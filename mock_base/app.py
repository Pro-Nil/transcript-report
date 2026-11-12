"""MOCK of the base app's REST API, for developing and testing the plugin without their speech pipeline.

It serves invented conversations in the base app's exact schema (engine/schemas.py: TranscriptResult,
ConversationTurn, AlignedWord) on the same /api/v1 paths. It is NOT their app and NOT real data; for the demo,
point the plugin at their real backend instead (BASE_API=http://<host>:8000/api/v1).

    uvicorn mock_base.app:app --port 8200
"""
from __future__ import annotations

import random

from fastapi import FastAPI, HTTPException

app = FastAPI(title="MOCK base API (Video Transcription with Confidence Analytics)", version="mock")

# (speaker, text, noisy) - noisy turns get lower word confidence (crosstalk, background noise)
CONVERSATIONS = {
    "rec_standup": ("weekly_standup.mp4", True, [
        ("SPEAKER_00", "Okay let's start. Quick round of updates, then we look at the deadline for the report.", False),
        ("SPEAKER_01", "I finished the upload page yesterday and fixed the bug where long file names broke the table.", False),
        ("SPEAKER_00", "Nice. Did you push it to the main branch?", False),
        ("SPEAKER_01", "Yes, it's merged. Tests pass on my machine and on the lab system.", False),
        ("SPEAKER_02", "Sorry, my mic was off. I was working on the diarization config but the NeMo checkpoint keeps timing out.", True),
        ("SPEAKER_00", "Can you share the error log in the group after this call?", False),
        ("SPEAKER_02", "Sure, I think it's the cache folder, kasturba hostel wifi drops every few minutes.", True),
        ("SPEAKER_01", "You can use my download, I have the checkpoint on a pen drive.", False),
        ("SPEAKER_00", "Great. For Thursday we need the confidence charts and the export buttons working end to end.", False),
        ("SPEAKER_02", "I'll take the export buttons. SRT and VTT are mostly done, JSON needs the speaker field.", True),
        ("SPEAKER_01", "And I'll write the test for the reliability diagram.", False),
        ("SPEAKER_00", "Perfect. Let's meet again on Wednesday night, same time.", False),
    ]),
    "rec_interview": ("customer_interview.wav", True, [
        ("SPEAKER_00", "Thanks for joining. Could you tell us how your team takes notes in meetings today?", False),
        ("SPEAKER_01", "Mostly someone types in a shared doc, but half the time nobody does it and we forget decisions.", True),
        ("SPEAKER_00", "What happens when a decision is forgotten?", False),
        ("SPEAKER_01", "We repeat the same discussion next week. It wastes maybe thirty minutes every time.", True),
        ("SPEAKER_00", "Would automatic transcripts help, or do you worry about accuracy?", False),
        ("SPEAKER_01", "Accuracy matters. If the tool marks the parts it is unsure about, I can check only those.", True),
        ("SPEAKER_01", "Our accents are mixed, Hindi English Marathi, and most tools get the names completely wrong.", True),
        ("SPEAKER_00", "That's useful. Which names do they usually miss?", False),
        ("SPEAKER_01", "Names like Aarav, Ishita, Vikram, and places like Kalyanpur or Nankari.", True),
        ("SPEAKER_00", "Got it. Last question, would you share recordings with an external service?", False),
        ("SPEAKER_01", "Only if it runs on our own machine. Privacy is a big concern for us.", False),
    ]),
    "rec_lecture": ("guest_lecture_qa.mp3", False, [
        ("SPEAKER_00", "Today I will talk about calibration. A model is calibrated when its confidence matches how often it is right.", False),
        ("SPEAKER_00", "If a speech recognizer says ninety percent for a set of words, about ninety percent of them should be correct.", False),
        ("SPEAKER_00", "We measure this with the expected calibration error and with reliability diagrams.", False),
        ("SPEAKER_00", "Isotonic regression and temperature scaling are two common ways to fix a miscalibrated model.", False),
        ("SPEAKER_01", "Sir, does temperature scaling change which word the model predicts?", True),
        ("SPEAKER_00", "No, it only rescales the confidence. The ranking of the words stays the same.", False),
        ("SPEAKER_02", "What if the test audio is noisier than the training audio?", True),
        ("SPEAKER_00", "Then calibration usually breaks, and you should recalibrate on audio like the one you deploy on.", False),
        ("SPEAKER_03", "Is there a quick check we can do without labels?", True),
        ("SPEAKER_00", "Not a reliable one. You need some labelled audio, even a small amount helps.", False),
        ("SPEAKER_00", "Okay, that's all for today. Slides are on the course page.", False),
    ]),
}
PROCESSING = {"rec_board": "board_meeting.m4a"}   # shows how the plugin handles a recording still in the pipeline
CREATED = {"rec_standup": "2026-11-10T21:05:00", "rec_interview": "2026-11-11T16:40:00",
           "rec_lecture": "2026-11-12T10:15:00", "rec_board": "2026-11-12T18:02:00"}


def _transcript(rid: str) -> dict:
    filename, calibrated, turns = CONVERSATIONS[rid]
    rng = random.Random(rid)
    t, segs, words = 0.6, [], []
    for i, (spk, text, noisy) in enumerate(turns):
        t += rng.uniform(0.25, 0.9)
        start, tw = t, []
        for tok in text.split():
            dur = 0.12 + 0.045 * len(tok) + rng.uniform(0, 0.08)
            c = rng.betavariate(9, 1.6)
            if noisy and rng.random() < 0.38:
                c = rng.betavariate(1.6, 3.2)        # crosstalk / noise
            if tok[0].isupper() and i and rng.random() < 0.35:
                c *= rng.uniform(0.3, 0.7)          # names are hard
            c = round(min(0.99, max(0.02, c)), 3)
            raw = round(min(0.99, max(0.01, c + rng.uniform(-0.08, 0.08))), 3)
            w = {"word": tok, "start": round(t, 3), "end": round(t + dur, 3), "speaker": spk, "confidence": c,
                 "raw_confidence": raw, "is_calibrated": calibrated, "alignment_status": "aligned",
                 "alignment_score": round(min(1, c + 0.05), 3), "asr_confidence": raw, "features": None}
            tw.append(w)
            t += dur + rng.uniform(0.02, 0.12)
        segs.append({"turn_id": f"turn_{i:03d}", "speaker": spk, "start": round(start, 3), "end": round(t, 3),
                     "text": text, "words": tw,
                     "avg_confidence": round(sum(x["confidence"] for x in tw) / len(tw), 3)})
        words += tw
    confs = [w["confidence"] for w in words]
    return {
        "recording_id": rid, "filename": filename, "duration": round(t + 1.5, 2), "sample_rate": 16000,
        "channels": 1, "method": "Phase20-OracleMSDD-MidpointFusion",
        "calibration": {"method": "isotonic_regression", "version": "1.0.0", "is_calibrated": calibrated,
                        "brier_score": None, "ece": None},
        "speakers": sorted({s["speaker"] for s in segs}), "segments": segs, "words": words,
        "summary": {"mean_confidence": round(sum(confs) / len(confs), 3), "total_words": len(words)},
    }


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "mock": True}


@app.get("/api/v1/media")
def media():
    out = [{"recording_id": rid, "filename": v[0], "duration": _transcript(rid)["duration"], "size_bytes": 0,
            "sha256": "mock", "created_at": CREATED[rid]} for rid, v in CONVERSATIONS.items()]
    out += [{"recording_id": rid, "filename": f, "duration": 1834.0, "size_bytes": 0, "sha256": "mock",
             "created_at": CREATED[rid]} for rid, f in PROCESSING.items()]
    return sorted(out, key=lambda r: r["created_at"], reverse=True)


@app.get("/api/v1/transcriptions/{rid}")
def transcript(rid: str):
    if rid in PROCESSING:  # the real app raises HTTPException(202, ...) while a job runs
        raise HTTPException(202, "Processing in progress (stage: Speaker diarization, 64%).")
    if rid not in CONVERSATIONS:
        raise HTTPException(404, f"No transcript found for recording '{rid}'.")
    return _transcript(rid)


@app.get("/api/v1/analytics/{rid}")
def analytics(rid: str):
    if rid not in CONVERSATIONS:
        raise HTTPException(404, "Transcript not found for analytics.")
    t = _transcript(rid)
    c = [w["confidence"] for w in t["words"]]
    n = len(c)
    k = lambda f: sum(1 for x in c if f(x))  # noqa: E731
    return {"recording_id": rid, "filename": t["filename"], "total_words": n,
            "mean_confidence": round(sum(c) / n, 3),
            "tiers": {"low": {"count": k(lambda x: x < .3), "ratio": round(k(lambda x: x < .3) / n, 3)},
                      "mid": {"count": k(lambda x: .3 <= x < .6), "ratio": round(k(lambda x: .3 <= x < .6) / n, 3)},
                      "high": {"count": k(lambda x: x >= .6), "ratio": round(k(lambda x: x >= .6) / n, 3)}},
            "speakers_count": len(t["speakers"]), "duration": t["duration"]}
