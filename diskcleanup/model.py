from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field, asdict
from typing import Any

HOME = os.path.expanduser("~")

# Tiers decide what the UI lets the user do with a finding.
SAFE = "safe"          # regenerates automatically; selectable, preselected
CARE = "care"          # reclaimable but loses state or needs a precondition
PERSONAL = "personal"  # user content; shown for awareness, never actionable
INUSE = "inuse"        # real app data; shown so the user knows it was seen

TIERS = (SAFE, CARE, PERSONAL, INUSE)

# Categories drive the treemap and the auto-cleanup category picker.
CAT_XCODE = "Xcode builds"
CAT_SIM = "Simulators"
CAT_CACHE = "App caches"
CAT_PKG = "Package managers"
CAT_EDITOR = "Editors & AI tools"
CAT_CLAUDE = "Claude scratch"
CAT_INSTALLER = "Installers"
CAT_APPDATA = "App data"
CAT_PERSONAL = "Personal files"
CAT_SYSTEM = "System"

AUTO_CATEGORIES = (CAT_XCODE, CAT_SIM, CAT_CACHE, CAT_PKG, CAT_EDITOR, CAT_CLAUDE, CAT_INSTALLER)


def shorten(path: str) -> str:
    if path == HOME or path.startswith(HOME + "/"):
        return "~" + path[len(HOME):]
    return path


def finding_id(kind: str, path: str) -> str:
    return hashlib.sha1(f"{kind}|{path}".encode()).hexdigest()[:12]


@dataclass
class Action:
    # trash_path / trash_children / delete_path / simctl_delete / simctl_testing_delete_all
    # brew_cleanup / sqlite_vacuum / uv_cache_clean / pod_repo_remove / kill_process / empty_trash / none
    type: str = "none"
    args: dict[str, Any] = field(default_factory=dict)
    permanent: bool = False  # true when the action can't go through Trash
    label: str = ""          # human verb shown on the button, e.g. "Delete simulator"


@dataclass
class Finding:
    kind: str
    path: str
    bytes: int
    tier: str
    category: str
    title: str
    reason: str
    action: Action = field(default_factory=Action)
    requires_quit: list[str] = field(default_factory=list)  # apps that must not be running
    blocked_by: list[str] = field(default_factory=list)     # of those, which are running now
    mtime: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    children: list[dict[str, Any]] = field(default_factory=list)  # optional sub-breakdown

    @property
    def id(self) -> str:
        return finding_id(self.kind, self.path)

    @property
    def selectable(self) -> bool:
        return self.tier in (SAFE, CARE) and self.action.type != "none" and not self.blocked_by

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = self.id
        d["display"] = shorten(self.path)
        d["selectable"] = self.selectable
        return d


@dataclass
class DiskInfo:
    total: int
    used: int
    free: int

    def to_dict(self) -> dict[str, int]:
        return asdict(self)
