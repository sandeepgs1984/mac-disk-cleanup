from __future__ import annotations

import os

from . import ScanContext, detector
from ..model import Action, Finding, CARE, SAFE, INUSE, CAT_EDITOR, CAT_APPDATA, HOME
from ..sysinfo import du_bytes, du_children, mtime, which

GB = 1024 ** 3
MB = 1024 ** 2
APPSUP = os.path.join(HOME, "Library/Application Support")

# VS Code–family editors: (app-support folder, app name for the running check)
EDITORS = [("Cursor", "Cursor"), ("Code", "Visual Studio Code"), ("Kiro", "Kiro"),
           ("Qoder", "Qoder"), ("Antigravity", "Antigravity"), ("Windsurf", "Windsurf")]


def _blocked(ctx: ScanContext, app: str) -> list[str]:
    return [app] if app in ctx.running else []


@detector("Editors & AI tools")
def editors(ctx: ScanContext) -> list[Finding]:
    out: list[Finding] = []
    for folder, app in EDITORS:
        base = os.path.join(APPSUP, folder)
        if not os.path.isdir(base):
            continue
        gs = os.path.join(base, "User/globalStorage")

        db = os.path.join(gs, "state.vscdb")
        size = du_bytes(db)
        if size >= 300 * MB:
            out.append(Finding(
                kind="vscdb", path=db, bytes=size, tier=CARE, category=CAT_EDITOR,
                title=f"{app} settings & chat-history database",
                reason="Holds settings and AI chat history, and grows with unused space over time. "
                       "Compacting keeps everything and only reclaims the slack.",
                action=Action("sqlite_vacuum", label="Compact database"),
                requires_quit=[app], blocked_by=_blocked(ctx, app), mtime=mtime(db)))
        backup = db + ".backup"
        size = du_bytes(backup)
        if size >= 100 * MB:
            out.append(Finding(
                kind="vscdb-backup", path=backup, bytes=size, tier=SAFE, category=CAT_EDITOR,
                title=f"{app} database backup copy",
                reason="A backup the editor makes of its state database; it creates a fresh one.",
                action=Action("trash_path", label="Move to Trash"), mtime=mtime(backup)))

        versions = os.path.join(gs, "anysphere.cursor-agent-worker/agent-cli/.local/share/cursor-agent/versions")
        if os.path.isdir(versions):
            kids = du_children(versions)
            names = sorted(os.path.basename(p) for p, _ in kids)
            if len(names) > 1:
                latest = names[-1]
                old = [(p, b) for p, b in kids if os.path.basename(p) != latest]
                total = sum(b for _, b in old)
                if total >= 100 * MB:
                    out.append(Finding(
                        kind="cursor-agent-versions", path=versions, bytes=total, tier=SAFE,
                        category=CAT_EDITOR, title=f"Old Cursor agent versions ({len(old)})",
                        reason=f"Cursor keeps every past agent CLI. Only the newest ({latest}) is used; it stays.",
                        action=Action("trash_children_except", {"keep": [latest]}, label="Remove old versions"),
                        mtime=mtime(versions), meta={"keep": latest},
                        children=[{"name": os.path.basename(p), "bytes": b} for p, b in old]))

        for sub in ("Cache", "Code Cache", "CachedData", "logs"):
            p = os.path.join(base, sub)
            size = du_bytes(p)
            if size >= 150 * MB:
                out.append(Finding(
                    kind="editor-cache", path=p, bytes=size, tier=CARE, category=CAT_EDITOR,
                    title=f"{app} {sub.lower()}", reason=f"Rebuilt automatically. Quit {app} first.",
                    action=Action("trash_path", label="Move to Trash"),
                    requires_quit=[app], blocked_by=_blocked(ctx, app), mtime=mtime(p)))
    return out


@detector("Claude desktop app")
def claude_app(ctx: ScanContext) -> list[Finding]:
    base = os.path.join(APPSUP, "Claude")
    if not os.path.isdir(base):
        return []
    out = []
    for sub in ("Cache", "Code Cache"):
        p = os.path.join(base, sub)
        size = du_bytes(p)
        if size >= 150 * MB:
            out.append(Finding(
                kind="claude-cache", path=p, bytes=size, tier=CARE, category=CAT_EDITOR,
                title=f"Claude app {sub.lower()}", reason="Electron cache; rebuilt automatically. Quit Claude first.",
                action=Action("trash_path", label="Move to Trash"),
                requires_quit=["Claude"], blocked_by=_blocked(ctx, "Claude"), mtime=mtime(p)))
    vm = os.path.join(base, "vm_bundles")
    size = du_bytes(vm)
    if size >= 1 * GB:
        out.append(Finding(kind="claude-vm", path=vm, bytes=size, tier=INUSE, category=CAT_APPDATA,
                           title="Claude sandbox VM images",
                           reason="The sandbox the Claude desktop app runs Claude Code sessions in. Core functionality."))
    return out


@detector("Large app data")
def large_app_support(ctx: ScanContext) -> list[Finding]:
    """Informational: App Support folders over 1 GB that no specific detector claimed."""
    if not os.path.isdir(APPSUP):
        return []
    claimed = {"Cursor", "Code", "Kiro", "Qoder", "Antigravity", "Windsurf", "Claude"}
    out = []
    for path, size in du_children(APPSUP, min_bytes=1 * GB):
        name = os.path.basename(path)
        if name in claimed:
            continue
        out.append(Finding(kind="appsupport", path=path, bytes=size, tier=INUSE, category=CAT_APPDATA,
                           title=f"{name} app data",
                           reason="Real application data (profiles, databases, downloads), not cache.",
                           mtime=mtime(path)))
    return out
