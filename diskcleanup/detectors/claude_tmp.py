from __future__ import annotations

import glob
import os
import time

from . import ScanContext, detector
from ..model import Action, Finding, CARE, SAFE, CAT_CLAUDE
from ..sysinfo import du_bytes, du_children, newest_mtime, processes_matching

MB = 1024 ** 2
RECENT = 30 * 60


@detector("Claude Code scratch space")
def claude_tmp(ctx: ScanContext) -> list[Finding]:
    out: list[Finding] = []
    for root in glob.glob("/private/tmp/claude-*"):
        if not os.path.isdir(root):
            continue
        for project_dir, _ in du_children(root, min_bytes=100 * MB):
            pname = os.path.basename(project_dir)
            if pname == "bash-edit-diff":
                out.append(Finding(
                    kind="claude-diffs", path=project_dir, bytes=du_bytes(project_dir), tier=SAFE,
                    category=CAT_CLAUDE, title="Claude Code edit diffs",
                    reason="Temporary diff files from past edits.",
                    action=Action("trash_path", label="Move to Trash")))
                continue
            project = pname.strip("-").replace("-", "/")
            short = project.split("/")[-1] if "/" in project else project
            for session_dir, _ in du_children(project_dir, min_bytes=100 * MB):
                sid = os.path.basename(session_dir)
                alive = bool(processes_matching(sid))
                scratch = os.path.join(session_dir, "scratchpad")
                for path, size in du_children(scratch if os.path.isdir(scratch) else session_dir, min_bytes=100 * MB):
                    newest = newest_mtime(path, max_depth=3)
                    recent = (time.time() - (newest or 0)) < RECENT
                    name = os.path.basename(path)
                    tier = CARE if (alive and recent) else SAFE
                    reason = (f"Private build output left by a Claude Code session in {short}. "
                              "Xcode already keeps its own copy in DerivedData.")
                    if alive and recent:
                        reason += " That session is active and wrote here in the last 30 minutes."
                    elif alive:
                        reason += " The session is still open but hasn't used this folder recently."
                    out.append(Finding(
                        kind="claude-scratch", path=path, bytes=size, tier=tier, category=CAT_CLAUDE,
                        title=f"{short} · session {sid[:8]} · {name}", reason=reason,
                        action=Action("trash_path", label="Move to Trash"),
                        mtime=newest,
                        meta={"session": sid, "alive": alive, "recent": recent}))

    # Orphaned build scripts (parent = launchd) still pointing into scratch space.
    for pid, ppid, cmd in processes_matching("/tmp/claude-"):
        if ppid == 1 and ("/bin/sh" in cmd or "upload-symbols" in cmd):
            out.append(Finding(
                kind="orphan-proc", path=f"pid:{pid}", bytes=0, tier=CARE, category=CAT_CLAUDE,
                title=f"Stuck build script (pid {pid})",
                reason="A build-phase script left running after its Claude session ended. "
                       "It holds files open and may block cleanup.",
                action=Action("kill_process", {"pid": pid}, permanent=True, label="Stop process"),
                meta={"command": cmd[:200]}))
    out.sort(key=lambda f: -f.bytes)
    return out
