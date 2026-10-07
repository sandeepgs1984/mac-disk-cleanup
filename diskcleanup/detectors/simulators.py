from __future__ import annotations

import json
import os
import time

from . import ScanContext, detector
from ..model import Action, Finding, CARE, SAFE, INUSE, CAT_SIM
from ..sysinfo import du_bytes, du_many, mtime, run

GB = 1024 ** 3
MB = 1024 ** 2


def _devices() -> list[dict]:
    code, out, _ = run(["xcrun", "simctl", "list", "devices", "-j"])
    if code != 0 or not out:
        return []
    try:
        data = json.loads(out)["devices"]
    except (ValueError, KeyError):
        return []
    devices = []
    for runtime, devs in data.items():
        rt = runtime.rsplit(".", 1)[-1].replace("-", " ", 1).replace("-", ".")
        for d in devs:
            d["runtime"] = rt
            devices.append(d)
    return devices


@detector("Simulators")
def simulators(ctx: ScanContext) -> list[Finding]:
    devices = _devices()
    if not devices:
        return []
    out: list[Finding] = []
    dead_paths = {d["udid"]: os.path.join(d["dataPath"], "Library/Caches/com.apple.containermanagerd/Dead")
                  for d in devices if d.get("dataPath")}
    sizes = du_many([d["dataPath"] for d in devices if d.get("dataPath")])
    dead_sizes = du_many(list(dead_paths.values()))
    stale_cutoff = time.time() - 45 * 86400

    for d in devices:
        data = d.get("dataPath")
        if not data:
            continue
        udid, name, state = d["udid"], d["name"], d.get("state", "Shutdown")
        label = f"{name} · {d['runtime']}"
        size = sizes.get(data, 0)
        booted = state == "Booted"

        dead = dead_sizes.get(dead_paths[udid], 0)
        if dead >= 200 * MB:
            try:
                count = len(os.listdir(dead_paths[udid]))
            except OSError:
                count = 0
            out.append(Finding(
                kind="sim-dead", path=dead_paths[udid], bytes=dead, tier=SAFE, category=CAT_SIM,
                title=f"Old app installs inside {name} ({count})",
                reason="Every reinstall leaves the previous copy of the app here. Your current install "
                       "is untouched. The simulator is shut down first if it's running.",
                action=Action("sim_dead_clear", {"udid": udid}, label="Clear old installs"),
                mtime=mtime(dead_paths[udid]), meta={"udid": udid, "device": label}))
            size -= dead

        if size < 300 * MB:
            continue
        if not d.get("isAvailable", True):
            out.append(Finding(
                kind="sim-unavailable", path=data, bytes=size, tier=SAFE, category=CAT_SIM,
                title=f"{label} (runtime no longer installed)",
                reason="Its OS runtime was removed, so this simulator can't boot any more.",
                action=Action("simctl_delete", {"udid": udid}, permanent=True, label="Delete simulator"),
                meta={"udid": udid}))
        elif booted:
            out.append(Finding(
                kind="sim-active", path=data, bytes=size, tier=INUSE, category=CAT_SIM,
                title=f"{label} (running)", reason="This simulator is booted right now.",
                meta={"udid": udid}))
        else:
            m = mtime(data) or 0
            stale = m < stale_cutoff
            out.append(Finding(
                kind="sim-idle", path=data, bytes=size, tier=CARE, category=CAT_SIM,
                title=label + (" (unused 45+ days)" if stale else ""),
                reason="Deleting removes the simulator and everything installed on it. "
                       "You can recreate it from Xcode → Devices and Simulators.",
                action=Action("simctl_delete", {"udid": udid}, permanent=True, label="Delete simulator"),
                mtime=m, meta={"udid": udid, "stale": stale}))
    out.sort(key=lambda f: -f.bytes)
    return out
