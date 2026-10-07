"""Headless auto-cleanup: safe tier only, Trash only, categories from settings."""
from __future__ import annotations

import time

from . import actions, store
from .model import SAFE
from .scanner import run_scan
from .sysinfo import run


def fmt(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit not in ("B", "KB") else f"{int(n)} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def notify(title: str, body: str) -> None:
    safe = body.replace('"', "'")
    run(["osascript", "-e", f'display notification "{safe}" with title "{title}"'])


def run_auto(dry_run: bool = False) -> dict:
    s = store.settings()
    auto = s["autoclean"]
    scan = run_scan(deep=False, excludes=s.get("excludes", []))
    store.save_scan(scan)
    picks = [f for f in scan["findings"]
             if f["tier"] == SAFE and f["selectable"] and not f["action"]["permanent"]
             and f["category"] in auto["categories"]]
    results, freed = [], 0
    for f in picks:
        if dry_run:
            results.append({"id": f["id"], "title": f["title"], "bytes": f["bytes"], "ok": True, "dry": True})
            continue
        try:
            r = actions.execute(f, mode="trash")
            freed += r["freed"]
            results.append({"id": f["id"], "title": f["title"], "bytes": f["bytes"], "ok": True})
        except Exception as e:
            results.append({"id": f["id"], "title": f["title"], "bytes": f["bytes"], "ok": False, "error": str(e)})
    if not dry_run:
        store.mark_cleaned([r["id"] for r in results if r["ok"]])
    record = {"t": time.time(), "kind": "auto", "dryRun": dry_run, "freed": freed,
              "count": len([r for r in results if r["ok"]]), "items": results,
              "freeBefore": scan["disk"]["free"]}
    store.record_run(record)
    if auto.get("notify") and not dry_run:
        if freed:
            notify("Disk Cleanup", f"Moved {fmt(freed)} across {record['count']} items to Trash. "
                                   "Empty the Trash to reclaim it.")
        else:
            notify("Disk Cleanup", "Nothing new to clean.")
    return record
