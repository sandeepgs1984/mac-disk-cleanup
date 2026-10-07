"""Detector registry. Each detector is `fn(ctx) -> list[Finding]`."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..model import Finding


@dataclass
class ScanContext:
    running: set[str]
    deep: bool = False
    fixture_dir: str | None = None
    excludes: list[str] = field(default_factory=list)

    def excluded(self, path: str) -> bool:
        return any(path == e or path.startswith(e.rstrip("/") + "/") for e in self.excludes)


Detector = Callable[[ScanContext], list[Finding]]

REGISTRY: list[tuple[str, Detector]] = []


def detector(name: str):
    def wrap(fn: Detector) -> Detector:
        REGISTRY.append((name, fn))
        return fn
    return wrap


# Import side-effect registers each module's detectors, in display order.
from . import xcode, simulators, caches, apps, claude_tmp, downloads, fixture  # noqa: E402,F401
