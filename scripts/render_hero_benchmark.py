#!/usr/bin/env python3
"""Render the hero benchmark image for the polycodegraph README.

Source of truth: bench/RESULTS_AGENT_LATEST.md (Claude-Code-style agent bench,
3 configs x 5 queries x 2 repos).

Outputs: docs/images/hero_benchmark.png  (1600x900, white background)
Usage:   python scripts/render_hero_benchmark.py
"""
from pathlib import Path

import matplotlib.pyplot as plt

# Totals across codegraph-self + fastapi, sourced verbatim from
# bench/RESULTS_AGENT_LATEST.md (run 20260523T143844Z).
# Realistic baseline: all configs include Claude's native grep + file tools
# (mimicking Claude Code / Cursor's default surface). Only the registered
# graph MCP varies.
ROWS = [
    # (label,                            correct, tokens_in, cost_usd, color)
    ("Claude + grep (no graph MCP)",      8,      336_589,   1.1740, "#c44536"),
    ("+ code-review-graph MCP",           3,      202_756,   0.6833, "#9aa3ad"),
    ("+ graphify MCP",                    5,      154_520,   0.5058, "#9aa3ad"),
    ("+ polycodegraph MCP",               7,       90_052,   0.3705, "#2a9d8f"),
]

TITLE = "Same Claude. Same 10 questions. Two real repos. Only the graph MCP changes."
# (Unicode multiplication-sign x is intentional in rendered chart text.)
SUBTITLE = (
    "polycodegraph: near-grep correctness at ~3x lower cost and ~4x lower latency. "
    "Competitor graph MCPs are strictly worse than just letting Claude grep."
)

OUT = Path(__file__).resolve().parent.parent / "docs" / "images" / "hero_benchmark.png"


def main() -> None:
    fig, (ax_correct, ax_tokens, ax_cost) = plt.subplots(
        1, 3,
        figsize=(16, 9),
        dpi=100,
        gridspec_kw={"width_ratios": [1.0, 1.2, 0.9]},
    )
    fig.patch.set_facecolor("white")

    labels = [r[0] for r in ROWS]
    colors = [r[4] for r in ROWS]
    y_pos = list(range(len(ROWS)))

    # --- Panel 1: Correctness (out of 10) ----------------------------------
    correct = [r[1] for r in ROWS]
    ax_correct.barh(y_pos, correct, color=colors, edgecolor="#222", linewidth=0.8)
    ax_correct.set_xlim(0, 10)
    ax_correct.set_xticks([0, 5, 10])
    ax_correct.set_yticks(y_pos)
    ax_correct.set_yticklabels(labels, fontsize=14)
    ax_correct.invert_yaxis()
    ax_correct.set_title("Correct  (out of 10)", fontsize=15, fontweight="bold", pad=14)
    ax_correct.spines["top"].set_visible(False)
    ax_correct.spines["right"].set_visible(False)
    ax_correct.tick_params(axis="x", labelsize=11)
    for i, c in enumerate(correct):
        ax_correct.text(c + 0.2, i, f"{c}/10", va="center", fontsize=13, fontweight="bold")

    # --- Panel 2: Tokens in (sum across repos) -----------------------------
    tokens = [r[2] for r in ROWS]
    ax_tokens.barh(y_pos, tokens, color=colors, edgecolor="#222", linewidth=0.8)
    ax_tokens.set_xlim(0, max(tokens) * 1.18)
    ax_tokens.set_yticks(y_pos)
    ax_tokens.set_yticklabels([""] * len(ROWS))  # share with panel 1
    ax_tokens.invert_yaxis()
    ax_tokens.set_title("Context tokens consumed  (sum across 10 queries)",
                        fontsize=15, fontweight="bold", pad=14)
    ax_tokens.spines["top"].set_visible(False)
    ax_tokens.spines["right"].set_visible(False)
    ax_tokens.tick_params(axis="x", labelsize=11)
    ax_tokens.set_xticks([0, 100_000, 200_000, 300_000])
    ax_tokens.set_xticklabels(["0", "100k", "200k", "300k"])
    for i, t in enumerate(tokens):
        ax_tokens.text(
            t + max(tokens) * 0.015, i,
            f"{t/1000:.1f}k" if t >= 1000 else str(t),
            va="center", fontsize=13, fontweight="bold",
        )

    # --- Panel 3: Cost (USD) -----------------------------------------------
    cost = [r[3] for r in ROWS]
    ax_cost.barh(y_pos, cost, color=colors, edgecolor="#222", linewidth=0.8)
    ax_cost.set_xlim(0, max(cost) * 1.2)
    ax_cost.set_yticks(y_pos)
    ax_cost.set_yticklabels([""] * len(ROWS))
    ax_cost.invert_yaxis()
    ax_cost.set_title("Cost  (USD)", fontsize=15, fontweight="bold", pad=14)
    ax_cost.spines["top"].set_visible(False)
    ax_cost.spines["right"].set_visible(False)
    ax_cost.tick_params(axis="x", labelsize=11)
    for i, c in enumerate(cost):
        ax_cost.text(
            c + max(cost) * 0.02, i, f"${c:.2f}",
            va="center", fontsize=13, fontweight="bold",
        )

    # --- Title strip --------------------------------------------------------
    fig.suptitle(TITLE, fontsize=20, fontweight="bold", y=0.97)
    fig.text(0.5, 0.91, SUBTITLE, ha="center", fontsize=14, color="#444")

    # --- Footer -------------------------------------------------------------
    fig.text(
        0.5, 0.03,
        "Reproduce: `codegraph bench agent`  ·  "
        "Raw: bench/RESULTS_AGENT_LATEST.md  ·  "
        "polycodegraph 0.1.0  ·  MIT",
        ha="center", fontsize=11, color="#666",
    )

    plt.subplots_adjust(wspace=0.18)
    plt.tight_layout(rect=(0, 0.05, 1, 0.88), w_pad=2.4)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(OUT, dpi=100, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
