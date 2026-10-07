#!/usr/bin/env python3
"""Mac Disk Cleanup — local dashboard and scheduled cleaner.

  cleanup.py                 start the dashboard at http://127.0.0.1:7777 and open it
  cleanup.py serve [--port N] [--no-open]
  cleanup.py scan [--deep]   print findings as a table
  cleanup.py auto [--dry-run] run the scheduled cleanup once (safe tier → Trash)
  cleanup.py schedule on|off|status
  cleanup.py install-app     create "Disk Cleanup.app" in /Applications (double-click to open the dashboard)
"""
from __future__ import annotations

import argparse
import json
import sys

from diskcleanup import auto, schedule, store
from diskcleanup.auto import fmt
from diskcleanup.scanner import run_scan
from diskcleanup.server import serve


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="cleanup", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("serve"); s.add_argument("--port", type=int, default=7777); s.add_argument("--no-open", action="store_true")
    s.add_argument("--idle-exit", type=int, default=0, metavar="MIN", help="quit after MIN minutes with no open page")
    sub.add_parser("install-app", help="create 'Disk Cleanup.app' in /Applications")
    sc = sub.add_parser("scan"); sc.add_argument("--deep", action="store_true"); sc.add_argument("--json", action="store_true")
    a = sub.add_parser("auto"); a.add_argument("--dry-run", action="store_true")
    sch = sub.add_parser("schedule"); sch.add_argument("state", choices=["on", "off", "status"])
    args = ap.parse_args(argv)

    if args.cmd in (None, "serve"):
        serve(port=getattr(args, "port", 7777), open_browser=not getattr(args, "no_open", False),
              idle_minutes=getattr(args, "idle_exit", 0))
        return 0
    if args.cmd == "install-app":
        from diskcleanup.macapp import install
        print(install())
        return 0
    if args.cmd == "scan":
        res = run_scan(deep=args.deep, excludes=store.settings().get("excludes", []),
                       progress=lambda p: print(f"\r  {p['done']}/{p['total']} {p['current']:<40}", end="", file=sys.stderr))
        print(file=sys.stderr)
        store.save_scan(res)
        if args.json:
            print(json.dumps(res, indent=1)); return 0
        d = res["disk"]
        print(f"Disk: {fmt(d['free'])} free of {fmt(d['total'])}\n")
        for tier in ("safe", "care", "personal", "inuse"):
            rows = [f for f in res["findings"] if f["tier"] == tier]
            if not rows:
                continue
            print(f"== {tier} ({fmt(sum(r['bytes'] for r in rows))}) ==")
            for f in rows:
                flag = f"  [quit {', '.join(f['blocked_by'])}]" if f["blocked_by"] else ""
                print(f"  {fmt(f['bytes']):>9}  {f['title']}{flag}\n             {f['display']}")
            print()
        return 0
    if args.cmd == "auto":
        rec = auto.run_auto(dry_run=args.dry_run)
        verb = "Would move" if args.dry_run else "Moved"
        print(f"{verb} {fmt(sum(i['bytes'] for i in rec['items'] if i['ok']))} across {len(rec['items'])} items to Trash.")
        for i in rec["items"]:
            print(f"  {'ok ' if i['ok'] else 'ERR'} {fmt(i['bytes']):>9}  {i['title']}" + (f"  — {i['error']}" if not i["ok"] else ""))
        return 0
    if args.cmd == "schedule":
        if args.state == "on":
            store.save_settings({"autoclean": {"enabled": True}}); print(schedule.install())
        elif args.state == "off":
            store.save_settings({"autoclean": {"enabled": False}}); print(schedule.remove())
        else:
            print(schedule.status())
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
