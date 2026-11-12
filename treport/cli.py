"""Command line:  python -m treport.cli --list
                 python -m treport.cli REC_ID [--format pdf|md] [--out reports/]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import charts, render, stats
from .client import DEFAULT_BASE, BaseAPIError, BaseClient


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="treport", description="Build a transcript report from the base app's API.")
    ap.add_argument("recording_id", nargs="?")
    ap.add_argument("--list", action="store_true", help="list recordings in the base app")
    ap.add_argument("--format", choices=["md", "pdf", "both"], default="both")
    ap.add_argument("--out", default="reports", help="output folder (default: reports/)")
    ap.add_argument("--base", default=DEFAULT_BASE, help=f"base app API (default {DEFAULT_BASE})")
    ap.add_argument("--turn-avg-below", type=float, default=0.60)
    ap.add_argument("--low-word-below", type=float, default=0.30)
    ap.add_argument("--min-low-words", type=int, default=2)
    a = ap.parse_args(argv)
    c = BaseClient(a.base)
    try:
        if a.list or not a.recording_id:
            for r in c.recordings():
                print(f"{r['recording_id']}\t{r.get('filename', '')}\t{stats.fmt_dur(float(r.get('duration') or 0))}")
            return 0
        rep = stats.build(c.transcript(a.recording_id), c.analytics(a.recording_id),
                          stats.Rules(a.turn_avg_below, a.low_word_below, a.min_low_words))
    except BaseAPIError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = "report_" + "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in Path(rep["filename"] or a.recording_id).stem)
    ch = charts.all_charts(rep)
    if a.format in ("md", "both"):  # Markdown with the charts saved next to it
        links = {}
        for name, png in ch.items():
            (out / f"{stem}_{name}.png").write_bytes(png)
            links[name] = f"{stem}_{name}.png"
        (out / f"{stem}.md").write_text(render.to_markdown(rep, ch, links), encoding="utf-8")
        print(out / f"{stem}.md")
    if a.format in ("pdf", "both"):
        (out / f"{stem}.pdf").write_bytes(render.to_pdf(rep, ch))
        print(out / f"{stem}.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
