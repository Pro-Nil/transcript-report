"""Report charts as PNG bytes. Okabe-Ito colours plus hatching and printed values, so nothing relies on colour."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .stats import fmt_dur  # noqa: E402

INK, GRID = "#222222", "#DDDDDD"
TIER_STYLE = {  # Okabe-Ito colours; hatch so tiers differ in greyscale too
    "high": {"color": "#0072B2", "hatch": "", "label": "High (60% and up)"},
    "mid": {"color": "#E69F00", "hatch": "///", "label": "Mid (30-60%)"},
    "low": {"color": "#D55E00", "hatch": "xxx", "label": "Low (below 30%)"},
}
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.edgecolor": GRID,
                     "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK, "hatch.color": "white",
                     "hatch.linewidth": 1.2})


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def talk_time(report: dict) -> bytes:
    rows = report["speakers"][::-1]  # largest on top
    fig, ax = plt.subplots(figsize=(7, 0.55 * len(rows) + 0.9))
    names = [r["speaker"] for r in rows]
    vals = [r["share"] * 100 for r in rows]
    ax.barh(names, vals, color="#0072B2", height=0.6)
    for y, r in enumerate(rows):
        ax.text(r["share"] * 100 + 1, y, f"{r['share']:.0%}  ({fmt_dur(r['talk_s'])}, {r['turns']} turns)",
                va="center", color=INK, fontsize=9)
    ax.set_xlim(0, 100 if not vals else min(100, max(vals) * 1.45 + 5))
    ax.set_xlabel("Share of speaking time (%)")
    ax.set_title("Talk time by speaker", loc="left", color=INK, fontsize=12, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)
    return _png(fig)


def confidence_tiers(report: dict) -> bytes:
    rows = [("All speakers", report["tiers"])] + [(r["speaker"], r["tiers"]) for r in report["speakers"]]
    rows = rows[::-1]
    fig, ax = plt.subplots(figsize=(7, 0.55 * len(rows) + 1.3))
    for y, (name, t) in enumerate(rows):
        left = 0.0
        for k in ("high", "mid", "low"):
            w = t[k]["ratio"] * 100
            st = TIER_STYLE[k]
            ax.barh(y, w, left=left, color=st["color"], hatch=st["hatch"], height=0.6, edgecolor="white",
                    linewidth=0.8, label=st["label"] if y == 0 else None)
            if w >= 7:
                ax.text(left + w / 2, y, f"{w:.0f}%", ha="center", va="center", color="white", fontsize=9,
                        fontweight="bold", bbox={"facecolor": "#00000055", "edgecolor": "none", "pad": 1})
            left += w
    ax.set_yticks(range(len(rows)), [n for n, _ in rows])
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of words (%)")
    ax.set_title("Word confidence by speaker", loc="left", color=INK, fontsize=12, fontweight="bold")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.32 if len(rows) < 4 else -0.18), ncol=3, frameon=False,
              fontsize=9)
    return _png(fig)


def all_charts(report: dict) -> dict[str, bytes]:
    if not report["speakers"]:
        return {}
    return {"talk_time": talk_time(report), "confidence": confidence_tiers(report)}
