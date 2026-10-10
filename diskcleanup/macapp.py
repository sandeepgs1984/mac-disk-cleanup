"""Builds a double-clickable 'Disk Cleanup.app' that starts the server and opens the browser.

The bundle is a thin launcher: a shell script plus Info.plist plus an icon generated here
(no image libraries needed). It lives in /Applications but runs the code from this repo,
so `git pull` updates the app too.
"""
from __future__ import annotations

import math
import os
import plistlib
import shutil
import stat
import struct
import subprocess
import tempfile
import zlib

from .model import HOME

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_NAME = "Disk Cleanup"
BUNDLE_ID = "com.sandeepgs.mac-disk-cleanup.app"

LAUNCHER = f'''#!/bin/bash
# Launcher for {APP_NAME}.app — starts the dashboard server (or reuses a running one) and opens it.
REPO="{ROOT}"
LOG="$HOME/.disk-cleanup/app.log"
mkdir -p "$HOME/.disk-cleanup"

if [ ! -x "$REPO/bin/cleanup" ]; then
  osascript -e 'display alert "{APP_NAME}" message "The project folder has moved. Run  bin/cleanup install-app  from its new location." as critical'
  exit 1
fi

# bin/cleanup picks the newest Python 3.9+ (and shows its own alert if there is none).
# Detached, so Finder gets its launcher back immediately. serve() opens the browser itself and,
# if a dashboard is already running on the port, just reopens it instead of starting another.
nohup "$REPO/bin/cleanup" serve --idle-exit 15 >>"$LOG" 2>&1 &
disown
'''


# ---------- icon ----------------------------------------------------------------
def _png(width: int, height: int, pixels: bytes) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + pixels[y * width * 4:(y + 1) * width * 4] for y in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def render_icon(size: int) -> bytes:
    """A rounded blue→teal tile with a white gauge arc — drawn pixel by pixel."""
    top, bottom = (42, 120, 214), (27, 175, 122)
    radius = size * 0.225
    cx = cy = size / 2
    arc_r, arc_w = size * 0.30, size * 0.085
    px = bytearray()
    for y in range(size):
        for x in range(size):
            # rounded-rect mask with 1px anti-aliasing
            dx = max(abs(x + .5 - cx) - (size / 2 - radius), 0)
            dy = max(abs(y + .5 - cy) - (size / 2 - radius), 0)
            d = math.hypot(dx, dy) - radius
            alpha = max(0.0, min(1.0, 0.5 - d))
            if alpha <= 0:
                px += b"\x00\x00\x00\x00"
                continue
            r, g, b = _lerp(top, bottom, (x + y) / (2 * size))
            # gauge arc: 220° sweep opening at the bottom, plus a bright "free" tip
            ang = math.degrees(math.atan2(y + .5 - cy, x + .5 - cx))
            dist = abs(math.hypot(x + .5 - cx, y + .5 - cy) - arc_r)
            on_arc = dist < arc_w / 2 and not (60 < ang < 120)
            if on_arc:
                edge = max(0.0, min(1.0, (arc_w / 2 - dist) * 1.5))
                white = (255, 255, 255) if not (-30 < ang < 60) else (200, 255, 215)
                r, g, b = _lerp((r, g, b), white, 0.92 * edge)
            px += bytes((r, g, b, int(255 * alpha)))
    return _png(size, size, bytes(px))


def build_icns(dest: str) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        iconset = os.path.join(tmp, "icon.iconset")
        os.makedirs(iconset)
        for base in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                name = f"icon_{base}x{base}" + ("@2x" if scale == 2 else "") + ".png"
                with open(os.path.join(iconset, name), "wb") as f:
                    f.write(render_icon(base * scale))
        r = subprocess.run(["iconutil", "-c", "icns", iconset, "-o", dest], capture_output=True, text=True)
        return r.returncode == 0


# ---------- bundle --------------------------------------------------------------
def install(target_dir: str | None = None) -> str:
    target_dir = target_dir or ("/Applications" if os.access("/Applications", os.W_OK) else os.path.join(HOME, "Applications"))
    os.makedirs(target_dir, exist_ok=True)
    app = os.path.join(target_dir, f"{APP_NAME}.app")
    if os.path.exists(app):
        shutil.rmtree(app)
    macos = os.path.join(app, "Contents/MacOS")
    resources = os.path.join(app, "Contents/Resources")
    os.makedirs(macos)
    os.makedirs(resources)

    launcher = os.path.join(macos, "launcher")
    with open(launcher, "w") as f:
        f.write(LAUNCHER)
    os.chmod(launcher, os.stat(launcher).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    has_icon = build_icns(os.path.join(resources, "AppIcon.icns"))
    info = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "launcher",
        "LSMinimumSystemVersion": "12.0",
        "LSUIElement": True,          # no Dock icon — it just opens the browser
        "NSHighResolutionCapable": True,
    }
    if has_icon:
        info["CFBundleIconFile"] = "AppIcon"
    with open(os.path.join(app, "Contents/Info.plist"), "wb") as f:
        plistlib.dump(info, f)
    # Ad-hoc signature keeps Gatekeeper calm for a locally built bundle.
    subprocess.run(["codesign", "--force", "--sign", "-", app], capture_output=True)
    # Nudge LaunchServices so Finder picks up the icon straight away.
    subprocess.run(["touch", app])
    return app
