import pytest
from fastapi.testclient import TestClient

from mock_base.app import app as mock_app
from treport import charts, render, stats
from treport.app import app as plugin_app
from treport.client import BaseAPIError, BaseClient, NotReady


def w(word, s, e, spk, c):
    return {"word": word, "start": s, "end": e, "speaker": spk, "confidence": c, "raw_confidence": c}


def tiny():
    a = [w("hello", 0, 1, "A", 0.9), w("there", 1, 2, "A", 0.8)]
    b = [w("uh", 3, 3.5, "B", 0.1), w("Nankari", 3.5, 4, "B", 0.2), w("road", 4, 5, "B", 0.7)]
    c = [w("yes", 6, 9, "A", 0.95)]
    segs = [{"turn_id": "t0", "speaker": "A", "start": 0, "end": 2, "text": "hello there", "words": a},
            {"turn_id": "t1", "speaker": "B", "start": 3, "end": 5, "text": "uh Nankari road", "words": b},
            {"turn_id": "t2", "speaker": "A", "start": 6, "end": 9, "text": "yes", "words": c}]
    return {"recording_id": "r1", "filename": "x.wav", "duration": 10, "speakers": ["A", "B"], "segments": segs,
            "words": a + b + c, "calibration": {"is_calibrated": True}}


def test_talk_time_and_shares():
    r = stats.build(tiny())
    a, b = r["speakers"]
    assert (a["speaker"], a["talk_s"], a["turns"], a["words"]) == ("A", 5, 2, 3)
    assert (b["speaker"], b["talk_s"]) == ("B", 2)
    assert a["share"] == pytest.approx(5 / 7)
    assert r["talk_s"] == 7 and r["n_words"] == 6


def test_tiers_match_base_cutoffs():
    t = stats.tiers([0.1, 0.29, 0.3, 0.59, 0.6, 0.99])
    assert [t[k]["count"] for k in ("low", "mid", "high")] == [2, 2, 2]


def test_flagging_rules():
    r = stats.build(tiny())
    assert [f["turn_id"] for f in r["flagged"]] == ["t1"]
    f = r["flagged"][0]
    assert f["low_words"] == ["uh", "Nankari"] and len(f["why"]) == 2
    # stricter rule flags nothing; looser average threshold also flags turn t0 (mean 0.85)
    assert stats.build(tiny(), rules=stats.Rules(turn_avg_below=0.2, min_low_words=5))["flagged"] == []
    assert len(stats.build(tiny(), rules=stats.Rules(turn_avg_below=0.9))["flagged"]) == 2


def test_turn_without_words_uses_top_level_words():
    t = tiny()
    for s in t["segments"]:
        s["words"] = []
    assert [f["turn_id"] for f in stats.build(t)["flagged"]] == ["t1"]


def test_renders():
    r = stats.build(tiny())
    ch = charts.all_charts(r)
    assert set(ch) == {"talk_time", "confidence"} and all(v[:4] == b"\x89PNG" for v in ch.values())
    md = render.to_markdown(r, ch)
    assert "**Nankari**" in md and "data:image/png;base64," in md and "| A |" in md
    pdf = render.to_pdf(r, ch)
    assert pdf[:4] == b"%PDF" and len(pdf) > 5000
    assert "<mark>Nankari</mark>" in render.to_html_fragment(r, ch)


def test_pipes_and_markers_in_text_are_safe():
    t = tiny()
    t["segments"][1]["text"] = "uh | Nankari ** road -- __"
    r = stats.build(t)
    assert "\\|" in render.to_markdown(r, {})
    assert render.to_pdf(r, {})[:4] == b"%PDF"


@pytest.fixture
def base():
    return BaseClient("/api/v1", http=TestClient(mock_app))


def test_client_against_mock(base):
    recs = base.recordings()
    assert {r["recording_id"] for r in recs} >= {"rec_standup", "rec_board"}
    t = base.transcript("rec_interview")
    assert t["segments"] and t["words"] and t["speakers"] == ["SPEAKER_00", "SPEAKER_01"]
    with pytest.raises(NotReady):
        base.transcript("rec_board")
    with pytest.raises(BaseAPIError) as e:
        base.transcript("nope")
    assert e.value.status == 404


def test_plugin_endpoints(base):
    plugin_app.state.client = base
    c = TestClient(plugin_app)
    assert c.get("/health").json()["base_reachable"] is True
    r = c.get("/report/rec_standup?format=pdf")
    assert r.status_code == 200 and r.content[:4] == b"%PDF" and "attachment" in r.headers["content-disposition"]
    r = c.get("/report/rec_standup?format=md")
    assert r.status_code == 200 and r.text.startswith("# Transcript report: weekly_standup.mp4")
    j = c.get("/report/rec_interview?format=json").json()
    assert j["n_speakers"] == 2 and j["flagged"]
    assert c.get("/report/rec_board").status_code == 409
    assert c.get("/report/nope").status_code == 404
    assert "weekly_standup.mp4" in c.get("/").text
    assert c.get("/view/rec_lecture").status_code == 200
    assert c.get("/view/rec_board").status_code == 409


def test_base_down():
    plugin_app.state.client = BaseClient("http://127.0.0.1:9")
    c = TestClient(plugin_app)
    assert c.get("/report/x").status_code == 502
    assert "Cannot reach the base app" in c.get("/").text
    plugin_app.state.client = None
