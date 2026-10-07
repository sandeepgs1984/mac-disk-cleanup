from __future__ import annotations

import glob
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from .detectors import REGISTRY, ScanContext
from .model import Finding, HOME, shorten
from .sysinfo import disk_info, du_children, running_apps

Progress = Callable[[dict], None]
GB = 1024 ** 3


def _overview() -> list[dict]:
    """Top-level 'where does the space go' for the deep scan treemap."""
    items: list[tuple[str, int]] = []
    items += du_children(HOME, min_bytes=GB // 2)
    for p in ("/private/tmp", "/Applications", "/Users/Shared"):
        items += du_children(p, min_bytes=GB)
    seen, out = set(), []
    for path, size in sorted(items, key=lambda t: -t[1]):
        if path in seen:
            continue
        seen.add(path)
        out.append({"path": path, "display": shorten(path), "bytes": size})
    return out[:40]


def run_scan(deep: bool = False, fixture_dir: str | None = None, excludes: list[str] | None = None,
             progress: Progress | None = None, only: set[str] | None = None) -> dict:
    started = time.time()
    running = running_apps()
    ctx = ScanContext(running=running, deep=deep, fixture_dir=fixture_dir, excludes=excludes or [])
    registry = [(n, fn) for n, fn in REGISTRY if not only or n in only]
    total = len(registry) + (1 if deep else 0)
    done = 0
    findings: dict[str, Finding] = {}
    overview: list[dict] = []
    timings: dict[str, float] = {}
    lock = threading.Lock()

    def timed(name, fn):
        def go(c):
            t0 = time.time()
            try:
                return fn(c)
            finally:
                timings[name] = round(time.time() - t0, 1)
        return go

    def emit(current: str):
        if progress:
            progress({"done": done, "total": total, "current": current,
                      "findings": [f.to_dict() for f in findings.values()]})

    emit("Starting")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(timed(name, fn), ctx): name for name, fn in registry}
        if deep:
            ov_future = pool.submit(timed("Whole-disk overview", lambda c: _overview()), ctx)
            futures[ov_future] = "Whole-disk overview"
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                result = fut.result()
            except Exception as e:  # a broken detector must not kill the scan
                result = []
                print(f"[scan] {name} failed: {e!r}")
            with lock:
                if name == "Whole-disk overview":
                    overview = result
                else:
                    for f in result:
                        findings[f.id] = f
                done += 1
                emit(name)

    ordered = sorted(findings.values(), key=lambda f: -f.bytes)
    disk = disk_info("/")
    return {
        "startedAt": started,
        "finishedAt": time.time(),
        "deep": deep,
        "running": sorted(running),
        "disk": disk.to_dict(),
        "findings": [f.to_dict() for f in ordered],
        "overview": overview,
        "timings": dict(sorted(timings.items(), key=lambda kv: -kv[1])),
    }
