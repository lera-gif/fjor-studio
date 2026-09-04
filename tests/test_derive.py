"""Deriving a variation from a finished job."""
import json

import pytest

from conftest import make_job, scene_plan, write_config, write_replies
from fjor_studio.app import open_studio
from fjor_studio.derive import FROM_STAGES, DeriveError, derive
from fjor_studio.derive import plan as derive_plan


@pytest.fixture
def finished(home, reference):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]},
                                 "delivery": {"formats": ["9:16"]}})
    write_replies(home, analysis="analysed", text=scene_plan(2),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    job = make_job(store, reference, scenes=2, config=cfg, packshot="formula")
    job = engine.approve(engine.approve(engine.run(job)))
    assert job.state == "done"
    return cfg, store, engine, job


def counts(backend, kind):
    return len([c for c in backend.calls
                if c["op"] == "submit" and c["kind"] == kind])


# -- what each starting point inherits ---------------------------------------

def test_a_re_cut_variation_buys_nothing(finished):
    """Most variations change one thing; re-running from scratch would re-buy
    the same plates to arrive at the same place."""
    _cfg, store, engine, job = finished
    img = engine.providers.backend_for("image")
    vid = engine.providers.backend_for("video")
    before = (counts(img, "image"), counts(vid, "video"))

    child = derive(store, job.id, "LIPIL900", "assembly",
                   {"concept": "variant"}, "swap the music")
    child = engine.run(child)
    assert child.state == "GATE_DRAFT"
    assert (counts(img, "image"), counts(vid, "video")) == before
    assert child.spent == 0.0
    assert child.meta["inherited"]["inherited_credits"] == pytest.approx(job.spent)


def test_new_clips_keep_the_plates(finished):
    _cfg, store, engine, job = finished
    img = engine.providers.backend_for("image")
    vid = engine.providers.backend_for("video")
    before_img, before_vid = counts(img, "image"), counts(vid, "video")

    child = engine.run(derive(store, job.id, "LIPIL901", "clips", {}, "more energy"))
    assert counts(img, "image") == before_img          # plates inherited
    assert counts(vid, "video") == before_vid + 2      # clips re-bought
    assert all(s["plate"] for s in child.scenes)
    assert child.spent > 0


def test_new_plates_keep_the_prompts(finished):
    _cfg, store, engine, job = finished
    child = derive(store, job.id, "LIPIL902", "plates", {}, "warmer light")
    assert all(s["image_prompt"] for s in child.scenes)
    assert not any(s["plate"] for s in child.scenes)
    assert child.state == "plates"


def test_a_rewrite_keeps_only_the_analysis(finished):
    _cfg, store, engine, job = finished
    child = derive(store, job.id, "LIPIL903", "prompts", {}, "different hook")
    assert child.analysis == job.analysis
    assert not any(s["image_prompt"] for s in child.scenes)
    assert child.state == "prompts"


# -- what always comes across ------------------------------------------------

def test_the_reference_never_has_to_be_uploaded_again(finished):
    """This is the friction the feature exists to remove."""
    _cfg, store, _engine, job = finished
    child = derive(store, job.id, "LIPIL904", "prompts", {}, "")
    ref = store.job_dir("LIPIL904") / "ref"
    assert list(ref.glob("*")), "the reference did not come across"
    assert child.intake["reference_local"] == job.intake["reference_local"]


def test_the_note_reaches_the_writer_as_part_of_the_brief(finished):
    """A variation with no instruction is just a copy."""
    _cfg, store, _engine, job = finished
    child = derive(store, job.id, "LIPIL905", "prompts", {}, "lead with the objection")
    assert "lead with the objection" in child.intake["brief"]


def test_inherited_credits_are_recorded_but_not_claimed_as_spend(finished):
    """The ledger answers 'what did THIS job spend', and for a re-cut that is
    nothing."""
    _cfg, store, _engine, job = finished
    child = derive(store, job.id, "LIPIL906", "assembly", {}, "")
    assert child.ledger == []
    assert child.spent == 0.0
    assert child.meta["inherited"]["inherited_credits"] == pytest.approx(job.spent)


def test_inherited_scenes_carry_no_submissions(finished):
    """Carrying them would make the child look able to collect generations it
    never made."""
    _cfg, store, _engine, job = finished
    child = derive(store, job.id, "LIPIL907", "assembly", {}, "")
    assert all(s["submissions"] == [] for s in child.scenes)
    assert child.open_submissions() == []


def test_both_jobs_record_the_lineage(finished):
    _cfg, store, _engine, job = finished
    child = derive(store, job.id, "LIPIL908", "clips", {}, "")
    assert child.meta["derived_from"] == job.id
    assert "LIPIL908" in store.load(job.id).meta["derivatives"]


def test_overrides_replace_the_parent_settings(finished):
    _cfg, store, _engine, job = finished
    child = derive(store, job.id, "LIPIL909", "assembly",
                   {"music": "Radiant_Energy_2026-08-14T144237",
                    "crossfade_s": 0.8, "concept": "nomusic"}, "")
    assert child.intake["music"].startswith("Radiant")
    assert child.intake["crossfade_s"] == 0.8
    assert child.intake["concept"] == "nomusic"
    assert child.intake["packshot"] == job.intake["packshot"]   # untouched


# -- refusals ----------------------------------------------------------------

def test_an_unknown_starting_point_is_refused(finished):
    _cfg, store, _engine, job = finished
    with pytest.raises(DeriveError, match="not a starting point"):
        derive(store, job.id, "LIPIL910", "magic", {}, "")


def test_re_cutting_a_job_with_no_clips_is_refused(home, reference):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="a", text=scene_plan(2),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    job = engine.run(make_job(store, reference, scenes=2, config=cfg))
    assert job.state == "GATE_PLATES"
    with pytest.raises(DeriveError, match="nothing to re-cut"):
        derive(store, job.id, "LIPIL911", "assembly", {}, "")


def test_the_plan_preview_has_no_side_effects(finished):
    """The dialog prices the choice before anything is created."""
    _cfg, store, _engine, job = finished
    before = set(store.list_ids())
    p = derive_plan(job, "clips")
    assert p["rebuys"] == ["clips"] and p["plates_kept"] == 2
    assert set(store.list_ids()) == before


# -- the voiceover, which is a file and a reference and must not be split ------
#
# SL041 (derived from SL040 at 'prompts') failed at assembly on a missing
# audio/scene_00_vo.wav. The reference travelled and the file did not, and
# `voiceovers` skips any scene that already has a vo_track -- so nothing was
# re-bought and nothing said so until ffmpeg could not open the input.

def _give_everyone_a_voice(store, job):
    """Make the parent's shots carry recorded voiceovers, on disk."""
    job_dir = store.job_dir(job.id)
    (job_dir / "audio").mkdir(parents=True, exist_ok=True)
    for s in job.scene_objs():
        s.voice, s.line = "vo", f"line for scene {s.idx}"
        s.vo_track = f"audio/scene_{s.idx:02d}_vo.wav"
        (job_dir / s.vo_track).write_bytes(b"RIFF fake wav")
        job.put_scene(s)
        job.add_artifact("audio", s.vo_track)
    store.save(job)
    return job


def test_deriving_at_prompts_drops_the_old_recording(finished):
    """The line is about to be rewritten, so the old recording is a voice
    saying words that are no longer in the script."""
    _cfg, store, _engine, src = finished
    _give_everyone_a_voice(store, src)
    child = derive(store, src.id, "SL900", "prompts")
    assert all(s.get("vo_track") is None for s in child.scenes)


def test_deriving_at_plates_carries_the_recording_as_a_file(finished):
    """The line comes across unchanged, so the recording is still correct --
    and it was already paid for."""
    _cfg, store, _engine, src = finished
    _give_everyone_a_voice(store, src)
    child = derive(store, src.id, "SL901", "plates")
    child_dir = store.job_dir(child.id)
    for s in child.scenes:
        assert s["vo_track"], "the reference was dropped but the line is the same"
        assert (child_dir / s["vo_track"]).is_file(), (
            f"{s['vo_track']} is referenced but not on disk -- assembly will "
            f"die on a missing input")


def test_no_derived_job_ever_names_a_voiceover_it_does_not_have(finished):
    """The invariant, across every starting point: a vo_track either resolves
    to a real file or is absent. Nothing in between ships."""
    _cfg, store, _engine, src = finished
    _give_everyone_a_voice(store, src)
    for i, stage in enumerate(FROM_STAGES):
        child = derive(store, src.id, f"SL91{i}", stage)
        child_dir = store.job_dir(child.id)
        for s in child.scenes:
            rel = s.get("vo_track")
            assert rel is None or (child_dir / rel).is_file(), (
                f"derived at '{stage}': scene {s['idx']} names {rel}, "
                f"which is not there")
