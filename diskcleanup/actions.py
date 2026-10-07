"""Executes reclaim actions. Every entry point validates the path before touching it."""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import time

from .model import HOME
from .sysinfo import du_bytes, run

ALLOWED_ROOTS = [HOME, "/private/tmp/claude-", "/tmp/claude-"]
NEVER = {HOME, os.path.join(HOME, "Library"), os.path.join(HOME, "Desktop"),
         os.path.join(HOME, "Documents"), os.path.join(HOME, "Pictures"),
         os.path.join(HOME, "Library/Application Support")}


class ActionError(Exception):
    pass


def _check(path: str) -> str:
    real = os.path.realpath(path)
    if real in NEVER or real == "/":
        raise ActionError(f"Refusing to touch protected location {path}")
    inside_home = real.startswith(HOME + "/")
    claude_tmp = real.startswith("/private/tmp/claude-") or real.startswith("/tmp/claude-")
    if not (inside_home or claude_tmp):
        raise ActionError(f"Path outside allowed roots: {path}")
    if not os.path.lexists(real):
        raise ActionError(f"Already gone: {path}")
    return real


def _finder_trash(paths: list[str]) -> bool:
    """Ask Finder to trash the paths. Needed for other volumes; may show a one-time
    Automation permission prompt, so keep the timeout short."""
    items = ", ".join(f'POSIX file "{p}"' for p in paths)
    script = f'tell application "Finder" to delete {{{items}}}'
    code, _, err = run(["osascript", "-e", script], timeout=90)
    return code == 0


def _manual_trash(path: str) -> None:
    trash = os.path.join(HOME, ".Trash")
    dest = os.path.join(trash, os.path.basename(path))
    if os.path.lexists(dest):
        stamp = time.strftime("%H.%M.%S")
        root, ext = os.path.splitext(os.path.basename(path))
        dest = os.path.join(trash, f"{root} {stamp}{ext}")
    os.rename(path, dest)


def trash_paths(paths: list[str]) -> None:
    paths = [_check(p) for p in paths]
    # A rename into ~/.Trash is instant and needs no permissions on the same volume.
    # Anything that can't be renamed (other volume, EPERM) goes through Finder in one batch.
    leftovers: list[str] = []
    for p in paths:
        try:
            _manual_trash(p)
        except OSError:
            leftovers.append(p)
    for i in range(0, len(leftovers), 50):
        chunk = leftovers[i:i + 50]
        if not _finder_trash(chunk):
            still = [p for p in chunk if os.path.lexists(p)]
            if still:
                raise ActionError("Could not move to Trash: " + ", ".join(os.path.basename(p) for p in still)
                                  + ". If macOS asked whether Python may control Finder, allow it and retry.")


def delete_paths(paths: list[str]) -> None:
    for p in paths:
        real = _check(p)
        if os.path.isdir(real) and not os.path.islink(real):
            shutil.rmtree(real, ignore_errors=False)
        else:
            os.remove(real)


def _children(path: str, keep: list[str] | None = None) -> list[str]:
    keep = set(keep or [])
    return [os.path.join(path, n) for n in os.listdir(path) if n not in keep]


def execute(finding: dict, mode: str = "trash") -> dict:
    """Run a finding's action. Returns {freed, note}. mode: 'trash' | 'delete'."""
    act = finding["action"]
    typ, args, path = act["type"], act.get("args", {}), finding["path"]
    before = finding.get("bytes", 0)
    remove = delete_paths if mode == "delete" else trash_paths
    note = "Moved to Trash — empty the Trash to reclaim the space." if mode == "trash" else "Deleted."

    if typ == "trash_path":
        remove([path])
    elif typ == "trash_children":
        remove(_children(_check(path)))
    elif typ == "trash_children_except":
        remove(_children(_check(path), args.get("keep")))
    elif typ == "sim_dead_clear":
        run(["xcrun", "simctl", "shutdown", args["udid"]])
        remove(_children(_check(path)))
    elif typ == "simctl_delete":
        code, _, err = run(["xcrun", "simctl", "delete", args["udid"]])
        if code != 0:
            raise ActionError(err.strip() or "simctl delete failed")
        note = "Simulator deleted."
    elif typ == "simctl_testing_delete_all":
        code, _, err = run(["xcrun", "simctl", "--set", "testing", "delete", "all"])
        if code != 0:
            raise ActionError(err.strip() or "simctl delete failed")
        note = "Test clones deleted."
    elif typ == "brew_cleanup":
        code, _, err = run(["brew", "cleanup", "-s", "--prune=all"], timeout=900)
        if code != 0:
            raise ActionError(err.strip() or "brew cleanup failed")
        note = "Homebrew cleanup finished."
    elif typ == "uv_cache_clean":
        code, _, err = run(["uv", "cache", "clean"])
        if code != 0:
            raise ActionError(err.strip() or "uv cache clean failed")
        note = "uv cache cleared."
    elif typ == "pod_repo_remove":
        code, _, err = run(["pod", "repo", "remove", args["name"]])
        if code != 0:
            # pod may not be on PATH; the folder itself is still safe to remove.
            remove([path])
        note = "Legacy specs repo removed."
    elif typ == "sqlite_vacuum":
        _check(path)
        code, _, err = run(["sqlite3", path, "VACUUM;"], timeout=1800)
        if code != 0:
            raise ActionError(err.strip() or "VACUUM failed")
        note = "Database compacted in place."
    elif typ == "kill_process":
        pid = int(args["pid"])
        try:
            os.kill(pid, 15)
        except ProcessLookupError:
            pass
        note = "Process stopped."
        return {"freed": 0, "note": note}
    elif typ == "empty_trash":
        code, _, err = run(["osascript", "-e", 'tell application "Finder" to empty trash'], timeout=1800)
        if code != 0:
            raise ActionError(err.strip() or "Finder refused to empty the Trash")
        return {"freed": before, "note": "Trash emptied."}
    else:
        raise ActionError(f"No action for {typ}")

    after = du_bytes(path) if os.path.lexists(path) else 0
    freed = max(0, before - after) if typ in ("sqlite_vacuum", "trash_children", "trash_children_except",
                                                "sim_dead_clear", "brew_cleanup", "uv_cache_clean") else before
    return {"freed": freed, "note": note}
