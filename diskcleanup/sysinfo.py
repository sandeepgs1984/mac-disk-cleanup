from __future__ import annotations

import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor

from .model import DiskInfo

_DU_POOL = ThreadPoolExecutor(max_workers=6)


def run(cmd: list[str], timeout: int = 600) -> tuple[int, str, str]:
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                             start_new_session=True)
    except FileNotFoundError as e:
        return 1, "", str(e)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err
    except subprocess.TimeoutExpired:
        p.kill()
        try:
            # A child stuck in an uninterruptible disk read ignores SIGKILL until the read
            # returns; don't let that pin the whole scan. Abandon it after a short grace period.
            out, err = p.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            out, err = "", ""
        return 124, out or "", f"timed out after {timeout}s"


def disk_info(path: str = "/") -> DiskInfo:
    u = shutil.disk_usage(path)
    return DiskInfo(total=u.total, used=u.used, free=u.free)


DU_TIMEOUT = 150  # one pathological folder must not stall the whole scan


def du_bytes(path: str) -> int:
    """Size of a path in bytes via `du -sk` (fast, follows no symlinks)."""
    if not os.path.lexists(path):
        return 0
    code, out, _ = run(["du", "-skx", path], timeout=DU_TIMEOUT)
    if not out:
        return 0
    try:
        return int(out.split()[0]) * 1024
    except ValueError:
        return 0


def du_children(path: str, min_bytes: int = 0) -> list[tuple[str, int]]:
    """Sizes of every direct child (files and dirs), largest first."""
    try:
        names = os.listdir(path)
    except OSError:
        return []
    paths = [os.path.join(path, n) for n in names]
    if not paths:
        return []
    out: list[tuple[str, int]] = []
    # du accepts many args at once; chunk to stay under ARG_MAX comfortably.
    for i in range(0, len(paths), 200):
        chunk = paths[i:i + 200]
        _, text, _ = run(["du", "-skx", *chunk], timeout=DU_TIMEOUT)
        for line in text.splitlines():
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            try:
                size = int(parts[0]) * 1024
            except ValueError:
                continue
            if size >= min_bytes:
                out.append((parts[1], size))
    out.sort(key=lambda t: -t[1])
    return out


def du_many(paths: list[str]) -> dict[str, int]:
    futures = {p: _DU_POOL.submit(du_bytes, p) for p in paths}
    return {p: f.result() for p, f in futures.items()}


def mtime(path: str) -> float | None:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def newest_mtime(path: str, max_depth: int = 3, dir_budget: int = 400) -> float | None:
    """Newest modification time within a tree — bounded depth and directory count.

    Build trees have hundreds of thousands of directories; a full walk takes minutes.
    Directory mtimes change whenever an entry is added/removed, so sampling the top of the
    tree is a good-enough recency signal.
    """
    newest = mtime(path)
    base_depth = path.rstrip("/").count("/")
    visited = 0
    for root, dirs, files in os.walk(path):
        visited += 1
        if visited > dir_budget:
            break
        if root.count("/") - base_depth >= max_depth:
            dirs[:] = []
        for n in files[:30]:
            m = mtime(os.path.join(root, n))
            if m and (newest is None or m > newest):
                newest = m
        d = mtime(root)
        if d and (newest is None or d > newest):
            newest = d
    return newest


_APP_PROCS = {
    "Xcode": ("/Xcode.app/Contents/MacOS/Xcode", "/Xcode-beta.app/Contents/MacOS/Xcode"),
    "Simulator": ("/Simulator.app/Contents/MacOS/Simulator",),
    "Cursor": ("/Cursor.app/Contents/MacOS/Cursor",),
    "Visual Studio Code": ("/Visual Studio Code.app/Contents/MacOS/Electron",),
    "Claude": ("/Claude.app/Contents/MacOS/Claude",),
    "Codex": ("/Codex.app/Contents/MacOS/Codex",),
    "Google Chrome": ("/Google Chrome.app/Contents/MacOS/Google Chrome",),
    "LM Studio": ("/LM Studio.app/Contents/MacOS/LM Studio",),
}


def running_apps() -> set[str]:
    _, out, _ = run(["ps", "-axo", "comm="])
    comms = out.splitlines()
    found: set[str] = set()
    for app, needles in _APP_PROCS.items():
        if any(c.rstrip().endswith(n) for c in comms for n in needles):
            found.add(app)
    return found


def processes_matching(needle: str) -> list[tuple[int, int, str]]:
    """(pid, ppid, command) for processes whose command line contains needle."""
    _, out, _ = run(["ps", "-axo", "pid=,ppid=,command="])
    hits = []
    for line in out.splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) == 3 and needle in parts[2]:
            hits.append((int(parts[0]), int(parts[1]), parts[2]))
    return hits


def which(name: str) -> str | None:
    return shutil.which(name)
