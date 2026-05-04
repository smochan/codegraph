#!/usr/bin/env python3
"""Capture the README hero video by driving the codegraph dashboard via Playwright.

Run a fresh codegraph serve on cross-stack-demo, then walk the architecture
lifecycle modal for ``GET /api/users/{user_id}`` so the recording shows the
arg-flow chip light up as the request travels through the layers.

Usage:
    codegraph build  # in examples/cross-stack-demo, if not already
    codegraph serve --port 8765 --no-open  # leave running
    python3 scripts/capture_hero_video.py

Outputs:
    docs/videos/hero.webm   (raw Playwright recording)
    docs/images/hero.mp4    (h264, README-friendly)
    docs/images/hero.gif    (fallback for renderers that strip <video>)
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
VIDEO_DIR = REPO / "docs" / "videos"
IMAGES_DIR = REPO / "docs" / "images"
DASHBOARD_URL = "http://127.0.0.1:8765/?v=hero#architecture"
VIEWPORT = {"width": 1280, "height": 720}


def record() -> Path:
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport=VIEWPORT,
            record_video_dir=str(VIDEO_DIR),
            record_video_size=VIEWPORT,
        )
        page = ctx.new_page()
        page.goto(DASHBOARD_URL, wait_until="networkidle")
        page.wait_for_timeout(800)

        # Open the lifecycle modal for GET /api/users/{user_id}.
        page.evaluate(
            """
            () => {
              const b = [...document.querySelectorAll('button.arch-handler')]
                .find(b => /\\/api\\/users\\/\\{user_id\\}/.test(b.textContent || ''));
              if (b) b.click();
            }
            """
        )
        page.wait_for_timeout(900)

        # Pause autoplay so we control the cadence.
        page.evaluate(
            """
            () => {
              const pause = [...document.querySelectorAll('button')]
                .find(b => /pause/i.test(b.textContent || ''));
              if (pause) pause.click();
            }
            """
        )
        page.wait_for_timeout(200)

        # Walk forward through the pipeline beats.
        for _ in range(12):
            page.evaluate(
                """
                () => {
                  const next = [...document.querySelectorAll('button')]
                    .find(b => (b.getAttribute('title') || '') === 'Next step (→)');
                  if (next) next.click();
                }
                """
            )
            page.wait_for_timeout(280)

        # Switch to Diagram mode so the arg-flow topology shows.
        page.evaluate(
            """
            () => {
              const dia = [...document.querySelectorAll('button')]
                .find(b => (b.textContent || '').trim() === 'Diagram');
              if (dia) dia.click();
            }
            """
        )
        page.wait_for_timeout(1500)

        ctx.close()
        browser.close()

    # Playwright writes a single .webm; grab the newest one.
    webms = sorted(VIDEO_DIR.glob("*.webm"), key=lambda p: p.stat().st_mtime)
    if not webms:
        raise SystemExit("no .webm produced")
    final = VIDEO_DIR / "hero.webm"
    if webms[-1] != final:
        shutil.move(str(webms[-1]), str(final))
    # cleanup any older recordings
    for old in webms[:-1]:
        old.unlink(missing_ok=True)
    return final


def transcode(webm: Path) -> None:
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    mp4 = IMAGES_DIR / "hero.mp4"
    gif = IMAGES_DIR / "hero.gif"
    palette = VIDEO_DIR / "palette.png"

    # H264 mp4 — README <video> fallback works on most viewers.
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(webm),
            "-vf", "scale=1280:-2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-preset", "veryslow", "-crf", "26",
            str(mp4),
        ],
        check=True,
    )

    # Palette-based gif keeps colour banding out at a sane file size.
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(webm),
            "-vf", "fps=15,scale=1000:-1:flags=lanczos,palettegen",
            str(palette),
        ],
        check=True,
    )
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(webm), "-i", str(palette),
            "-filter_complex", "fps=15,scale=1000:-1:flags=lanczos[x];[x][1:v]paletteuse",
            str(gif),
        ],
        check=True,
    )
    palette.unlink(missing_ok=True)
    print(f"wrote {mp4} ({mp4.stat().st_size // 1024} KB)")
    print(f"wrote {gif} ({gif.stat().st_size // 1024} KB)")


def main() -> int:
    print("recording...")
    webm = record()
    print(f"recorded {webm} ({webm.stat().st_size // 1024} KB)")
    print("transcoding...")
    transcode(webm)
    return 0


if __name__ == "__main__":
    sys.exit(main())
