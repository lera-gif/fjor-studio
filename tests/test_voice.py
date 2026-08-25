"""Shots whose speaker is not on screen.

Measured on BPW026: an on-camera studio line generated fine, while the same
B-roll shot with a voiceover was refused three times for copyright and passed
immediately with generate_audio off. Asking the video model for a disembodied
voice makes it invent a soundtrack, and that is what gets rejected.
"""
import json
import math
import struct
import subprocess

import pytest

from conftest import make_job, write_config, write_replies
from fjor_studio.app import open_studio
from fjor_studio.assemble import SIZES, build_final
from fjor_studio.stages.steps import _parse_scene_plan


def plan(voices):
    return json.dumps({"scenes": [
        {"idx": i, "voice": v, "line": f"line {i}", "characters": [],
         "image_prompt": f"p{i}", "video_prompt": f"m{i}", "duration_s": 5}
        for i, v in enumerate(voices)]})


# -- the plan ----------------------------------------------------------------

def test_voice_modes_are_parsed():
    scenes, notes = _parse_scene_plan(plan(["on_camera", "vo", "silent"]), 3,
                                      (4.0, 15.0))
    assert [s["voice"] for s in scenes] == ["on_camera", "vo", "silent"]
    assert notes == []


def test_an_unknown_voice_mode_falls_back_and_says_so():
    scenes, notes = _parse_scene_plan(plan(["whispered"]), 1, (4.0, 15.0))
    assert scenes[0]["voice"] == "on_camera"
    assert any("not one of on_camera/vo/silent" in n for n in notes)


# -- generation --------------------------------------------------------------

@pytest.fixture
def mixed(home, reference):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]},
                                 "characters": {"enabled": False},
                                 "delivery": {"formats": ["9:16"]}})
    write_replies(home, analysis="a", text=plan(["on_camera", "vo", "silent"]),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    return cfg, store, engine, make_job(store, reference, scenes=3, config=cfg)


def test_only_an_on_camera_shot_asks_the_model_for_audio(mixed):
    """This is the whole fix: the other two are generated silent."""
    _cfg, _store, engine, job = mixed
    job = engine.approve(engine.run(job))
    backend = engine.providers.backend_for("video")
    calls = sorted([c for c in backend.calls
                    if c["op"] == "submit" and c["kind"] == "video"],
                   key=lambda c: c["prompt"])
    assert [c["params"]["generate_audio"] for c in calls] == [True, False, False]


def test_a_vo_shot_gets_its_line_spoken_separately(mixed):
    _cfg, store, engine, job = mixed
    job = engine.approve(engine.run(job))
    assert job.state == "GATE_DRAFT"
    tracks = {s["idx"]: s["vo_track"] for s in job.scenes}
    assert tracks[1] == "audio/scene_01_vo.wav"
    assert (store.job_dir(job.id) / tracks[1]).exists()
    # on-camera speech is already in the clip; silence needs nothing
    assert tracks[0] is None and tracks[2] is None
    spoken = [c for c in engine.providers.backend_for("speech").calls
              if c["op"] == "submit" and c["kind"] == "speech"]
    assert len(spoken) == 1 and spoken[0]["prompt"] == "line 1"


def test_the_voiceover_is_not_re_spoken_on_a_re_run(mixed):
    _cfg, store, engine, job = mixed
    job = engine.approve(engine.run(job))
    backend = engine.providers.backend_for("speech")
    before = len([c for c in backend.calls if c["op"] == "submit"])
    from fjor_studio.stages import steps
    steps.voiceovers(engine._ctx(store.load(job.id)))
    assert len([c for c in backend.calls if c["op"] == "submit"]) == before


def test_the_cut_carries_the_voiceover_track(mixed):
    _cfg, store, engine, job = mixed
    job = engine.approve(engine.run(job))
    manifest = json.loads(
        (store.job_dir(job.id) / "draft" / "edit_manifest.json").read_text())
    vos = [s.get("voiceover") for s in manifest["segments"] if s["role"] == "clip"]
    assert vos == [None, "scene_01_vo.wav", None]


# -- the mix ------------------------------------------------------------------

def _rms(path, start, dur):
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(dur), "-i", str(path),
         "-f", "s16le", "-ac", "1", "-ar", "16000", "-"],
        capture_output=True, check=True).stdout
    n = len(raw) // 2
    if not n:
        return 0.0
    vals = struct.unpack(f"<{n}h", raw[:n * 2])
    return math.sqrt(sum(v * v for v in vals) / n)


def test_a_short_voiceover_does_not_shorten_the_shot(tmp_path):
    """amix against a silence source made the shortest input win, so a 2.5s
    voiceover cut a 4s shot down to 2.5s."""
    clip, vo = tmp_path / "c.mp4", tmp_path / "vo.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=navy:size=180x320:rate=30:duration=4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
                   check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=2.5",
                    "-c:a", "pcm_s16le", str(vo)], check=True, capture_output=True)
    r = build_final([clip], tmp_path / "out.mp4", SIZES["9:16"],
                    clip_audio=[str(vo)], crf=34, preset="ultrafast")
    assert r["duration_s"] == pytest.approx(4.0, abs=0.3)
    assert _rms(tmp_path / "out.mp4", 0, 2) > 500      # the voice is there
    assert _rms(tmp_path / "out.mp4", 3, 1) < 50       # and then silence
