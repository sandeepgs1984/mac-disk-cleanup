from __future__ import annotations

import os

from . import ScanContext, detector
from ..model import Action, Finding, CARE, SAFE, CAT_CACHE, CAT_PKG, HOME
from ..sysinfo import du_bytes, du_children, mtime, which

MB = 1024 ** 2
CACHES = os.path.join(HOME, "Library/Caches")

# bundle-id prefix -> (friendly title, reason). Anything else gets a generic cache entry.
KNOWN = {
    "Google": ("Chrome cache", "Chrome's page cache, separate from your bookmarks and history."),
    "org.swift.swiftpm": ("Swift Package Manager cache", "Downloaded package sources; fetched again on the next build."),
    "com.openai.codex": ("Codex app cache", "App cache; rebuilt as you use the app."),
    "com.openai.chat": ("ChatGPT app cache", "App cache; rebuilt as you use the app."),
    "com.todesktop.230313mzl4w4u92.ShipIt": ("Cursor updater downloads", "Installer files left by Cursor's auto-updater."),
    "com.google.antigravity.ShipIt": ("Antigravity updater downloads", "Installer files left by the auto-updater."),
    "com.google.antigravity": ("Antigravity cache", "App cache; rebuilt as you use the app."),
    "pip": ("pip cache", "Downloaded Python wheels; fetched again on demand."),
    "GeoServices": ("Maps data cache", "Apple Maps tiles; re-downloaded when needed."),
    "CocoaPods": ("CocoaPods download cache", "Downloaded pod archives; re-fetched on the next `pod install`."),
    "Homebrew": ("Homebrew downloads", "Old bottle downloads. Cleared with Homebrew's own cleanup command."),
    "com.apple.dt.Xcode": ("Xcode cache", "Xcode's own cache; rebuilt on launch."),
    "ms-playwright": ("Playwright browsers", "Browser binaries; re-downloaded by `npx playwright install`."),
    "node-gyp": ("node-gyp headers", "Node headers; re-downloaded when a native module builds."),
    "yarn": ("Yarn cache", "Downloaded packages; fetched again on demand."),
    "typescript": ("TypeScript cache", "Compiler cache; rebuilt on demand."),
}


@detector("App caches")
def library_caches(ctx: ScanContext) -> list[Finding]:
    if not os.path.isdir(CACHES):
        return []
    out = []
    for path, size in du_children(CACHES, min_bytes=40 * MB):
        if ctx.excluded(path):
            continue
        name = os.path.basename(path)
        title, reason = KNOWN.get(name, (f"{name} cache", "Cache folder; apps rebuild their caches automatically."))
        if name == "Homebrew" and which("brew"):
            action = Action("brew_cleanup", label="Run brew cleanup")
        else:
            action = Action("trash_path", label="Move to Trash")
        out.append(Finding(kind="cache", path=path, bytes=size, tier=SAFE, category=CAT_CACHE,
                           title=title, reason=reason, action=action, mtime=mtime(path)))
    return out


PKG = [
    # path, title, reason, tier, action
    ("~/.npm/_cacache", "npm cache", "Downloaded packages; fetched again on demand.", SAFE, Action("trash_path", label="Move to Trash")),
    ("~/.npm/_npx", "npx package cache", "Packages run via npx; re-downloaded next use.", SAFE, Action("trash_path", label="Move to Trash")),
    ("~/.cache/uv", "uv cache", "Python packages cached by uv.", SAFE, Action("uv_cache_clean", label="Run uv cache clean")),
    ("~/.cache/pip", "pip cache", "Downloaded Python wheels.", SAFE, Action("trash_path", label="Move to Trash")),
    ("~/.cache/puppeteer", "Puppeteer browsers", "Chromium builds Puppeteer downloaded; re-fetched on install.", SAFE, Action("trash_path", label="Move to Trash")),
    ("~/.cache/ms-playwright", "Playwright browsers", "Re-downloaded by `npx playwright install`.", SAFE, Action("trash_path", label="Move to Trash")),
    ("~/.gradle/caches", "Gradle cache", "Downloaded Android/Java dependencies; re-fetched on the next build.", SAFE, Action("trash_path", label="Move to Trash")),
    ("~/.cocoapods/repos/cocoapods", "Legacy CocoaPods specs repo", "The old git clone of the CocoaPods specs. Modern CocoaPods uses the `trunk` CDN. Re-downloaded only if a Podfile still names the git source.", CARE, Action("pod_repo_remove", {"name": "cocoapods"}, permanent=True, label="Remove repo")),
    ("~/.cache/codex-runtimes", "Codex runtimes", "Runtimes downloaded by the Codex app; re-downloaded when needed.", CARE, Action("trash_path", label="Move to Trash")),
    ("~/.cache/lm-studio/models", "LM Studio models", "Local AI models you downloaded. Deleting means downloading them again.", CARE, Action("trash_path", label="Move to Trash")),
    ("~/Library/Caches/CocoaPods", "CocoaPods download cache", "Downloaded pod archives.", SAFE, Action("trash_path", label="Move to Trash")),
    ("~/Library/Android/sdk/system-images", "Android emulator images", "System images for Android emulators; re-downloadable from SDK Manager.", CARE, Action("trash_path", label="Move to Trash")),
]

QUIT = {"~/.cache/codex-runtimes": ["Codex"], "~/.cache/lm-studio/models": ["LM Studio"]}


@detector("Package & tool caches")
def package_caches(ctx: ScanContext) -> list[Finding]:
    out = []
    for rel, title, reason, tier, action in PKG:
        path = os.path.expanduser(rel)
        if ctx.excluded(path):
            continue
        size = du_bytes(path)
        if size < 40 * MB:
            continue
        if action.type == "uv_cache_clean" and not which("uv"):
            action = Action("trash_path", label="Move to Trash")
        req = QUIT.get(rel, [])
        out.append(Finding(kind="pkg", path=path, bytes=size, tier=tier, category=CAT_PKG,
                           title=title, reason=reason, action=action, requires_quit=req,
                           blocked_by=[a for a in req if a in ctx.running], mtime=mtime(path)))
    return out
