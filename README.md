# Transcript Report Generator

Cross-dev plugin (CS698B / FDE1) by team **rm -rf sleep** for the base project
**Video Transcription with Confidence Analytics** (team Technologia Gang).

For one processed recording it builds a downloadable report, **Markdown or PDF**, with:
- speaker talk time and share (bar chart + table),
- word confidence breakdown, overall and per speaker (high / mid / low, the base app's own cut-offs),
- utterances to review: speaker turns with low average confidence or several very-low-confidence words,
  least certain first, with timestamps and the uncertain words marked.

It reads the base app **only through its documented REST API** (`/api/v1/media`, `/api/v1/transcriptions/{id}`,
`/api/v1/analytics/{id}`); no change to their code is needed. Flagging is rule-based: no model is trained, and the
report makes no accuracy claims beyond the base app's confidence scores.

## Run

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Linux/macOS: .venv/bin/pip

# against the real base app (its backend on port 8000)
BASE_API=http://127.0.0.1:8000/api/v1 .venv/Scripts/python -m uvicorn treport.app:app --port 8300
```
Open http://127.0.0.1:8300 : list of recordings → preview → **Download PDF / Markdown**. The flagging thresholds
can be changed on the preview page.

Command line:
```bash
.venv/Scripts/python -m treport.cli --list
.venv/Scripts/python -m treport.cli <recording_id> --format pdf --out reports/
```

## API (our side)

| Method | Path | |
|---|---|---|
| GET | `/report/{recording_id}?format=md\|pdf\|html\|json` | the report; optional `turn_avg_below`, `low_word_below`, `min_low_words` |
| GET | `/recordings` | the base app's recordings, with report links |
| GET | `/health` | plugin status and whether the base app is reachable |

OpenAPI docs at `/docs`. Errors: 404 unknown recording, 409 still being transcribed, 502 base app unreachable.

## Developing without the base app's speech pipeline

`mock_base/` is a **mock** of the base API serving invented conversations in their exact schema
(`engine/schemas.py`). It is for development and tests only, not their app and not real data:

```bash
.venv/Scripts/python -m uvicorn mock_base.app:app --port 8200
BASE_API=http://127.0.0.1:8200/api/v1 .venv/Scripts/python -m uvicorn treport.app:app --port 8300
.venv/Scripts/python -m pytest -q
```

## Layout

- `treport/client.py` - base API client (handles "still processing", not found, unreachable)
- `treport/stats.py` - talk time, tiers, flagging rules
- `treport/charts.py` - matplotlib charts (Okabe-Ito colours + hatching + printed values)
- `treport/render.py` - Markdown, HTML and PDF (fpdf2, DejaVu font from matplotlib for full Unicode)
- `treport/app.py` - FastAPI service; `treport/cli.py` - command line
