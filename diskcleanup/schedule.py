"""launchd integration for scheduled auto-cleanup."""
from __future__ import annotations

import os
import plistlib

from .model import HOME
from .store import DIR, settings
from .sysinfo import run

LABEL = "com.sandeepgs.mac-disk-cleanup"
PLIST = os.path.join(HOME, "Library/LaunchAgents", LABEL + ".plist")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _domain() -> str:
    return f"gui/{os.getuid()}"


def is_installed() -> bool:
    code, _, _ = run(["launchctl", "print", f"{_domain()}/{LABEL}"])
    return code == 0


def install() -> dict:
    s = settings()["autoclean"]
    interval = {"Hour": int(s["hour"]), "Minute": 0}
    if s["frequency"] == "weekly":
        interval["Weekday"] = int(s["weekday"])
    plist = {
        "Label": LABEL,
        # bin/cleanup resolves Python at run time, so a Homebrew upgrade can't break the schedule.
        "ProgramArguments": [os.path.join(ROOT, "bin", "cleanup"), "auto"],
        "StartCalendarInterval": interval,
        "RunAtLoad": False,
        "StandardOutPath": os.path.join(DIR, "launchd.log"),
        "StandardErrorPath": os.path.join(DIR, "launchd.log"),
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:" + os.path.join(HOME, "bin")},
    }
    os.makedirs(os.path.dirname(PLIST), exist_ok=True)
    os.makedirs(DIR, exist_ok=True)
    with open(PLIST, "wb") as f:
        plistlib.dump(plist, f)
    run(["launchctl", "bootout", f"{_domain()}/{LABEL}"])
    code, _, err = run(["launchctl", "bootstrap", _domain(), PLIST])
    if code != 0:
        return {"installed": False, "error": err.strip() or "launchctl bootstrap failed"}
    return {"installed": True, "plist": PLIST, "interval": interval}


def remove() -> dict:
    run(["launchctl", "bootout", f"{_domain()}/{LABEL}"])
    try:
        os.remove(PLIST)
    except FileNotFoundError:
        pass
    return {"installed": False}


def status() -> dict:
    s = settings()["autoclean"]
    return {"installed": is_installed(), "plist": PLIST, "frequency": s["frequency"],
            "hour": s["hour"], "weekday": s["weekday"]}
