"""Persistence under ~/.disk-cleanup: settings, last scan, free-space history, run log."""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

from .model import AUTO_CATEGORIES, HOME

DIR = os.path.join(HOME, ".disk-cleanup")
_lock = threading.Lock()

DEFAULT_SETTINGS: dict[str, Any] = {
    "cleanMode": "trash",
    "excludes": [],
    "autoclean": {
        "enabled": False,
        "frequency": "weekly",   # daily | weekly
        "hour": 3,
        "weekday": 0,            # 0 = Sunday (launchd convention)
        "categories": list(AUTO_CATEGORIES),
        "notify": True,
    },
}


def _path(name: str) -> str:
    os.makedirs(DIR, exist_ok=True)
    return os.path.join(DIR, name)


def _read(name: str, default):
    try:
        with open(_path(name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _write(name: str, data) -> None:
    tmp = _path(name) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, _path(name))


def settings() -> dict:
    s = json.loads(json.dumps(DEFAULT_SETTINGS))
    saved = _read("settings.json", {})
    s.update({k: v for k, v in saved.items() if k != "autoclean"})
    s["autoclean"].update(saved.get("autoclean", {}))
    return s


def save_settings(new: dict) -> dict:
    with _lock:
        cur = settings()
        for k in ("cleanMode", "excludes"):
            if k in new:
                cur[k] = new[k]
        if "autoclean" in new:
            cur["autoclean"].update(new["autoclean"])
        _write("settings.json", cur)
        return cur


def last_scan() -> dict | None:
    return _read("last-scan.json", None)


def save_scan(scan: dict) -> None:
    with _lock:
        _write("last-scan.json", scan)
        hist = _read("history.json", [])
        reclaimable = sum(f["bytes"] for f in scan["findings"] if f["tier"] == "safe")
        hist.append({"t": scan["finishedAt"], "free": scan["disk"]["free"],
                     "total": scan["disk"]["total"], "reclaimable": reclaimable})
        _write("history.json", hist[-200:])


def history() -> list[dict]:
    return _read("history.json", [])


def runs() -> list[dict]:
    return _read("runs.json", [])


def record_run(run: dict) -> None:
    with _lock:
        r = _read("runs.json", [])
        r.append(run)
        _write("runs.json", r[-100:])
        if run.get("freed"):
            hist = _read("history.json", [])
            if hist:
                hist[-1]["freedAfter"] = hist[-1].get("freedAfter", 0) + run["freed"]
                _write("history.json", hist)


def mark_cleaned(ids: list[str]) -> None:
    """Drop cleaned findings from the cached scan so the page doesn't show stale items."""
    with _lock:
        scan = _read("last-scan.json", None)
        if not scan:
            return
        gone = set(ids)
        scan["findings"] = [f for f in scan["findings"] if f["id"] not in gone]
        _write("last-scan.json", scan)
