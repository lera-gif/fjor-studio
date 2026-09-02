"""The reference kind: what the producer declares at intake, and what it changes.

AW024 (2026-09-01) was a stylised 3D cartoon reference. The analysis said so and
every image prompt opened with "3D cartoon animation style" -- and the creative
came back photoreal and uncanny. The words were right and the words were not
enough. These tests are mostly about the difference between saying a thing and
attaching a picture of it.
"""
import json
import subprocess

import pytest

from conftest import make_job, scene_plan, write_config, write_replies
from fjor_studio import refkind
from fjor_studio.app import open_studio
from fjor_studio.gen.base import GenError


def setup(home, reference, kind=None, scenes=1):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed", text=scene_plan(scenes),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    extra = {"ref_kind": kind} if kind else {}
    return cfg, store, engine, make_job(store, reference, scenes=scenes,
                                        config=cfg, **extra)


def real_reference(path, seconds=6):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"testsrc=size=320x568:rate=25:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
                   check=True, capture_output=True)
    return path


# -- the declaration ---------------------------------------------------------

def test_only_their_two_kinds_are_accepted():
    assert sorted(refkind.KINDS) == ["replica", "ugc"]
    assert refkind.normalise(None) == "ugc"
    assert refkind.normalise("REPLICA") == "replica"
    with pytest.raises(GenError, match="not one of"):
        refkind.normalise("cartoon")


def test_the_kind_is_a_job_decision_not_a_studio_setting(home, reference):
    """Two references handed to the same studio on the same day can want
    different treatment, and the producer knows which at intake."""
    _cfg, store, engine, job = setup(home, reference, kind="replica")
    assert refkind.is_replica(store.load(job.id)) is True
    _cfg2, store2, _e2, plain = setup(home, reference)
    assert refkind.is_replica(store2.load(plain.id)) is False


# -- what it changes ---------------------------------------------------------

def test_a_replica_asks_the_analysis_about_the_picture_itself(home, reference):
    _cfg, _store, engine, job = setup(home, reference, kind="replica")
    engine.run(job)
    briefs = [c["prompt"] for c
              in engine.providers.backend_for("analysis").calls
              if c["op"] == "submit" and c["kind"] == "analysis"]
    assert briefs and "MATERIAL AND FINISH" in briefs[0]
    # the distinction that failed on AW024
    assert "Pixar-like cartoon and a" in briefs[0] or "not just" in briefs[0]
    assert "WHAT IS NOT IN FRAME" in briefs[0]


def test_a_ugc_job_is_asked_none_of_that(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    engine.run(job)
    briefs = [c["prompt"] for c
              in engine.providers.backend_for("analysis").calls
              if c["op"] == "submit" and c["kind"] == "analysis"]
    assert briefs and "MATERIAL AND FINISH" not in briefs[0]


def test_stills_are_cut_from_the_reference_and_reach_every_plate(tmp_path, home):
    """The whole point. A look is pinned by a picture, the same way a face is."""
    ref = real_reference(tmp_path / "ref.mp4")
    _cfg, store, engine, job = setup(home, ref, kind="replica", scenes=2)
    job = engine.approve(engine.run(job))
    frames = store.load(job.id).meta["style_frames"]
    assert len(frames) == refkind.STYLE_FRAMES
    for rel in frames:
        assert (store.job_dir(job.id) / rel).is_file()
    plates = [c for c in engine.providers.backend_for("image").calls
              if c["op"] == "submit" and c["kind"] == "image"]
    assert plates
    for call in plates:
        assert sum(1 for m in call["medias"] if "style_" in m) == len(frames)
        assert "STYLE ANCHOR" in call["prompt"]
        assert "THE FRAMES WIN" in call["prompt"]


def test_a_ugc_job_cuts_no_frames_and_carries_no_style_anchor(tmp_path, home):
    ref = real_reference(tmp_path / "ref.mp4")
    _cfg, store, engine, job = setup(home, ref)
    job = engine.approve(engine.run(job))
    assert not store.load(job.id).meta.get("style_frames")
    plates = [c for c in engine.providers.backend_for("image").calls
              if c["op"] == "submit" and c["kind"] == "image"]
    assert plates and all("STYLE ANCHOR" not in c["prompt"] for c in plates)


def test_the_frames_are_spread_across_the_reference(tmp_path):
    """An ad's first second is often a title card or a hard cut, and a style
    anchor taken from one would teach the model the wrong thing."""
    ref = real_reference(tmp_path / "ref.mp4", seconds=8)
    frames = refkind.cut_style_frames(ref, tmp_path / "out", 8.0, count=3)
    assert len(frames) == 3
    sizes = {__import__("pathlib").Path(f).stat().st_size for f in frames}
    assert len(sizes) > 1, "identical frames: they were all cut from one moment"


def test_frames_are_cut_once_and_reused(tmp_path, home):
    ref = real_reference(tmp_path / "ref.mp4")
    _cfg, store, engine, job = setup(home, ref, kind="replica")
    job = engine.approve(engine.run(job))
    first = [(store.job_dir(job.id) / r).stat().st_mtime_ns
             for r in store.load(job.id).meta["style_frames"]]
    from fjor_studio.stages.steps import _style_frames
    _style_frames(engine._ctx(store.load(job.id)))
    again = [(store.job_dir(job.id) / r).stat().st_mtime_ns
             for r in store.load(job.id).meta["style_frames"]]
    assert first == again


# -- the rule that AW024 broke ------------------------------------------------

def test_every_job_is_told_the_reference_carries_the_body_type(home, reference):
    """Ported out of their niche templates, because a body type drifting slimmer
    is not specific to a vertical. AW024 lost its 'before' this way."""
    _cfg, _store, engine, job = setup(home, reference)
    engine.run(job)
    brief = [c["prompt"] for c in engine.providers.backend_for("text").calls
             if c["op"] == "submit" and c["kind"] == "text"][0]
    assert "BODY TYPE IS CARRIED BY THE REFERENCE" in brief
    assert "plus-size customer IS the audience" in brief
    assert "drifts SILENTLY" in brief
