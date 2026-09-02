"""A transformation on camera: the person changes in shot, with no cut.

The video model is handed two photographs of the same frame and morphs between
them. Everything here is about the word "same" -- anything that differs beyond
the change itself will be seen moving, and will read as a mistake.
"""
import json

import pytest

from conftest import make_job, write_config, write_replies
from fjor_studio.app import open_studio
from fjor_studio.gen.base import GenError


def plan_with_morph(scene=1, scenes=3):
    out = []
    for i in range(scenes):
        s = {"idx": i, "image_prompt": f"plate {i}", "video_prompt": f"motion {i}",
             "duration_s": 6, "characters": ["host"]}
        if i == scene:
            s["end_image_prompt"] = f"plate {i}, twenty-eight days later"
        out.append(s)
    return json.dumps({"cast": [{"id": "host", "description": "a woman, 40s"}],
                       "scenes": out})


@pytest.fixture
def morphing(home, reference):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed", text=plan_with_morph(),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    job = make_job(store, reference, scenes=3, config=cfg,
                   morph="she loses the swelling in her legs")
    return cfg, store, engine, job


# -- the writer --------------------------------------------------------------

def test_the_writer_is_asked_to_build_the_creative_around_the_change(morphing):
    _cfg, _store, engine, job = morphing
    job = engine.run(job)
    backend = engine.providers.backend_for("text")
    brief = [c for c in backend.calls if c.get("kind") == "text"][-1]["prompt"]
    assert "TRANSFORMATION ON CAMERA" in brief
    assert "she loses the swelling in her legs" in brief
    assert "THE SAME FRAME" in brief
    assert "One transformation per" in brief   # it wraps


def test_a_job_without_a_morph_is_never_told_about_one(home, reference):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed", text=plan_with_morph(scene=99),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    job = engine.run(make_job(store, reference, scenes=3, config=cfg))
    backend = engine.providers.backend_for("text")
    brief = [c for c in backend.calls if c.get("kind") == "text"][-1]["prompt"]
    assert "TRANSFORMATION" not in brief


def test_only_one_shot_may_transform(home, reference):
    """Two would each cost an extra plate, and neither would be the moment the
    script was built around."""
    from fjor_studio.stages.steps import _parse_scene_plan
    both = json.dumps({"scenes": [
        {"idx": 0, "image_prompt": "a", "video_prompt": "m", "duration_s": 6,
         "end_image_prompt": "a later"},
        {"idx": 1, "image_prompt": "b", "video_prompt": "m", "duration_s": 6,
         "end_image_prompt": "b later"}]})
    scenes, notes = _parse_scene_plan(both, 2, (4.0, 15.0))
    assert [bool(s["end_image_prompt"]) for s in scenes] == [True, False]
    assert any("transforms once" in n for n in notes)


# -- the two photographs -----------------------------------------------------

def test_the_end_frame_is_generated_from_the_start_frame(morphing):
    """Not merely beside it. They have to be the same shot, and handing the
    model the first one is the surest way to get that."""
    _cfg, store, engine, job = morphing
    job = engine.run(job)
    assert job.scenes[1]["plate_end"], "the transforming shot has no end frame"
    assert (store.job_dir(job.id) / job.scenes[1]["plate_end"]).is_file()
    assert not job.scenes[0]["plate_end"]        # the others have one photo

    backend = engine.providers.backend_for("image")
    end_call = [c for c in backend.calls
                if c["op"] == "submit" and "END FRAME OF A TRANSFORMATION"
                in c["prompt"]][0]
    assert any("scene_01.png" in str(m) for m in end_call["medias"]), \
        "the start frame was not supplied to the end frame's generation"
    assert "change ONLY" in end_call["prompt"]


def test_the_end_frame_is_judged_too(morphing):
    _cfg, _store, engine, job = morphing
    job = engine.run(job)
    assert job.scenes[1]["plate_end_qa"], "the second photograph went unchecked"


def test_the_gate_prices_both_photographs(morphing):
    """A transformation is two photographs of one shot. A forecast that counts
    one is the under-quote the gate exists to prevent, just smaller."""
    _cfg, _store, engine, job = morphing
    job = engine.run(job)
    plates = job.forecasts["plates"]
    # 3 scenes + 1 cast portrait + 1 end frame
    assert len(plates["items"]) == 5


# -- the clip ----------------------------------------------------------------

def test_the_clip_is_given_both_frames(morphing):
    _cfg, _store, engine, job = morphing
    job = engine.approve(engine.run(job))
    backend = engine.providers.backend_for("video")
    calls = [c for c in backend.calls if c["op"] == "submit" and c["kind"] == "video"]
    morph = [c for c in calls if c["params"].get("end_frame")]
    assert len(morph) == 1, "exactly one shot morphs"
    assert "scene_01_end" in str(morph[0]["params"]["end_frame"])


def test_a_shot_cannot_both_morph_and_ride_a_driver(morphing, tmp_path):
    """A morph takes its movement from the two frames, a driver from the video.
    Both at once describes no shot the model can make."""
    import subprocess
    _cfg, store, engine, job = morphing
    job = engine.run(job)
    drv = tmp_path / "d.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=green:size=640x360:rate=25:duration=5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(drv)],
                   check=True, capture_output=True)
    job = engine.add_driver(job, drv, "seedance")
    job = engine.attach_driver(job, "d1", [1])
    job = engine.approve(job)
    assert job.state == "failed"
    assert "both transforms and rides a driver" in job.error
