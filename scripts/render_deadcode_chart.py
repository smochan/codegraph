#!/usr/bin/env python3
"""Render the codegraph self-graph dead-code journey chart.

Outputs: docs/images/deadcode_journey.png
Usage:   python scripts/render_deadcode_chart.py
"""
from pathlib import Path

import matplotlib.pyplot as plt

DATA = [
    ("Session zero\n(2026-04-25)", 451, "#c44536"),
    ("Analyzer hardened\n(2026-04-27)", 15, "#e2a72e"),
    ("Pragma exemption — PR #21\n(2026-04-28)", 0, "#2a9d8f"),
]

OUT = Path(__file__).resolve().parent.parent / "docs" / "images" / "deadcode_journey.png"


def main() -> None:
    labels = [row[0] for row in DATA]
    counts = [row[1] for row in DATA]
    colors = [row[2] for row in DATA]

    fig, ax = plt.subplots(figsize=(10, 4.2), dpi=160)
    bars = ax.barh(labels, counts, color=colors, edgecolor="#222", linewidth=0.6)

    ax.invert_yaxis()
    ax.set_xlabel("Dead-code findings on codegraph self-graph", fontsize=11)
    ax.set_title(
        "codegraph dead-code: 451 → 15 → 0",
        fontsize=14,
        fontweight="bold",
        pad=14,
    )
    ax.set_xlim(0, max(counts) * 1.15 + 5)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", linestyle=":", alpha=0.4)
    ax.tick_params(axis="y", labelsize=10)

    for bar, count in zip(bars, counts):
        width = bar.get_width()
        ax.text(
            width + max(counts) * 0.012,
            bar.get_y() + bar.get_height() / 2,
            str(count),
            va="center",
            ha="left",
            fontsize=11,
            fontweight="bold",
            color="#222",
        )

    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
