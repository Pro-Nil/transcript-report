"""The plugin's own web service.

    GET /                       recordings in the base app, with report links
    GET /view/{recording_id}    report preview page with download buttons
    GET /report/{recording_id}  ?format=md|pdf|html|json  (documented in /docs)
    GET /health

Run:  uvicorn treport.app:app --port 8300      (BASE_API=http://127.0.0.1:8000/api/v1 by default)
"""
from __future__ import annotations

import html
import os
from datetime import datetime
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from . import __version__, charts, render, stats
from .client import DEFAULT_BASE, BaseAPIError, BaseClient


def _when(value) -> str:
    """The base app's ISO timestamp (UTC) as local time, e.g. '14 Nov 2026, 14:29'; raw text if it does not parse."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return (dt.astimezone() if dt.tzinfo else dt).strftime("%d %b %Y, %H:%M").lstrip("0")
    except ValueError:
        return str(value)[:16]

app = FastAPI(
    title="Transcript Report Generator",
    version=__version__,
    description="Cross-dev plugin for *Video Transcription with Confidence Analytics*. Builds a downloadable "
                "report (Markdown or PDF) for one processed recording: speaker talk time, confidence breakdown and "
                "low-confidence utterances to review. Reads the base app only through its REST API.",
)


def client(request: Request) -> BaseClient:
    c = getattr(request.app.state, "client", None)
    if c is None:
        c = request.app.state.client = BaseClient(os.environ.get("BASE_API", DEFAULT_BASE))
    return c


def _rules(turn_avg_below, low_word_below, min_low_words) -> stats.Rules:
    return stats.Rules(turn_avg_below=turn_avg_below, low_word_below=low_word_below, min_low_words=min_low_words)


def _build(c: BaseClient, recording_id: str, rules: stats.Rules) -> dict:
    try:
        t = c.transcript(recording_id)
    except BaseAPIError as e:
        raise HTTPException(e.status, str(e))
    return stats.build(t, c.analytics(recording_id), rules)


def _safe_name(s: str) -> str:
    base = os.path.splitext(s or "recording")[0]
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in base)[:60] or "recording"


@app.get("/health", tags=["service"])
def health(request: Request):
    c = client(request)
    try:
        base = c.health()
        ok = True
    except BaseAPIError as e:
        base, ok = str(e), False
    return {"plugin": "ok", "version": __version__, "base_api": c.base_url, "base_reachable": ok, "base": base}


@app.get("/recordings", tags=["reports"], summary="Recordings in the base app, with report links")
def recordings(request: Request):
    try:
        recs = client(request).recordings()
    except BaseAPIError as e:
        raise HTTPException(e.status, str(e))
    return [{**r, "report_md": f"/report/{r['recording_id']}?format=md",
             "report_pdf": f"/report/{r['recording_id']}?format=pdf"} for r in recs]


@app.get("/report/{recording_id}", tags=["reports"], summary="Report for one recording",
         responses={200: {"content": {"text/markdown": {}, "application/pdf": {}, "text/html": {}}},
                    404: {"description": "Recording or transcript not found in the base app"},
                    409: {"description": "The base app is still transcribing this recording"},
                    502: {"description": "The base app could not be reached"}})
def report(request: Request, recording_id: str,
           format: Literal["md", "pdf", "html", "json"] = "md",
           turn_avg_below: float = Query(0.60, ge=0, le=1, description="Flag a turn whose mean word confidence is below this"),
           low_word_below: float = Query(0.30, ge=0, le=1, description="A word is 'very low' below this confidence"),
           min_low_words: int = Query(2, ge=1, le=50, description="...or a turn with at least this many very-low words")):
    r = _build(client(request), recording_id, _rules(turn_avg_below, low_word_below, min_low_words))
    if format == "json":
        return JSONResponse(r)
    ch = charts.all_charts(r)
    name = f"report_{_safe_name(r['filename'])}"
    if format == "pdf":
        return Response(render.to_pdf(r, ch), media_type="application/pdf",
                        headers={"Content-Disposition": f'attachment; filename="{name}.pdf"'})
    if format == "html":
        return HTMLResponse(_page(f"Report: {r['filename']}", render.to_html_fragment(r, ch)))
    return Response(render.to_markdown(r, ch), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.md"'})


@app.get("/view/{recording_id}", response_class=HTMLResponse, include_in_schema=False)
def view(request: Request, recording_id: str, turn_avg_below: float = Query(0.60, ge=0, le=1),
         low_word_below: float = Query(0.30, ge=0, le=1), min_low_words: int = Query(2, ge=1, le=50)):
    e = html.escape
    try:
        r = _build(client(request), recording_id, _rules(turn_avg_below, low_word_below, min_low_words))
    except HTTPException as ex:
        return HTMLResponse(_page("Report not available", f"<p><a href='/'>&larr; All recordings</a></p>"
                                  f"<h1>Report not available</h1><p class='err'>{e(str(ex.detail))}</p>"), ex.status_code)
    q = f"turn_avg_below={turn_avg_below}&low_word_below={low_word_below}&min_low_words={min_low_words}"
    rid = e(recording_id)
    tools = f"""
<p><a href="/">&larr; All recordings</a></p>
<div class="bar">
  <a class="btn" href="/report/{rid}?format=pdf&{q}">Download PDF</a>
  <a class="btn ghost" href="/report/{rid}?format=md&{q}">Download Markdown</a>
</div>
<form class="rules" method="get" aria-label="Flagging rules">
  <label>Flag turns with average below <input name="turn_avg_below" type="number" step="0.01" min="0" max="1" value="{turn_avg_below}"></label>
  <label>or with at least <input name="min_low_words" type="number" min="1" max="50" value="{min_low_words}"> words below
  <input name="low_word_below" type="number" step="0.01" min="0" max="1" value="{low_word_below}"></label>
  <button class="btn ghost" type="submit">Update</button>
</form>"""
    return _page(f"Report: {r['filename']}", tools + render.to_html_fragment(r, charts.all_charts(r)))


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def index(request: Request):
    e = html.escape
    c = client(request)
    try:
        recs = c.recordings()
    except BaseAPIError as ex:
        return _page("Transcript Report Generator",
                     f"<h1>Transcript Report Generator</h1><p class='err'>{e(str(ex))}</p>"
                     f"<p>Set <code>BASE_API</code> to the base app's API (now <code>{e(c.base_url)}</code>).</p>")
    rows = "".join(
        f"<tr><td><a href='/view/{e(x['recording_id'])}'>{e(x.get('filename', x['recording_id']))}</a></td>"
        f"<td>{stats.fmt_dur(float(x.get('duration') or 0))}</td><td class='nw'>{e(_when(x.get('created_at')))}</td>"
        f"<td class='nw'><a href='/report/{e(x['recording_id'])}?format=pdf'>PDF</a> · "
        f"<a href='/report/{e(x['recording_id'])}?format=md'>Markdown</a></td></tr>" for x in recs)
    body = f"""
<h1>Transcript Report Generator</h1>
<p class="sub">Reports for recordings processed by <em>Video Transcription with Confidence Analytics</em>
(base API: <code>{e(c.base_url)}</code>). Open one to preview, or download it.</p>
{"<div class='scroll'><table><thead><tr><th>Recording</th><th>Duration</th><th>Added</th><th>Download</th></tr></thead><tbody>" + rows + "</tbody></table></div>" if recs else "<p>No recordings in the base app yet.</p>"}
<p class="sub">API for developers: <a href="/docs">/docs</a></p>"""
    return _page("Transcript Report Generator", body)


CSS = """
:root{--bg:#fff;--fg:#1d1f23;--mut:#5b6170;--line:#e3e6ea;--card:#f6f8fa;--acc:#0b5cad;--accfg:#fff;--mark:#ffe08a;--markfg:#1d1f23;--err:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#15171b;--fg:#e8eaed;--mut:#a3a9b5;--line:#30343b;--card:#1d2026;--acc:#6db3f2;--accfg:#0b1220;--mark:#ffd24d;--markfg:#111;--err:#ff8a80}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:960px;margin:0 auto;padding:24px 16px 64px}h1{font-size:1.6rem;margin:.3em 0 .4em;line-height:1.25}h2{font-size:1.2rem;margin:1.8em 0 .6em}
a{color:var(--acc)}.sub,.note{color:var(--mut)}.note{font-size:.9rem;margin:.3em 0}.err{color:var(--err);font-weight:600}
table{border-collapse:collapse;width:100%;font-size:.92rem}th,td{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}
thead th{background:var(--card)}.summary{max-width:620px}.summary th{width:45%;font-weight:600;color:var(--mut)}.nw{white-space:nowrap}
.scroll{overflow-x:auto}img{max-width:100%;height:auto;background:#fff;border-radius:6px;margin:4px 0 10px}
mark{background:var(--mark);color:var(--markfg);font-weight:700;padding:0 2px;border-radius:3px}
.bar{display:flex;gap:10px;flex-wrap:wrap;margin:8px 0 14px}.btn{display:inline-block;background:var(--acc);color:var(--accfg);padding:8px 14px;border-radius:8px;text-decoration:none;font-weight:600;border:1px solid var(--acc);cursor:pointer;font:inherit}
.btn.ghost{background:transparent;color:var(--acc)}.rules{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:8px;font-size:.9rem}
.rules input{width:4.5em;padding:3px 5px;background:var(--bg);color:var(--fg);border:1px solid var(--line);border-radius:6px}
code{background:var(--card);padding:1px 4px;border-radius:4px}
"""


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
            f"content='width=device-width,initial-scale=1'><title>{html.escape(title)}</title><style>{CSS}</style>"
            f"</head><body><main>{body}</main></body></html>")
