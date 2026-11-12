"""Turn report numbers + charts into Markdown, HTML or PDF."""
from __future__ import annotations

import base64
import html
import io
import re
from datetime import datetime
from pathlib import Path

import matplotlib
from fpdf import FPDF
from fpdf.fonts import FontFace

from .stats import fmt_dur, fmt_time

TITLE = "Transcript report"


def _pct(x):
    return "-" if x is None else f"{x:.0%}"


def _summary_rows(r: dict) -> list[tuple[str, str]]:
    cov = r["talk_s"] / r["duration_s"] if r["duration_s"] else None
    return [
        ("Recording", f"{r['filename']} ({r['recording_id']})"),
        ("Duration", fmt_dur(r["duration_s"])),
        ("Speakers / turns / words", f"{r['n_speakers']} / {r['n_turns']} / {r['n_words']}"),
        ("Speaking time", f"{fmt_dur(r['talk_s'])}" + (f" ({cov:.0%} of the recording)" if cov is not None else "")),
        ("Mean word confidence", _pct(r["mean_conf"])),
        ("Utterances flagged for review", str(len(r["flagged"]))),
    ]


def _notes(r: dict) -> list[str]:
    notes = []
    if not r["calibrated"]:
        notes.append("The base app does not mark these confidence scores as calibrated, so read them as relative "
                     "(higher = more certain), not as exact probabilities.")
    notes.append("Confidence values come from the base app; this report only summarises them and makes no accuracy "
                 "claims of its own.")
    return notes


def _rules_text(r: dict) -> str:
    ru = r["rules"]
    return (f"An utterance (speaker turn) is flagged when its average word confidence is below "
            f"{ru['turn_avg_below']:.0%}, or when it has at least {ru['min_low_words']} words below "
            f"{ru['low_word_below']:.0%}. Flagged utterances are listed least certain first. Confidence tiers: "
            f"high 60% and up, mid 30-60%, low below 30% (the base app's own cut-offs).")


def _mark_low(text: str, low_words: list[str], open_: str, close: str, esc=lambda s: s) -> str:
    """Wrap each very-low-confidence word of the utterance in open_/close (first occurrence of each)."""
    out = esc(text)
    for w in dict.fromkeys(low_words):
        ew = esc(w.strip())
        if not ew:
            continue
        out = re.sub(rf"(?<![\w*]){re.escape(ew)}(?![\w*])", lambda m: f"{open_}{m.group(0)}{close}", out, count=1)
    return out


# ---------- Markdown ----------

def _md_cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def to_markdown(r: dict, charts: dict[str, bytes], image_links: dict[str, str] | None = None) -> str:
    """image_links: name -> relative path; if absent, charts are embedded as data URIs (one self-contained file)."""
    def img(name, alt):
        if name not in charts:
            return ""
        src = (image_links or {}).get(name) or "data:image/png;base64," + base64.b64encode(charts[name]).decode()
        return f"![{alt}]({src})\n"

    L = [f"# {TITLE}: {r['filename']}", "",
         f"Generated {datetime.now():%d %b %Y, %H:%M} from the base app's REST API.", "",
         "| | |", "|---|---|"]
    L += [f"| {_md_cell(k)} | {_md_cell(v)} |" for k, v in _summary_rows(r)]
    L += [""] + [f"> {n}" for n in _notes(r)] + ["", "## Talk time", "",
          img("talk_time", "Bar chart of each speaker's share of speaking time"),
          "| Speaker | Talk time | Share | Turns | Words | Mean confidence | Low-confidence words |",
          "|---|---|---|---|---|---|---|"]
    for s in r["speakers"]:
        L.append(f"| {_md_cell(s['speaker'])} | {fmt_dur(s['talk_s'])} | {s['share']:.0%} | {s['turns']} | "
                 f"{s['words']} | {_pct(s['mean_conf'])} | {s['tiers']['low']['count']} |")
    L += ["", "## Confidence breakdown", "", img("confidence", "Stacked bars of high, mid and low confidence words"),
          "| | High | Mid | Low |", "|---|---|---|---|"]
    for name, t in [("All speakers", r["tiers"])] + [(s["speaker"], s["tiers"]) for s in r["speakers"]]:
        L.append(f"| {_md_cell(name)} | " + " | ".join(f"{t[k]['ratio']:.0%} ({t[k]['count']})" for k in ("high", "mid", "low")) + " |")
    L += ["", f"## Utterances to review ({len(r['flagged'])})", ""]
    if r["flagged"]:
        L += ["Very-low-confidence words are in **bold**.", "",
              "| # | Time | Speaker | Avg conf. | Utterance | Why flagged |", "|---|---|---|---|---|---|"]
        for i, f in enumerate(r["flagged"], 1):
            text = _mark_low(_md_cell(f["text"]), f["low_words"], "**", "**")
            L.append(f"| {i} | {fmt_time(f['start'])}-{fmt_time(f['end'])} | {_md_cell(f['speaker'])} | "
                     f"{_pct(f['avg_conf'])} | {text} | {_md_cell('; '.join(f['why']))} |")
    else:
        L.append("No utterance meets the flagging rules.")
    L += ["", "## How this report was made", "", _rules_text(r), ""]
    return "\n".join(L)


# ---------- HTML (preview page) ----------

def to_html_fragment(r: dict, charts: dict[str, bytes]) -> str:
    e = html.escape

    def img(name, alt):
        if name not in charts:
            return ""
        return f'<img src="data:image/png;base64,{base64.b64encode(charts[name]).decode()}" alt="{e(alt)}">'

    rows = "".join(f"<tr><th scope='row'>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in _summary_rows(r))
    notes = "".join(f"<p class='note'>{e(n)}</p>" for n in _notes(r))
    spk = "".join(
        f"<tr><td>{e(s['speaker'])}</td><td>{fmt_dur(s['talk_s'])}</td><td>{s['share']:.0%}</td><td>{s['turns']}</td>"
        f"<td>{s['words']}</td><td>{_pct(s['mean_conf'])}</td><td>{s['tiers']['low']['count']}</td></tr>"
        for s in r["speakers"])
    tiers = "".join(
        f"<tr><td>{e(n)}</td>" + "".join(f"<td>{t[k]['ratio']:.0%} ({t[k]['count']})</td>" for k in ("high", "mid", "low")) + "</tr>"
        for n, t in [("All speakers", r["tiers"])] + [(s["speaker"], s["tiers"]) for s in r["speakers"]])
    if r["flagged"]:
        fl = "".join(
            f"<tr><td>{i}</td><td class='nw'>{fmt_time(f['start'])}-{fmt_time(f['end'])}</td><td>{e(f['speaker'])}</td>"
            f"<td>{_pct(f['avg_conf'])}</td><td>{_mark_low(f['text'], f['low_words'], '<mark>', '</mark>', e)}</td>"
            f"<td>{e('; '.join(f['why']))}</td></tr>" for i, f in enumerate(r["flagged"], 1))
        flagged = ("<p>Very-low-confidence words are <mark>highlighted</mark>.</p><div class='scroll'><table>"
                   "<thead><tr><th>#</th><th>Time</th><th>Speaker</th><th>Avg conf.</th><th>Utterance</th>"
                   f"<th>Why flagged</th></tr></thead><tbody>{fl}</tbody></table></div>")
    else:
        flagged = "<p>No utterance meets the flagging rules.</p>"
    return f"""
<h1>{TITLE}: {e(r['filename'])}</h1>
<table class="summary"><tbody>{rows}</tbody></table>
{notes}
<h2>Talk time</h2>
{img('talk_time', 'Bar chart of each speaker share of speaking time')}
<div class="scroll"><table><thead><tr><th>Speaker</th><th>Talk time</th><th>Share</th><th>Turns</th><th>Words</th>
<th>Mean confidence</th><th>Low-confidence words</th></tr></thead><tbody>{spk}</tbody></table></div>
<h2>Confidence breakdown</h2>
{img('confidence', 'Stacked bars of high, mid and low confidence words per speaker')}
<div class="scroll"><table><thead><tr><th></th><th>High</th><th>Mid</th><th>Low</th></tr></thead><tbody>{tiers}</tbody></table></div>
<h2>Utterances to review ({len(r['flagged'])})</h2>
{flagged}
<h2>How this report was made</h2>
<p>{e(_rules_text(r))}</p>"""


# ---------- PDF ----------

_FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"   # DejaVu ships with matplotlib: full Unicode


class _PDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("DejaVu", size=8)
        self.set_text_color(110)
        self.cell(0, 6, f"{TITLE} - page {self.page_no()}/{{nb}}", align="C")


def to_pdf(r: dict, charts: dict[str, bytes]) -> bytes:
    pdf = _PDF(format="A4")
    pdf.add_font("DejaVu", "", str(_FONT_DIR / "DejaVuSans.ttf"))
    pdf.add_font("DejaVu", "B", str(_FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdf.set_auto_page_break(True, margin=16)
    pdf.set_margins(16, 16, 16)
    pdf.add_page()
    W = pdf.epw

    def h1(t):
        pdf.set_font("DejaVu", "B", 17)
        pdf.set_text_color(20)
        pdf.multi_cell(W, 8, t, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    def h2(t):
        pdf.ln(3)
        pdf.set_font("DejaVu", "B", 13)
        pdf.set_text_color(20)
        pdf.cell(W, 8, t, new_x="LMARGIN", new_y="NEXT")

    def para(t, size=9.5, color=50):
        pdf.set_font("DejaVu", size=size)
        pdf.set_text_color(color)
        pdf.multi_cell(W, 5, t, new_x="LMARGIN", new_y="NEXT")

    def keep_room(mm):
        """Start a new page if fewer than `mm` millimetres are left (keeps a heading with its chart)."""
        if pdf.get_y() + mm > pdf.page_break_trigger:
            pdf.add_page()

    def chart_h(name, width=W * 0.92):
        if name not in charts:
            return 0
        from PIL import Image
        with Image.open(io.BytesIO(charts[name])) as im:
            return width * im.height / im.width

    def image(name, width=W * 0.92):
        if name in charts:
            pdf.image(io.BytesIO(charts[name]), w=width, x=pdf.l_margin)
            pdf.ln(1)

    head = FontFace(emphasis="BOLD", fill_color=(235, 240, 246))

    def table(rows, widths, header=True, markdown=False, size=8.5):
        pdf.set_font("DejaVu", size=size)
        pdf.set_text_color(30)
        with pdf.table(col_widths=widths, headings_style=head, first_row_as_headings=header, markdown=markdown,
                       line_height=4.6, padding=1.2, text_align="LEFT", width=W) as t:
            for row in rows:
                rr = t.row()
                for c in row:
                    rr.cell(str(c))

    h1(f"{TITLE}: {r['filename']}")
    para(f"Generated {datetime.now():%d %b %Y, %H:%M} from the base app's REST API.", 8.5, 110)
    pdf.ln(2)
    table(_summary_rows(r), (34, 66), header=False, size=9)
    pdf.ln(1)
    for n in _notes(r):
        para(n, 8.5, 90)

    keep_room(14 + chart_h("talk_time"))
    h2("Talk time")
    image("talk_time")
    table([("Speaker", "Talk time", "Share", "Turns", "Words", "Mean conf.", "Low words")] +
          [(s["speaker"], fmt_dur(s["talk_s"]), f"{s['share']:.0%}", s["turns"], s["words"], _pct(s["mean_conf"]),
            s["tiers"]["low"]["count"]) for s in r["speakers"]], (24, 14, 10, 9, 10, 14, 12))

    keep_room(14 + chart_h("confidence"))
    h2("Confidence breakdown")
    image("confidence")
    table([("", "High", "Mid", "Low")] +
          [(n, *(f"{t[k]['ratio']:.0%} ({t[k]['count']})" for k in ("high", "mid", "low")))
           for n, t in [("All speakers", r["tiers"])] + [(s["speaker"], s["tiers"]) for s in r["speakers"]]],
          (34, 22, 22, 22))

    keep_room(40)
    h2(f"Utterances to review ({len(r['flagged'])})")
    if r["flagged"]:
        para("Very-low-confidence words are in bold.", 8.5, 90)
        pdf.ln(1)
        def md(s):  # keep transcript text from being read as fpdf2 markdown markers (**, __, --)
            return s.replace("**", "* *").replace("__", "_ _").replace("--", "- -")
        table([("#", "Time", "Speaker", "Avg", "Utterance", "Why flagged")] +
              [(i, f"{fmt_time(f['start'])}-{fmt_time(f['end'])}", f["speaker"], _pct(f["avg_conf"]),
                _mark_low(md(f["text"]), f["low_words"], "**", "**"), "; ".join(f["why"]))
               for i, f in enumerate(r["flagged"], 1)], (5, 14, 20, 8, 55, 30), markdown=True, size=8)
    else:
        para("No utterance meets the flagging rules.")

    h2("How this report was made")
    para(_rules_text(r), 9)
    return bytes(pdf.output())
