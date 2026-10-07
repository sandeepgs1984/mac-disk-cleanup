"""Test fixture detector: surfaces children of DISK_CLEANUP_FIXTURE_DIR as safe items.

Lets the clean pipeline be exercised end-to-end on throwaway files instead of real caches.
"""
from __future__ import annotations

import os

from . import ScanContext, detector
from ..model import Action, Finding, SAFE
from ..sysinfo import du_children, mtime


@detector("Test fixture")
def fixture(ctx: ScanContext) -> list[Finding]:
    if not ctx.fixture_dir or not os.path.isdir(ctx.fixture_dir):
        return []
    return [Finding(kind="fixture", path=p, bytes=b, tier=SAFE, category="Test fixture",
                    title=f"Fixture · {os.path.basename(p)}", reason="Throwaway test data.",
                    action=Action("trash_path", label="Move to Trash"), mtime=mtime(p))
            for p, b in du_children(ctx.fixture_dir)]
