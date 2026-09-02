"""ElevenLabs speech: the three things their v4 note says it must get right.

    "Prepared right after QA rather than at the end, paid once per text, never
     silently absent."
"""
import json

import pytest

from conftest import make_job, scene_plan, write_config, write_replies
from fjor_studio.app import open_studio
from fjor_studio.gen.base import GenError
from fjor_studio.gen.elevenlabs import ElevenLabsBackend


class FakeHTTP:
    """Answers like the real endpoint: audio bytes, not JSON."""

    def __init__(self, status=200, ctype="audio/mpeg", body=b"ID3fake-mp3-bytes"):
        self.status, self.ctype, self.body, self.calls = status, ctype, body, []

    def __call__(self, method, url, headers, json=None, data=None, **kw):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "json": json})
        return self.status, {"content-type": self.ctype}, self.body


def backend(monkeypatch, http):
    from fjor_studio.gen import elevenlabs as mod
    monkeypatch.setattr(mod.http_mod, "request", http)
    return ElevenLabsBackend({"api_key": "k"})


# -- the backend -------------------------------------------------------------

def test_the_audio_is_written_as_the_mp3_it_actually_is(tmp_path, monkeypatch):
    http = FakeHTTP()
    out = tmp_path / "vo.wav"                     # asked for .wav
    r = backend(monkeypatch, http).submit(
        "speech", "eleven_multilingual_v2", "Just five minutes a day.",
        {"out_path": str(out), "voice": "voice-abc"})
    written = tmp_path / "vo.mp3"                 # ... written as .mp3
    assert written.exists() and written.read_bytes() == b"ID3fake-mp3-bytes"
    assert r.files == [str(written)]
    sent = http.calls[0]
    assert sent["headers"]["xi-api-key"] == "k"
    assert "voice-abc" in sent["url"]
    assert sent["json"]["text"] == "Just five minutes a day."


def test_a_refusal_is_never_written_to_disk_as_if_it_were_audio(tmp_path, monkeypatch):
    """The API answers JSON on refusal and audio on success. Without checking
    the content type, an error message becomes a track nobody can play."""
    http = FakeHTTP(status=401, ctype="application/json",
                    body=b'{"detail":"invalid api key"}')
    with pytest.raises(GenError, match="invalid api key"):
        backend(monkeypatch, http).submit(
            "speech", "m", "hello", {"out_path": str(tmp_path / "vo.mp3"),
                                     "voice": "v"})
    assert not list(tmp_path.iterdir())


def test_an_empty_track_is_refused(tmp_path, monkeypatch):
    http = FakeHTTP(body=b"")
    with pytest.raises(GenError, match="the failure that ships"):
        backend(monkeypatch, http).submit(
            "speech", "m", "hello", {"out_path": str(tmp_path / "vo.mp3"),
                                     "voice": "v"})


def test_a_missing_voice_id_says_it_is_not_a_name(tmp_path, monkeypatch):
    """Gemini takes a name, this takes an id, and the difference is a whole
    wasted run if nobody says so."""
    with pytest.raises(GenError, match="A NAME is not an id"):
        backend(monkeypatch, FakeHTTP()).submit(
            "speech", "m", "hello", {"out_path": str(tmp_path / "vo.mp3")})


def test_speaking_nothing_is_refused_rather_than_bought(tmp_path, monkeypatch):
    with pytest.raises(GenError, match="asked to speak nothing"):
        backend(monkeypatch, FakeHTTP()).submit(
            "speech", "m", "   ", {"out_path": str(tmp_path / "vo.mp3"),
                                   "voice": "v"})


# -- and the two rules that live in the stage --------------------------------

def _voiced(home, reference, lines):
    plan = json.dumps({"scenes": [
        {"idx": i, "image_prompt": f"plate {i}", "video_prompt": f"motion {i}",
         "duration_s": 5, "voice": "vo", "line": line}
        for i, line in enumerate(lines)]})
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]},
                                 "voice": {"source": "elevenlabs",
                                           "voice_id": "voice-abc"}})
    write_replies(home, analysis="analysed", text=plan,
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    return cfg, store, engine, make_job(store, reference, scenes=len(lines),
                                        config=cfg)


def test_the_same_line_is_spoken_once_and_used_twice(home, reference):
    """Their note names this among three things the voice must get right. Two
    shots with the same words are one recording."""
    line = "Just five minutes a day."
    cfg, store, engine, job = _voiced(home, reference, [line, "Different.", line])
    job = engine.approve(engine.approve(engine.run(job)))
    calls = [c for c in engine.providers.backend_for("speech").calls
             if c["op"] == "submit" and c["kind"] == "speech"]
    assert len(calls) == 2, "the repeated line was bought twice"
    tracks = [s["vo_track"] for s in job.scenes]
    assert tracks[0] == tracks[2] and tracks[1] != tracks[0]
    assert any(e["type"] == "vo_reused" for e in job.events)


def test_an_empty_track_stops_the_job_rather_than_shipping_a_silent_ad(home,
                                                                      reference):
    """The clip is silent BY DESIGN, so a missing voice looks like nothing at
    all downstream. That is the failure that ships."""
    cfg, store, engine, job = _voiced(home, reference, ["A line."])
    speech = engine.providers.backend_for("speech")
    real = speech._write

    def empty(result):
        path = real(result)
        open(path, "wb").close()          # a zero-byte track
        return path

    speech._write = empty
    job = engine.run(job)
    while job.state.startswith("GATE_"):
        job = engine.run(engine.approve(job))
    assert job.state == "failed"
    assert "no voice" in job.error and "voice: on_camera" in job.error
