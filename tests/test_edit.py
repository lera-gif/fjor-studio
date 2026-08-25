"""GATE_CLIPS and the editor that lives on it.

The rest of the suite skips this gate (see conftest) because it was written
before the gate existed. Everything about it is therefore proven here: that the
shipped config stops at it, that the edit reaches ffmpeg, and that a cut which
lost a shot cannot be delivered against stale subtitle timings.
"""
import json

import pytest
import yaml

from conftest import make_job, scene_plan, write_config, write_replies
from fjor_studio.app import open_studio
from fjor_studio.assemble import duration_of
from fjor_studio.engine import TransitionError
from fjor_studio.stages.steps import cut_scenes, edit_of


def qa_ok():
    return json.dumps({"passed": True, "severity": "ok", "issues": [],
                       "summary": "fine"})


def setup(home, reference, scenes=3, skip=("GATE_PLAN",), **kw):
    """A job at GATE_CLIPS, with the gate ON."""
    pipeline = {"gates": {"skip": list(skip)}, "delivery": {"formats": ["9:16"]}}
    pipeline.update(kw)
    write_config(home, pipeline=pipeline)
    write_replies(home, text=scene_plan(scenes), analysis="analysed",
                  **{"qa:plate": qa_ok(), "qa:clip": qa_ok()})
    cfg, store, engine = open_studio(home)
    job = make_job(store, reference, scenes=scenes, config=cfg, packshot="formula")
    return cfg, store, engine, job


# -- the gate ---------------------------------------------------------------

def test_the_run_stops_on_the_shots_before_it_cuts_them(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))          # past GATE_PLATES
    assert job.state == "GATE_CLIPS"
    assert all(s["clip"] for s in job.scenes)      # the shots exist
    assert not (store.job_dir(job.id) / "draft" / "draft.mp4").exists()


def test_the_gate_writes_the_shots_and_their_verdicts(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    review = json.loads((store.job_dir(job.id) / "review" / "clips.json").read_text())
    assert [c["idx"] for c in review["clips"]] == [0, 1, 2]
    assert all(c["qa"] for c in review["clips"])
    assert all(c["in_cut"] for c in review["clips"])


def test_approving_it_cuts_the_draft(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    assert job.state == "GATE_DRAFT"
    assert (store.job_dir(job.id) / "draft" / "draft.mp4").exists()


def test_a_config_may_skip_it_because_everything_after_is_free(home, reference):
    _cfg, _store, engine, job = setup(home, reference,
                                      skip=("GATE_PLAN", "GATE_CLIPS"))
    job = engine.approve(engine.run(job))
    assert job.state == "GATE_DRAFT"
    assert any("GATE_CLIPS" in e.get("msg", "") for e in job.events
               if e["type"] == "gate_skipped")


def test_the_shipped_config_stops_there():
    """The owner asked for this gate. A default that skips it would be the
    feature not existing."""
    import pathlib
    cfg = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parents[1] / "config" / "pipeline.yaml")
        .read_text())
    assert "GATE_CLIPS" not in (cfg.get("gates") or {}).get("skip", [])


def test_a_bad_shot_is_re_bought_from_this_gate(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    before = job.scenes[1]["clip_attempts"]
    job = engine.revise(job, "clip", "she looks away from camera", scenes=[1])
    assert job.state == "GATE_CLIPS"                       # back to the same gate
    assert job.scenes[1]["clip_attempts"] == before + 1
    assert job.scenes[0]["clip_attempts"] == before        # the others untouched


def test_assembly_is_not_revisable_here_because_there_is_no_cut_yet(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    with pytest.raises(TransitionError):
        engine.revise(job, "assembly")


# -- the edit ---------------------------------------------------------------

def test_dropping_a_shot_shortens_the_cut(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    full = duration_of(store.job_dir(job.id) / "draft" / "draft.mp4")

    job = engine.set_edit(job, {"order": [0, 2]})
    assert job.state == "GATE_DRAFT"                       # re-cut, same gate
    short = duration_of(store.job_dir(job.id) / "draft" / "draft.mp4")
    assert short < full - 0.5
    assert [s["idx"] for s in cut_scenes(job)] == [0, 2]
    # the shot is dropped from the CUT, not deleted: it can be put back
    assert job.scenes[1]["clip"]


def test_a_dropped_shot_can_be_put_back(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    full = duration_of(store.job_dir(job.id) / "draft" / "draft.mp4")
    job = engine.set_edit(job, {"order": [0, 2]})
    job = engine.set_edit(job, {"order": [0, 1, 2]})
    assert duration_of(store.job_dir(job.id) / "draft" / "draft.mp4") == \
        pytest.approx(full, abs=0.15)


def test_reordering_reaches_the_cut(home, reference):
    """Scenes have different durations, so the running order is measurable at
    the join rather than only in the manifest."""
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    job = engine.set_edit(job, {"order": [2, 1, 0]})
    manifest = json.loads(
        (store.job_dir(job.id) / "draft" / "edit_manifest.json").read_text())
    clips = [s["source"].split("/")[-1] for s in manifest["segments"]
             if s["role"] == "clip"]
    assert clips == ["scene_02.mp4", "scene_01.mp4", "scene_00.mp4"]


def test_the_edit_survives_into_delivery(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    job = engine.set_edit(job, {"order": [1, 0]})
    job = engine.approve(job)
    assert job.state == "done"
    manifest = json.loads(
        (store.job_dir(job.id) / "finals" / "build_manifest.json").read_text())
    clips = [s["source"].split("/")[-1]
             for s in manifest["finals"][0]["segments"] if s["role"] == "clip"]
    assert clips == ["scene_01.mp4", "scene_00.mp4"]


def test_an_edit_at_the_clip_gate_waits_for_the_approval_that_cuts(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    job = engine.set_edit(job, {"order": [0, 2]})
    assert job.state == "GATE_CLIPS"                       # nothing to re-cut yet
    assert not (store.job_dir(job.id) / "draft" / "draft.mp4").exists()
    job = engine.approve(job)
    manifest = json.loads(
        (store.job_dir(job.id) / "draft" / "edit_manifest.json").read_text())
    assert len([s for s in manifest["segments"] if s["role"] == "clip"]) == 2


def a_real_bed():
    """The suite runs against the real asset library, so the bed has to be one
    that is actually in it -- a made-up name is refused, which is its own test
    below."""
    import pathlib
    from fjor_studio.assemble import list_music
    beds = list_music(pathlib.Path(__file__).resolve().parents[1] / "assets")
    if not beds:
        pytest.skip("no music beds in assets/")
    return beds[0]


def test_the_music_bed_is_chosen_at_a_gate_not_in_the_brief(home, reference):
    bed = a_real_bed()
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    assert job.meta["draft"]["music"] is None              # the brief did not ask
    job = engine.set_edit(job, {"music": bed})
    assert job.state == "GATE_DRAFT"                       # the re-cut succeeded
    assert job.meta["draft"]["music"].startswith(bed)
    job = engine.set_edit(job, {"music": ""})
    assert job.meta["draft"]["music"] is None              # and can be taken off


def test_a_bed_that_is_not_in_the_library_fails_the_cut_loudly(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    job = engine.set_edit(job, {"music": "no-such-bed"})
    assert job.state == "failed"
    assert "no-such-bed" in job.error


def test_a_bed_named_in_the_brief_still_reaches_an_old_job(home, reference):
    """`intake.music` seeds the edit -- the CLI still offers --music, and a job
    made before the editor existed must not lose its bed on a re-cut."""
    bed = a_real_bed()
    _cfg, _store, engine, job = setup(home, reference)
    job.intake["music"] = bed
    job = engine.approve(engine.approve(engine.run(job)))
    assert job.meta["draft"]["music"].startswith(bed)
    assert edit_of(job)["music"] == bed
    job = engine.set_edit(job, {"music": ""})              # the gate overrides it
    assert job.meta["draft"]["music"] is None


def test_the_edit_overrides_the_configured_subtitle_settings(home, reference):
    """Burning them needs a live transcription key, so this checks the settings
    the burner is handed -- test_subtitles.py owns the rendering itself."""
    from fjor_studio.stages.steps import _subtitle_settings
    cfg, store, engine, job = setup(
        home, reference, subtitles={"enabled": True, "colour": "yellow",
                                    "size": "medium"})

    class Ctx:
        pass
    ctx = Ctx()
    ctx.config, ctx.job = cfg, job

    style, on = _subtitle_settings(ctx)
    assert on and style.colour == "yellow" and style.size == "medium"

    job.meta["edit"] = {"subtitles": {"colour": "white", "size": "large"}}
    style, on = _subtitle_settings(ctx)
    assert on and style.colour == "white" and style.size == "large"

    job.meta["edit"] = {"subtitles": {"enabled": False}}
    style, on = _subtitle_settings(ctx)
    assert (style, on) == (None, False)


# -- what the editor refuses ------------------------------------------------

def test_an_edit_that_drops_every_shot_is_refused(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    with pytest.raises(TransitionError):
        engine.set_edit(job, {"order": []})


def test_an_edit_naming_a_scene_that_does_not_exist_is_refused(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    with pytest.raises(TransitionError) as exc:
        engine.set_edit(job, {"order": [0, 9]})
    assert "9" in str(exc.value)


def test_an_edit_repeating_a_shot_is_refused(home, reference):
    """Not a nice-to-have: the same clip twice would be transcribed once and
    subtitled over both, which is a defect nobody would look for."""
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    with pytest.raises(TransitionError):
        engine.set_edit(job, {"order": [0, 0, 1]})


def test_an_unknown_edit_key_is_refused_rather_than_ignored(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    with pytest.raises(TransitionError):
        engine.set_edit(job, {"crossfade_s": 1.0})
    with pytest.raises(TransitionError):
        engine.set_edit(job, {"subtitles": {"colour": "yellow", "styel": "x"}})


def test_the_edit_cannot_be_set_while_a_stage_is_running(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.run(job)                                  # at GATE_PLATES
    job.state = "clips"
    with pytest.raises(TransitionError):
        engine.set_edit(job, {"order": [0]})


def test_the_edit_is_recorded_as_an_event(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    job = engine.set_edit(job, {"order": [2, 0], "music": "bed"})
    said = [e["msg"] for e in job.events if e["type"] == "edit"][-1]
    assert "2-0" in said and "dropped [1]" in said and "music bed" in said
