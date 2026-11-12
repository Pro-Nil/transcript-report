"""Report numbers from one TranscriptResult (the base app's canonical transcript JSON).

Everything here is plain arithmetic and fixed rules: no model is trained. Confidence tiers use the same
cut-offs as the base app's /analytics endpoint (low < 0.30 <= mid < 0.60 <= high).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

LOW_CUT, HIGH_CUT = 0.30, 0.60


@dataclass
class Rules:
    """When is an utterance flagged for review? Both rules are configurable."""
    turn_avg_below: float = 0.60     # the turn's mean word confidence is below this
    low_word_below: float = 0.30     # a word counts as "very low" below this
    min_low_words: int = 2           # ...and the turn has at least this many very-low words

    def as_dict(self):
        return asdict(self)


def tier(c: float) -> str:
    return "low" if c < LOW_CUT else ("mid" if c < HIGH_CUT else "high")


def tiers(confs: list[float]) -> dict:
    n = len(confs)
    out = {}
    for t in ("high", "mid", "low"):
        k = sum(1 for c in confs if tier(c) == t)
        out[t] = {"count": k, "ratio": (k / n) if n else 0.0}
    return out


def _turn_words(turn: dict, all_words: list[dict]) -> list[dict]:
    """Words of a turn. Turns usually carry their words; if not, take the speaker's words inside the turn."""
    if turn.get("words"):
        return turn["words"]
    s, e, spk = turn["start"], turn["end"], turn.get("speaker")
    return [w for w in all_words if w.get("speaker") == spk and s <= (w["start"] + w["end"]) / 2 <= e]


def _turn_conf(turn: dict, words: list[dict]) -> float | None:
    if words:
        return sum(w["confidence"] for w in words) / len(words)
    return turn.get("avg_confidence")


def speakers(t: dict) -> list[dict]:
    """Per speaker: talk time and share, turns, words, mean confidence and tiers. Sorted by talk time."""
    turns, words = t.get("segments", []), t.get("words", [])
    names = list(dict.fromkeys(list(t.get("speakers", [])) + [x["speaker"] for x in turns]))
    rows = []
    for name in names:
        ts = [x for x in turns if x["speaker"] == name]
        ws = [w for w in words if w.get("speaker") == name]
        if not ws:  # transcript without top-level words: fall back to the turns' words
            ws = [w for x in ts for w in x.get("words", [])]
        confs = [w["confidence"] for w in ws]
        rows.append({
            "speaker": name,
            "talk_s": sum(max(0.0, x["end"] - x["start"]) for x in ts),
            "turns": len(ts),
            "words": len(ws),
            "mean_conf": (sum(confs) / len(confs)) if confs else None,
            "tiers": tiers(confs),
        })
    total = sum(r["talk_s"] for r in rows)
    for r in rows:
        r["share"] = r["talk_s"] / total if total else 0.0
    return sorted(rows, key=lambda r: -r["talk_s"])


def flagged(t: dict, rules: Rules) -> list[dict]:
    """Utterances (turns) a person should re-check, least certain first."""
    out = []
    all_words = t.get("words", [])
    for turn in t.get("segments", []):
        ws = _turn_words(turn, all_words)
        avg = _turn_conf(turn, ws)
        low = [w for w in ws if w["confidence"] < rules.low_word_below]
        why = []
        if avg is not None and avg < rules.turn_avg_below:
            why.append(f"average confidence {avg:.0%} (below {rules.turn_avg_below:.0%})")
        if len(low) >= rules.min_low_words:
            why.append(f"{len(low)} very-low-confidence words")
        if why:
            out.append({
                "turn_id": turn.get("turn_id"), "speaker": turn["speaker"], "start": turn["start"], "end": turn["end"],
                "text": turn.get("text") or " ".join(w["word"] for w in ws), "avg_conf": avg,
                "low_words": [w["word"] for w in low], "why": why,
            })
    return sorted(out, key=lambda x: (x["avg_conf"] if x["avg_conf"] is not None else 1.0, x["start"]))


def build(t: dict, analytics: dict | None = None, rules: Rules | None = None) -> dict:
    """All numbers for one report."""
    rules = rules or Rules()
    words = t.get("words", []) or [w for x in t.get("segments", []) for w in x.get("words", [])]
    confs = [w["confidence"] for w in words]
    spk = speakers(t)
    talk = sum(r["talk_s"] for r in spk)
    cal = t.get("calibration") or {}
    return {
        "recording_id": t.get("recording_id"),
        "filename": t.get("filename", ""),
        "duration_s": float(t.get("duration") or 0.0),
        "method": t.get("method", ""),
        "calibrated": bool(cal.get("is_calibrated", False)) and all(w.get("is_calibrated", True) for w in words),
        "n_speakers": len(spk),
        "n_turns": len(t.get("segments", [])),
        "n_words": len(words),
        "talk_s": talk,
        "mean_conf": (sum(confs) / len(confs)) if confs else None,
        "tiers": tiers(confs),
        "speakers": spk,
        "flagged": flagged(t, rules),
        "rules": rules.as_dict(),
        # cross-check against the base app's own analytics, when it answers
        "base_mean_conf": (analytics or {}).get("mean_confidence"),
    }


def fmt_time(s: float) -> str:
    s = int(round(s))
    h, m, sec = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def fmt_dur(s: float) -> str:
    s = int(round(s))
    m, sec = divmod(s, 60)
    return f"{m}m {sec:02d}s" if m else f"{sec}s"
