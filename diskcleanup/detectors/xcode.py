from __future__ import annotations

import os
import plistlib
import time

from . import ScanContext, detector
from ..model import (Action, Finding, CARE, SAFE, INUSE, CAT_XCODE, CAT_SIM, HOME)
from ..sysinfo import du_bytes, du_children, mtime, run

DEV = os.path.join(HOME, "Library/Developer")
GB = 1024 ** 3
MB = 1024 ** 2


def derived_data_root() -> str:
    code, out, _ = run(["defaults", "read", "com.apple.dt.Xcode", "IDECustomDerivedDataLocation"])
    custom = out.strip()
    if code == 0 and custom:
        return os.path.expanduser(custom) if custom.startswith("~") else custom
    return os.path.join(DEV, "Xcode/DerivedData")


def _workspace_for(dd_folder: str) -> str | None:
    try:
        with open(os.path.join(dd_folder, "info.plist"), "rb") as f:
            return plistlib.load(f).get("WorkspacePath")
    except Exception:
        return None


@detector("Xcode build data")
def derived_data(ctx: ScanContext) -> list[Finding]:
    root = derived_data_root()
    if not os.path.isdir(root) or ctx.excluded(root):
        return []
    out: list[Finding] = []
    xcode_running = "Xcode" in ctx.running
    for path, size in du_children(root, min_bytes=50 * MB):
        name = os.path.basename(path)
        if name in ("ModuleCache.noindex", "SDKExplicitPrecompiledModules",
                    "SymbolCache.noindex", "SDKStatCaches.noindex", "CompilationCache.noindex"):
            out.append(Finding(
                kind="dd-shared", path=path, bytes=size, tier=SAFE, category=CAT_XCODE,
                title=f"Xcode {name.replace('.noindex', '')}",
                reason="Shared compiler cache; Xcode rebuilds it on the next build.",
                action=Action("trash_path", label="Move to Trash"),
                requires_quit=["Xcode"], blocked_by=["Xcode"] if xcode_running else [],
                mtime=mtime(path)))
            continue
        ws = _workspace_for(path)
        project = name.rsplit("-", 1)[0]
        if ws and not os.path.exists(ws):
            out.append(Finding(
                kind="dd-orphan", path=path, bytes=size, tier=SAFE, category=CAT_XCODE,
                title=f"{project} build data (project no longer exists)",
                reason=f"Built from {ws}, which has been deleted or moved. Nothing uses this any more.",
                action=Action("trash_path", label="Move to Trash"), mtime=mtime(path),
                meta={"workspace": ws}))
        else:
            is_worktree = bool(ws and "/.claude/worktrees/" in ws)
            out.append(Finding(
                kind="dd-project", path=path, bytes=size, tier=SAFE, category=CAT_XCODE,
                title=f"{project} build data" + (" (Claude worktree)" if is_worktree else ""),
                reason=("Build output for a temporary agent worktree; safe once that task is done."
                        if is_worktree else
                        "Compiled build output. Deleting it forces a slow full rebuild next time."),
                action=Action("trash_path", label="Move to Trash"),
                requires_quit=["Xcode"], blocked_by=["Xcode"] if xcode_running else [],
                mtime=mtime(path), meta={"workspace": ws or ""},
                children=[{"name": os.path.basename(p), "bytes": b}
                          for p, b in du_children(path, min_bytes=100 * MB)[:6]]))
    return out


@detector("iOS device symbols")
def device_support(ctx: ScanContext) -> list[Finding]:
    out: list[Finding] = []
    for platform in ("iOS", "watchOS", "tvOS", "visionOS"):
        root = os.path.join(DEV, f"Xcode/{platform} DeviceSupport")
        if not os.path.isdir(root):
            continue
        for path, size in du_children(root, min_bytes=100 * MB):
            out.append(Finding(
                kind="devsupport", path=path, bytes=size, tier=SAFE, category=CAT_XCODE,
                title=f"{platform} debug symbols · {os.path.basename(path)}",
                reason="Symbol files copied from a connected device. Xcode copies them again the "
                       "next time you plug in a device on that OS version.",
                action=Action("trash_path", label="Move to Trash"), mtime=mtime(path)))
    return out


@detector("Xcode test clones")
def xctest_devices(ctx: ScanContext) -> list[Finding]:
    root = os.path.join(DEV, "XCTestDevices")
    size = du_bytes(root)
    if size < 50 * MB:
        return []
    try:
        count = len([d for d in os.listdir(root) if not d.startswith(".")])
    except OSError:
        count = 0
    return [Finding(
        kind="xctestdevices", path=root, bytes=size, tier=SAFE, category=CAT_SIM,
        title=f"Test-run simulator clones ({count})",
        reason="Copies Xcode makes for parallel test runs. It recreates them the next time you run tests.",
        action=Action("simctl_testing_delete_all", permanent=True, label="Delete clones"),
        requires_quit=["Xcode"], blocked_by=["Xcode"] if "Xcode" in ctx.running else [],
        mtime=mtime(root))]


@detector("Xcode archives")
def archives(ctx: ScanContext) -> list[Finding]:
    root = os.path.join(DEV, "Xcode/Archives")
    if not os.path.isdir(root):
        return []
    out = []
    cutoff = time.time() - 180 * 86400
    for day_dir, size in du_children(root, min_bytes=200 * MB):
        m = mtime(day_dir) or 0
        if m < cutoff:
            out.append(Finding(
                kind="archive", path=day_dir, bytes=size, tier=CARE, category=CAT_XCODE,
                title=f"Xcode archives from {os.path.basename(day_dir)}",
                reason="App Store / TestFlight archives older than 6 months. Keep any build whose "
                       "crash reports you may still need to symbolicate.",
                action=Action("trash_path", label="Move to Trash"), mtime=m))
    return out


@detector("Device connection cache")
def coredevice(ctx: ScanContext) -> list[Finding]:
    path = os.path.join(HOME, "Library/Containers/com.apple.CoreDevice.CoreDeviceService/Data")
    size = du_bytes(path)
    if size < 300 * MB:
        return []
    return [Finding(
        kind="coredevice", path=path, bytes=size, tier=CARE, category=CAT_XCODE,
        title="Physical-device connection cache",
        reason="Apple's cache for iPhones/iPads you've debugged on; it rebuilds itself. "
               "Unplug your devices and quit Xcode first.",
        action=Action("trash_children", label="Clear cache"),
        requires_quit=["Xcode"], blocked_by=["Xcode"] if "Xcode" in ctx.running else [],
        mtime=mtime(path))]
