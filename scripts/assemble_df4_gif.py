#!/usr/bin/env python3
"""Assemble the 9 DF4 trace frames into an animated GIF.

Source frames are produced by driving the cross-stack-demo dashboard via
Playwright (see docs/RECORDING_GUIDE.md). This script stitches them into
one looping GIF small enough to play inline on GitHub and LinkedIn.

Inputs:  /Users/smochan/Documents/projects/df4_step_{01,03,05,07,09,11,13,15,17}.png
Output:  docs/images/df4_trace.gif
"""
from pathlib import Path

from PIL import Image

FRAMES = [Path(f"/Users/smochan/Documents/projects/df4_step_{i:02d}.png")
          for i in (1, 3, 5, 7, 9, 11, 13, 15, 17)]
OUT = Path(__file__).resolve().parent.parent / "docs" / "images" / "df4_trace.gif"
TARGET_WIDTH = 1280   # mobile-readable, keeps file size sane
PER_FRAME_MS = 750    # 750ms per step = ~7s total loop
HOLD_LAST_MS = 1800   # linger on the final step before looping


def main() -> None:
    images = []
    for p in FRAMES:
        img = Image.open(p).convert("RGBA")
        if img.width > TARGET_WIDTH:
            ratio = TARGET_WIDTH / img.width
            img = img.resize(
                (TARGET_WIDTH, int(img.height * ratio)),
                Image.LANCZOS,
            )
        images.append(img.convert("P", palette=Image.ADAPTIVE, colors=128))

    durations = [PER_FRAME_MS] * (len(images) - 1) + [HOLD_LAST_MS]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        OUT,
        save_all=True,
        append_images=images[1:],
        duration=durations,
        loop=0,
        optimize=True,
        disposal=2,
    )
    size_kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT}  ({size_kb:.0f} KB, {len(images)} frames @ {TARGET_WIDTH}px wide)")


if __name__ == "__main__":
    main()
