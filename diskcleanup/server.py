from __future__ import annotations

import json
import mimetypes
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from . import actions, schedule, store
from .scanner import run_scan
from .sysinfo import disk_info, run, running_apps

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(ROOT, "static")
TOKEN = secrets.token_urlsafe(24)


class Job:
    """Background scan or clean with a snapshot the UI polls."""

    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.state: dict = {}

    def snapshot(self) -> dict:
        with self.lock:
            return {"running": self.running, **json.loads(json.dumps(self.state))}

    def update(self, **kw):
        with self.lock:
            self.state.update(kw)


scan_job = Job()
clean_job = Job()


def start_scan(deep: bool, only: list[str] | None = None) -> bool:
    with scan_job.lock:
        if scan_job.running:
            return False
        scan_job.running = True
        scan_job.state = {"done": 0, "total": 1, "current": "Starting", "findings": [], "startedAt": time.time()}

    def work():
        try:
            s = store.settings()
            result = run_scan(deep=deep, fixture_dir=os.environ.get("DISK_CLEANUP_FIXTURE_DIR"),
                              excludes=s.get("excludes", []), progress=lambda p: scan_job.update(**p),
                              only=set(only) if only else None)
            store.save_scan(result)
            scan_job.update(result=True)
        except Exception as e:
            scan_job.update(error=repr(e))
        finally:
            with scan_job.lock:
                scan_job.running = False

    threading.Thread(target=work, daemon=True).start()
    return True


def start_clean(ids: list[str], mode: str, force: bool) -> dict:
    scan = store.last_scan()
    if not scan:
        return {"error": "Run a scan first."}
    by_id = {f["id"]: f for f in scan["findings"]}
    picked, errors = [], []
    running = running_apps()
    for i in ids:
        f = by_id.get(i)
        if not f:
            errors.append({"id": i, "error": "Unknown item — rescan."})
        elif f["tier"] not in ("safe", "care"):
            errors.append({"id": i, "error": "This item is view-only."})
        elif f["action"]["type"] == "none":
            errors.append({"id": i, "error": "No action available."})
        elif not force and any(a in running for a in f.get("requires_quit", [])):
            errors.append({"id": i, "error": f"Quit {', '.join(f['requires_quit'])} first."})
        else:
            picked.append(f)
    if not picked:
        return {"error": errors[0]["error"] if errors else "Nothing selected.", "rejected": errors}
    with clean_job.lock:
        if clean_job.running:
            return {"error": "A clean is already running."}
        clean_job.running = True
        clean_job.state = {"mode": mode, "startedAt": time.time(), "freed": 0, "total": len(picked),
                           "items": [{"id": f["id"], "title": f["title"], "bytes": f["bytes"], "status": "pending"}
                                     for f in picked],
                           "rejected": errors}

    def work():
        freed, done_ids = 0, []
        for idx, f in enumerate(picked):
            items = clean_job.state["items"]
            items[idx]["status"] = "working"
            clean_job.update(items=items, current=f["title"])
            try:
                r = actions.execute(f, mode=mode)
                freed += r["freed"]
                items[idx].update(status="done", freed=r["freed"], note=r["note"])
                done_ids.append(f["id"])
            except Exception as e:
                items[idx].update(status="failed", error=str(e))
            clean_job.update(items=items, freed=freed)
        store.mark_cleaned(done_ids)
        store.record_run({"t": time.time(), "kind": "manual", "mode": mode, "freed": freed,
                          "count": len(done_ids),
                          "items": [{k: v for k, v in it.items() if k != "note"} for it in clean_job.state["items"]]})
        clean_job.update(disk=disk_info("/").to_dict(), finishedAt=time.time())
        with clean_job.lock:
            clean_job.running = False

    threading.Thread(target=work, daemon=True).start()
    return {"started": True, "count": len(picked), "rejected": errors}


class Handler(BaseHTTPRequestHandler):
    server_version = "DiskCleanup/0.1"
    last_seen = time.time()

    def parse_request(self):
        Handler.last_seen = time.time()
        return super().parse_request()

    def log_message(self, fmt, *args):  # quieter console
        first = str(args[0]) if args else ""
        if "/api/" in first and ("status" in first or "ping" in first):
            return
        super().log_message(fmt, *args)

    # ---- helpers -------------------------------------------------------
    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n))
        except ValueError:
            return {}

    def _authorized(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        origin = self.headers.get("Origin")
        if host not in ("127.0.0.1", "localhost"):
            return False
        if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost"):
            return False
        return self.headers.get("X-Token") == TOKEN

    def _static(self, rel: str):
        path = os.path.normpath(os.path.join(STATIC, rel.lstrip("/")))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            return self._json({"error": "not found"}, 404)
        with open(path, "rb") as f:
            data = f.read()
        if rel.endswith("index.html"):
            data = data.replace(b"__TOKEN__", TOKEN.encode())
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") or "javascript" in ctype else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    # ---- routes --------------------------------------------------------
    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            return self._static("index.html")
        if p.startswith("/static/"):
            return self._static(p[len("/static/"):])
        if p == "/api/state":
            return self._json({
                "disk": disk_info("/").to_dict(),
                "running": sorted(running_apps()),
                "scan": store.last_scan(),
                "scanning": scan_job.snapshot(),
                "settings": store.settings(),
                "schedule": schedule.status(),
                "history": store.history(),
                "runs": store.runs()[-20:],
            })
        if p == "/api/ping":
            return self._json({"ok": True})
        if p == "/api/scan/status":
            return self._json(scan_job.snapshot())
        if p == "/api/clean/status":
            return self._json(clean_job.snapshot())
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._authorized():
            return self._json({"error": "unauthorized"}, 403)
        p = urlparse(self.path).path
        body = self._body()
        if p == "/api/scan":
            return self._json({"started": start_scan(bool(body.get("deep")), body.get("only"))})
        if p == "/api/clean":
            mode = "delete" if body.get("mode") == "delete" else "trash"
            return self._json(start_clean(list(body.get("ids", [])), mode, bool(body.get("force"))))
        if p == "/api/reveal":
            scan = store.last_scan() or {"findings": []}
            f = next((x for x in scan["findings"] if x["id"] == body.get("id")), None)
            if not f or f["path"].startswith("pid:"):
                return self._json({"error": "unknown item"}, 404)
            code, _, err = run(["open", "-R", f["path"]])
            return self._json({"ok": code == 0, "error": err.strip()})
        if p == "/api/settings":
            s = store.save_settings(body)
            if schedule.is_installed():
                schedule.install()  # re-write the plist with the new time/frequency
            return self._json(s)
        if p == "/api/schedule":
            if body.get("enabled"):
                store.save_settings({"autoclean": {"enabled": True}})
                return self._json(schedule.install())
            store.save_settings({"autoclean": {"enabled": False}})
            return self._json(schedule.remove())
        if p == "/api/open-trash":
            run(["open", os.path.expanduser("~/.Trash")])
            return self._json({"ok": True})
        return self._json({"error": "not found"}, 404)


def _already_ours(port: int) -> bool:
    """True if something answering on this port is a Disk Cleanup dashboard."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=2) as r:
            return r.headers.get("Server", "").startswith("DiskCleanup")
    except Exception:
        return False


def serve(port: int = 7777, open_browser: bool = True, idle_minutes: int = 0) -> None:
    httpd = None
    for candidate in range(port, port + 10):
        try:
            httpd = ThreadingHTTPServer(("127.0.0.1", candidate), Handler)
            port = candidate
            break
        except OSError as e:
            if e.errno != 48:  # EADDRINUSE
                raise
            if _already_ours(candidate):
                url = f"http://127.0.0.1:{candidate}/"
                print(f"Disk Cleanup is already running → {url}")
                if open_browser:
                    run(["open", url])
                return
    if httpd is None:
        raise SystemExit(f"No free port between {port} and {port + 9}.")

    url = f"http://127.0.0.1:{port}/"
    print(f"Disk Cleanup dashboard → {url}")
    if open_browser:
        run(["open", url])

    if idle_minutes:
        # Shut down once no page has pinged for a while (the app launcher uses this so a
        # Finder-launched server doesn't live forever after the tab is closed).
        def watchdog():
            while True:
                time.sleep(30)
                if time.time() - Handler.last_seen > idle_minutes * 60 and not scan_job.running and not clean_job.running:
                    print("Idle — shutting down.")
                    httpd.shutdown()
                    return
        threading.Thread(target=watchdog, daemon=True).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
