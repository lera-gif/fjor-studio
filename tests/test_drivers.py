"""Motion drivers: someone else's movement on our photograph.

The tool this was ported from lost a 23-second driver to a 15-second clamp
because the engine was chosen after the prompts were written. These tests are
mostly about that class of mistake: a decision taken at the wrong moment, or a
soundtrack nobody asked for.
"""
import json
import subprocess

import pytest

from conftest import make_job, scene_plan, write_config, write_replies
from fjor_studio import drivers
from fjor_studio.app import open_studio
from fjor_studio.engine import TransitionError
from fjor_studio.gen.base import GenError


def a_video(path, seconds=6, size="640x360"):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"color=c=green:size={size}:rate=25:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(path)], check=True, capture_output=True)
    return path


@pytest.fixture
def studio(home, reference):
    # GATE_PLAN is NOT skipped: it is where a driver is attached, because it is
    # the first moment the shot list exists and the last before anything is
    # bought.
    write_config(home, pipeline={"gates": {"skip": ["GATE_CLIPS"]}})
    write_replies(home, analysis="analysed", text=scene_plan(2),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    return cfg, store, engine, make_job(store, reference, scenes=2, config=cfg)


# -- the driver itself -------------------------------------------------------

def test_a_driver_is_copied_into_the_job_and_measured(studio, tmp_path):
    """Copied, not referenced: a job stays re-runnable after whatever the driver
    was cut from has moved."""
    _cfg, store, engine, job = studio
    src = a_video(tmp_path / "cut.mp4", seconds=7)
    job = engine.add_driver(job, src, "kling-mc-3.0", "the walk from the ref")
    d = drivers.all_of(job)[0]
    assert d["engine"] == "kling-mc-3.0"
    assert d["duration_s"] == pytest.approx(7, abs=0.2)
    assert (store.job_dir(job.id) / d["file"]).is_file()
    src.unlink()                                  # the source can go
    assert (store.job_dir(job.id) / d["file"]).is_file()


def test_a_driver_that_is_not_mp4_or_mov_is_refused(studio, tmp_path):
    _cfg, _store, engine, job = studio
    bad = tmp_path / "cut.webm"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=red:size=320x240:duration=1", str(bad)],
                   check=True, capture_output=True)
    with pytest.raises(GenError):
        engine.add_driver(job, bad, "kling-mc-3.0")


def test_one_driver_serves_several_shots(studio, tmp_path):
    _cfg, _store, engine, job = studio
    job = engine.run(job)                          # to GATE_PLAN: the shots exist
    job = engine.add_driver(job, a_video(tmp_path / "c.mp4"), "seedance")
    job = engine.attach_driver(job, "d1", [0, 1])
    assert [s["driver"] for s in job.scenes] == ["d1", "d1"]


# -- the decision that has to be taken early ---------------------------------

def test_motion_control_retimes_the_shot_to_the_driver(studio, tmp_path):
    """Their 23s driver became a 15s clip because the length was decided while
    writing prompts. Motion Control runs exactly as long as its driver, so the
    shot takes the driver's length and the plan's clamp does not apply."""
    _cfg, _store, engine, job = studio
    job = engine.run(job)
    assert job.scenes[0]["duration_s"] <= 15
    job = engine.add_driver(job, a_video(tmp_path / "long.mp4", seconds=23),
                            "kling-mc-3.0")
    job = engine.attach_driver(job, "d1", [0])
    assert job.scenes[0]["duration_s"] == pytest.approx(23, abs=0.2)
    said = [e["msg"] for e in job.events if e["type"] == "driver_attached"][-1]
    assert "retimed" in said


def test_a_seedance_driver_leaves_the_length_alone(studio, tmp_path):
    """Seedance's video reference is clamped like any other Seedance shot."""
    _cfg, _store, engine, job = studio
    job = engine.run(job)
    was = job.scenes[0]["duration_s"]
    job = engine.add_driver(job, a_video(tmp_path / "c.mp4", seconds=23), "seedance")
    job = engine.attach_driver(job, "d1", [0])
    assert job.scenes[0]["duration_s"] == was


def test_a_driver_cannot_be_attached_to_a_shot_already_bought(studio, tmp_path):
    _cfg, _store, engine, job = studio
    job = engine.approve(engine.approve(engine.run(job)))    # buys the clips
    job = engine.add_driver(job, a_video(tmp_path / "c.mp4"), "seedance")
    with pytest.raises(TransitionError) as exc:
        engine.attach_driver(job, "d1", [0])
    assert "already has a clip" in str(exc.value)


# -- what reaches the backend ------------------------------------------------

def test_a_driven_shot_is_generated_by_the_driver_s_engine(studio, tmp_path):
    _cfg, _store, engine, job = studio
    job = engine.run(job)
    job = engine.add_driver(job, a_video(tmp_path / "c.mp4"), "kling-mc-3.0")
    job = engine.attach_driver(job, "d1", [0])
    job = engine.approve(engine.approve(job))
    backend = engine.providers.backend_for("video")
    calls = [c for c in backend.calls if c["op"] == "submit" and c["kind"] == "video"]
    driven = [c for c in calls if c["model"] == "kling-3.0/motion-control"]
    plain = [c for c in calls if c["model"] != "kling-3.0/motion-control"]
    assert len(driven) == 1 and len(plain) == 1      # one of each, as attached
    assert driven[0]["params"].get("driver_video")


def test_a_driven_shot_is_silent_and_its_line_is_spoken_by_us(studio, tmp_path):
    """The driver carries a stranger talking. Motion Control gives us no say
    over the soundtrack, so the shot is silent and the line is ours to say --
    or it is simply gone, with nothing in the run admitting it."""
    _cfg, store, engine, job = studio
    job = engine.run(job)
    job = engine.add_driver(job, a_video(tmp_path / "c.mp4"), "kling-mc-3.0")
    job = engine.attach_driver(job, "d1", [0])
    scene = job.scene(0)
    scene.line = "This is the line the ad actually says."
    job.put_scene(scene)
    store.save(job)

    job = engine.approve(engine.approve(job))
    backend = engine.providers.backend_for("video")
    driven = [c for c in backend.calls
              if c["op"] == "submit" and c["model"] == "kling-3.0/motion-control"][0]
    assert driven["params"]["generate_audio"] is False
    assert job.scenes[0]["vo_track"], "the line was lost with the driver's audio"


def test_the_first_frame_of_a_driver_can_be_read(studio, tmp_path):
    """The plate has to start from the driver's pose, angle and supporting
    surface -- a body that starts from a different surface animates wrongly."""
    _cfg, store, engine, job = studio
    job = engine.add_driver(job, a_video(tmp_path / "c.mp4"), "seedance")
    frame = drivers.first_frame(store.job_dir(job.id), drivers.all_of(job)[0],
                                tmp_path / "f.png")
    assert frame.is_file() and frame.stat().st_size > 0


# -- what the writer and the plate are told ----------------------------------

def test_the_writer_is_told_which_shots_ride_a_driver(studio, tmp_path):
    _cfg, store, engine, job = studio
    job = engine.run(job)
    job = engine.add_driver(job, a_video(tmp_path / "c.mp4", seconds=11),
                            "kling-mc-3.0", "the sit-to-stand")
    job = engine.attach_driver(job, "d1", [0])
    job = engine.revise(job, "prompts", "rewrite shot 0 for its driver")

    backend = engine.providers.backend_for("text")
    brief = [c for c in backend.calls
             if c.get("kind") == "text"][-1]["prompt"]
    assert "MOTION DRIVERS" in brief
    assert "300-600 characters" in brief
    assert "NEVER DESCRIBE THE MOTION" in brief
    assert "11.0s" in brief and "kling-mc-3.0" in brief
    # the Kling rules only appear when a Kling driver is on the job
    assert "write NO speech" in brief


def test_a_seedance_only_job_is_not_given_the_kling_rules(studio, tmp_path):
    _cfg, _store, engine, job = studio
    job = engine.run(job)
    job = engine.add_driver(job, a_video(tmp_path / "c.mp4"), "seedance")
    job = engine.attach_driver(job, "d1", [0])
    job = engine.revise(job, "prompts", "rewrite")
    backend = engine.providers.backend_for("text")
    brief = [c for c in backend.calls
             if c.get("kind") == "text"][-1]["prompt"]
    assert "MOTION DRIVERS" in brief
    assert "write NO speech" not in brief


def test_a_job_with_no_driver_says_nothing_about_drivers(studio):
    """Byte-for-byte the brief it always was. A feature nobody used must not
    change the prompt of every other job."""
    _cfg, _store, engine, job = studio
    job = engine.run(job)
    backend = engine.providers.backend_for("text")
    brief = [c for c in backend.calls
             if c.get("kind") == "text"][-1]["prompt"]
    assert "MOTION DRIVER" not in brief


def test_a_rewrite_cannot_shorten_a_motion_control_shot(studio, tmp_path):
    """The plan clamps durations to 4-15s. A Motion Control shot is as long as
    its driver, and a rewrite must not quietly hand it back to the clamp."""
    _cfg, _store, engine, job = studio
    job = engine.run(job)
    job = engine.add_driver(job, a_video(tmp_path / "long.mp4", seconds=23),
                            "kling-mc-3.0")
    job = engine.attach_driver(job, "d1", [0])
    job = engine.revise(job, "prompts", "rewrite")
    assert job.scenes[0]["duration_s"] == pytest.approx(23, abs=0.2)


def test_the_plate_of_a_driven_shot_gets_the_opening_frame_as_a_template(studio, tmp_path):
    """The video model re-poses this photograph into the driver's motion, so the
    photograph has to open where the driver opens."""
    _cfg, store, engine, job = studio
    job = engine.run(job)
    job = engine.add_driver(job, a_video(tmp_path / "c.mp4"), "seedance")
    job = engine.attach_driver(job, "d1", [0])
    job = engine.approve(job)                       # buys the plates

    backend = engine.providers.backend_for("image")
    plate_calls = [c for c in backend.calls
                   if c["op"] == "submit" and c["kind"] == "image"]
    driven = [c for c in plate_calls if "STARTING FRAME" in c["prompt"]]
    assert len(driven) == 1, "only the driven shot gets the start-frame rule"
    assert any("_template" in str(m) for m in driven[0]["medias"]), \
        "the driver's opening frame was not supplied as a geometry template"
    assert "DIFFERENT INDIVIDUAL of the same type" in driven[0]["prompt"]
    assert "ROOM IS REBUILT" in driven[0]["prompt"]
    # and the ordinary shot is untouched
    plain = [c for c in plate_calls if "STARTING FRAME" not in c["prompt"]]
    assert len(plain) == 1


def test_a_driver_is_registered_and_attached_or_neither(studio, tmp_path):
    """A driver registered and then not attached is a video copied into the job
    that changes nothing -- and, the way it actually costs money, a plan gate
    approved with the shots' durations not yet retimed to the driver's."""
    _cfg, store, engine, job = studio
    job = engine.run(job)                       # the plan exists at GATE_PLAN
    src = a_video(tmp_path / "d.mp4", seconds=2)
    with pytest.raises(TransitionError):
        engine.drive(job, src, [], "kling-mc-3.0")
    job = store.load(job.id)
    assert not job.meta.get("drivers")
    assert not (store.job_dir(job.id) / "drivers").exists()

    with pytest.raises(TransitionError):
        engine.drive(job, src, [99], "kling-mc-3.0")
    assert not store.load(job.id).meta.get("drivers")

    job = engine.drive(job, src, [0], "kling-mc-3.0", note="the sit-up")
    assert len(job.meta["drivers"]) == 1
    assert job.scene(0).driver == "d1"
    assert job.scene(0).duration_s == job.meta["drivers"][0]["duration_s"]
