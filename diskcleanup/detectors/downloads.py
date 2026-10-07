from __future__ import annotations

import os
import time

from . import ScanContext, detector
from ..model import Action, Finding, SAFE, PERSONAL, CARE, CAT_INSTALLER, CAT_PERSONAL, CAT_SYSTEM, HOME
from ..sysinfo import du_bytes, du_children, mtime, run

MB = 1024 ** 2
INSTALLER_EXT = (".dmg", ".pkg", ".xip", ".iso")


@detector("Downloads")
def downloads(ctx: ScanContext) -> list[Finding]:
    root = os.path.join(HOME, "Downloads")
    if not os.path.isdir(root) or ctx.excluded(root):
        return []
    out = []
    week_ago = time.time() - 7 * 86400
    for path, size in du_children(root, min_bytes=25 * MB):
        name = os.path.basename(path)
        m = mtime(path) or 0
        if name.lower().endswith(INSTALLER_EXT):
            if m > week_ago:
                continue  # may not have been installed yet
            out.append(Finding(
                kind="installer", path=path, bytes=size, tier=SAFE, category=CAT_INSTALLER,
                title=name, reason="Installer image downloaded over a week ago. Once the app is installed it isn't needed.",
                action=Action("trash_path", label="Move to Trash"), mtime=m))
        else:
            out.append(Finding(
                kind="download", path=path, bytes=size, tier=PERSONAL, category=CAT_PERSONAL,
                title=name, reason="Looks like your own file. Shown for awareness only.", mtime=m))
    return out


@detector("Trash")
def trash(ctx: ScanContext) -> list[Finding]:
    path = os.path.join(HOME, ".Trash")
    size = du_bytes(path)
    if size == 0:
        # Either empty, or unreadable without Full Disk Access.
        code, _, err = run(["ls", path])
        if "Operation not permitted" not in err and code == 0:
            return []
        return [Finding(
            kind="trash", path=path, bytes=0, tier=CARE, category=CAT_SYSTEM,
            title="Trash (size unknown)",
            reason="macOS hides the Trash from apps without Full Disk Access. Empty it from Finder, "
                   "or grant this tool Full Disk Access in System Settings → Privacy & Security.",
            action=Action("empty_trash", permanent=True, label="Empty Trash via Finder"))]
    return [Finding(
        kind="trash", path=path, bytes=size, tier=CARE, category=CAT_SYSTEM, title="Trash",
        reason="Items already deleted but still taking space until the Trash is emptied.",
        action=Action("empty_trash", permanent=True, label="Empty Trash"))]
