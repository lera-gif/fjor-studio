"""Runs the whole pipeline on the mock backend, gate by gate.

These tests execute the engine. None of them read source or assert on strings a
stage happens to log -- a check that cannot fail is worth nothing here.
"""
import json

import pytest

from conftest import make_job, scene_plan, write_config, write_replies
from fjor_studio.app import open_studio
from fjor_studio.engine import TransitionError
from fjor_studio.qa import Verdict, technical_failure


def qa_ok():
    return json.dumps({"passed": True, "severity": "ok", "issues": [],
                       "summary": "fine"})


def qa_critical(issue="a Nike swoosh is visible on the shirt"):
    return json.dumps({"passed": False, "severity": "critical",
                       "issues": [issue], "summary": "blocking defect"})


def setup(home, reference, scenes=2, pipeline=None, **replies):
    write_config(home, pipeline=pipeline)
    write_replies(home, text=scene_plan(scenes), analysis="reference analysed",
                  **{"qa:plate": replies.get("plate_qa", qa_ok()),
                     "qa:clip": replies.get("clip_qa", qa_ok())})
    cfg, store, engine = open_studio(home)
    return cfg, store, engine, make_job(store, reference, scenes=scenes, config=cfg)


# -- the happy path ----------------------------------------------------------

def test_run_stops_at_the_first_gate(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.run(job)
    assert job.state == "GATE_PLAN"
    assert job.gate_ready is True
    assert len(job.scenes) == 2
    assert job.scenes[0]["image_prompt"] == "plate 0"


def test_full_walk_through_every_gate(home, reference):
    _cfg, store, engine, job = setup(home, reference, scenes=3)

    job = engine.run(job)
    assert job.state == "GATE_PLAN"
    # nothing has been bought yet beyond analysis and the prompt call
    assert all(not s["plate"] for s in job.scenes)

    job = engine.approve(job)
    assert job.state == "GATE_PLATES"
    assert all(s["plate"] for s in job.scenes)
    for s in job.scenes:
        assert (store.job_dir(job.id) / s["plate"]).exists()

    job = engine.approve(job)
    assert job.state == "GATE_DRAFT"
    assert all(s["clip"] for s in job.scenes)
    draft = store.job_dir(job.id) / "draft" / "draft.mp4"
    assert draft.exists()
    # a real, openable video -- not a stub with an .mp4 extension
    from fjor_studio.assemble import probe
    vs = [s for s in probe(draft)["streams"] if s["codec_type"] == "video"][0]
    assert (vs["width"], vs["height"]) == (1080, 1920)

    job = engine.approve(job)
    assert job.state == "done"
    expected = f"n-{job.id}_ch-fb_t-video_c-ugc_pr-lp_ds-nano_w-34_s-1080x1920.mp4"
    final = store.job_dir(job.id) / "finals" / expected
    assert final.exists()
    from fjor_studio.assemble import probe
    streams = probe(final)["streams"]
    vs = [s for s in streams if s["codec_type"] == "video"][0]
    assert (vs["width"], vs["height"]) == (1080, 1920)
    # audio survives even though every mock clip is silent
    assert any(s["codec_type"] == "audio" for s in streams)
    week_dir = home / "VIDEO" / "LIPEDEMA PILATES" / "34 week"
    assert (week_dir / expected).exists()
    assert (week_dir / f"{job.id}_manifest.json").exists()


def test_the_gate_before_the_video_spend_forecasts_it(home, reference):
    _cfg, _store, engine, job = setup(home, reference, scenes=3)
    job = engine.approve(engine.run(job))
    assert job.state == "GATE_PLATES"
    f = job.forecasts["clips"]
    assert f["complete"] is True
    assert f["total"] == pytest.approx(372.0)      # 3 scenes * 5s * 24.8
    assert f["unpriced"] == []


def test_the_forecast_says_so_when_it_cannot_price_a_model(home, reference, monkeypatch):
    """A total that quietly omits an unpriceable line reads as the price. The
    gate has to say the number is a floor."""
    from fjor_studio import costs
    monkeypatch.delitem(costs.MOCK_RATES, "video")     # no rate for video at all
    _cfg, _store, engine, job = setup(home, reference, scenes=2)
    job = engine.approve(engine.run(job))
    f = job.forecasts["clips"]
    assert f["complete"] is False
    assert f["total"] == 0.0
    assert f["unpriced"] == ["mock/bytedance/seedance-2-fast"] * 2
    assert "forecast_incomplete" in [e["type"] for e in job.events]


def test_ledger_records_what_the_provider_actually_charged(home, reference):
    _cfg, _store, engine, job = setup(home, reference, scenes=2)
    job = engine.approve(engine.approve(engine.run(job)))
    assert job.state == "GATE_DRAFT"
    clip_lines = [e for e in job.ledger if e["stage"] == "clips"]
    assert len(clip_lines) == 2
    assert sum(e["credits"] for e in clip_lines) == pytest.approx(248.0)
    assert all(e["backend"] == "mock" for e in job.ledger)


# -- gates -------------------------------------------------------------------

def test_a_skipped_gate_passes_through_but_is_still_logged(home, reference):
    _cfg, _store, engine, job = setup(home, reference,
                                      pipeline={"gates": {"skip": ["GATE_PLAN"]}})
    job = engine.run(job)
    assert job.state == "GATE_PLATES"          # ran straight past GATE_PLAN
    skipped = [e for e in job.events if e["type"] == "gate_skipped"]
    assert len(skipped) == 1 and "GATE_PLAN" in skipped[0]["msg"]
    # the plan review was still written -- skipping the stop is not skipping the work
    assert (_store.job_dir(job.id) / "review" / "plan.json").exists()


def test_the_money_gates_cannot_be_skipped_by_config(home, reference):
    from fjor_studio.engine import PipelineError
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLATES"]}})
    with pytest.raises(PipelineError, match="cannot be skipped"):
        open_studio(home)


def test_approving_when_not_at_a_gate_is_refused(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    with pytest.raises(TransitionError, match="not at a gate"):
        engine.approve(job)


# -- revision ----------------------------------------------------------------

def test_revising_plates_returns_to_the_same_gate(home, reference):
    _cfg, _store, engine, job = setup(home, reference, scenes=2)
    job = engine.approve(engine.run(job))
    assert job.state == "GATE_PLATES"
    first_plate = job.scenes[0]["plate"]

    job = engine.revise(job, "plates", "warmer light", scenes=[0])
    assert job.state == "GATE_PLATES"          # forward, back to the same gate
    assert job.revisions[-1]["what"] == "plates"
    assert job.revisions[-1]["scenes"] == [0]
    assert job.scenes[0]["plate"] == first_plate   # deterministic mock, same bytes


def test_revising_captions_at_the_draft_gate_costs_nothing(home, reference):
    _cfg, _store, engine, job = setup(home, reference, scenes=2)
    job = engine.approve(engine.approve(engine.run(job)))
    assert job.state == "GATE_DRAFT"
    spent_before = job.spent
    job = engine.revise(job, "captions", "bigger type")
    assert job.state == "GATE_DRAFT"
    assert job.spent == pytest.approx(spent_before)   # assembly is ffmpeg, not credits


def test_an_unknown_revision_target_lists_the_real_ones(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.run(job)
    with pytest.raises(TransitionError, match="is not revisable"):
        engine.revise(job, "lighting")


# -- QA drives regeneration --------------------------------------------------

def test_a_critical_plate_is_regenerated_up_to_the_cap(home, reference):
    _cfg, store, engine, job = setup(home, reference, scenes=1,
                                     plate_qa=[qa_critical(), qa_critical()])
    job = engine.approve(engine.run(job))
    scene = job.scenes[0]
    assert scene["plate_attempts"] == 2         # first try plus one regeneration
    regens = [e for e in job.events if e["type"] == "qa_regen"]
    assert len(regens) == 1
    assert scene["plate_qa"]["severity"] == "critical"


def test_a_plate_that_passes_on_retry_stops_regenerating(home, reference):
    _cfg, _store, engine, job = setup(home, reference, scenes=1,
                                      plate_qa=[qa_critical(), qa_ok()])
    job = engine.approve(engine.run(job))
    assert job.scenes[0]["plate_attempts"] == 2
    assert job.scenes[0]["plate_qa"]["passed"] is True


def test_clips_do_not_auto_regenerate_by_default(home, reference):
    _cfg, _store, engine, job = setup(home, reference, scenes=1,
                                      clip_qa=qa_critical())
    job = engine.approve(engine.approve(engine.run(job)))
    assert job.state == "GATE_DRAFT"
    assert job.scenes[0]["clip_attempts"] == 1     # paid once, then asked a human
    assert [e for e in job.events if e["type"] == "qa_regen"] == []


def test_a_blocking_clip_verdict_fails_preflight(home, reference):
    _cfg, store, engine, job = setup(home, reference, scenes=1,
                                     clip_qa=qa_critical())
    job = engine.approve(engine.approve(engine.run(job)))
    job = engine.approve(job)
    assert job.state == "failed"
    assert "preflight failed" in job.error
    report = json.loads((store.job_dir(job.id) / "review" / "preflight.json").read_text())
    assert report["failed"] == ["clip QA"]
    # the failure has to say WHICH shot and what would help. LME109 got
    # "preflight failed: clip QA", retried -- the only move the message
    # suggests -- and failed identically, because retry re-reads the same file.
    assert "blocking: [0]" in job.error
    assert "revise" in job.error and "--scene" in job.error
    assert "Retrying cannot help" in job.error


def test_retrying_a_failed_preflight_changes_nothing(home, reference):
    """Not a hypothetical: it is the first thing a producer tries."""
    _cfg, _store, engine, job = setup(home, reference, scenes=1,
                                      clip_qa=qa_critical())
    job = engine.approve(engine.approve(engine.approve(engine.run(job))))
    spent, error = job.spent, job.error
    job = engine.retry(job)
    assert job.state == "failed"
    assert job.error == error          # the same verdict on the same file
    assert job.spent == spent          # and it cost nothing to learn that twice


def test_a_silent_clip_under_an_external_voice_does_not_fail_preflight(home, reference):
    """The clip is MEANT to be silent; one such verdict must not block the run."""
    silent = json.dumps({"passed": False, "severity": "critical",
                         "issues": ["the actor does not speak at all"],
                         "summary": "no dialogue"})
    _cfg, _store, engine, job = setup(home, reference, scenes=1, clip_qa=silent,
                                      pipeline={"voice": {"source": "elevenlabs"}})
    job = engine.approve(engine.approve(engine.run(job)))
    assert job.scenes[0]["clip_qa"]["speech_only"] is True
    assert job.scenes[0]["clip_attempts"] == 1
    job = engine.approve(job)
    assert job.state == "done"


def test_the_same_verdict_does_block_when_the_video_model_speaks(home, reference):
    silent = json.dumps({"passed": False, "severity": "critical",
                         "issues": ["the actor does not speak at all"],
                         "summary": "no dialogue"})
    _cfg, _store, engine, job = setup(home, reference, scenes=1, clip_qa=silent,
                                      pipeline={"voice": {"source": "seedance"}})
    job = engine.approve(engine.approve(engine.run(job)))
    assert job.scenes[0]["clip_qa"]["speech_only"] is False
    job = engine.approve(job)
    assert job.state == "failed"


def test_preflight_reports_checks_that_could_not_look(home, reference):
    _cfg, store, engine, job = setup(home, reference, scenes=1,
                                     pipeline={"qa": {"enabled": False}})
    job = engine.approve(engine.approve(engine.run(job)))
    job = engine.approve(job)
    report = json.loads((store.job_dir(job.id) / "review" / "preflight.json").read_text())
    assert job.state == "done"
    assert report["failed"] == []
    # QA was off, so the clip-QA check had nothing to look at -- and says so
    # rather than reporting a clean run
    assert report["could_not_look"] == ["clip QA"]
    assert report["clean"] is False


# -- a revision aimed at particular scenes ----------------------------------

def test_revising_named_scenes_redoes_only_those(home, reference):
    """`revise --scene 3` used to record the scene and change nothing: the redo
    either re-ran everything or, because finished work is skipped, nothing."""
    _cfg, store, engine, job = setup(home, reference, scenes=3)
    job = engine.approve(engine.run(job))
    assert job.state == "GATE_PLATES"
    backend = engine.providers.backend_for("image")
    # every kind shares one mock instance in tests, so filter to image submits
    def image_submits():
        return [c for c in backend.calls
                if c["op"] == "submit" and c["kind"] == "image"]
    before = len(image_submits())

    job = engine.revise(job, "plates", "make her sit down", scenes=[1])
    after = image_submits()
    assert len(after) - before == 1, "expected exactly one plate to be re-bought"
    assert "make her sit down" in after[-1]["prompt"]
    assert "REVISION NOTE" in after[-1]["prompt"]
    scoped = [e for e in job.events if e["type"] == "revision_scope"]
    assert scoped and scoped[-1]["data"]["scenes"] == [1]


def test_a_revision_without_scenes_still_redoes_nothing_already_approved(home, reference):
    _cfg, _store, engine, job = setup(home, reference, scenes=2)
    job = engine.approve(engine.run(job))
    backend = engine.providers.backend_for("image")
    n = lambda: len([c for c in backend.calls
                     if c["op"] == "submit" and c["kind"] == "image"])
    before = n()
    job = engine.revise(job, "plates", "warmer light")
    assert n() == before


def test_a_consumed_revision_is_not_applied_twice(home, reference):
    """Re-running the stage must not re-buy the same scene again."""
    _cfg, store, engine, job = setup(home, reference, scenes=2)
    job = engine.approve(engine.run(job))
    job = engine.revise(job, "plates", "sitting", scenes=[0])
    backend = engine.providers.backend_for("image")
    n = lambda: len([c for c in backend.calls
                     if c["op"] == "submit" and c["kind"] == "image"])
    count = n()
    from fjor_studio.stages import steps
    steps.plates(engine._ctx(store.load(job.id)))
    assert n() == count


# -- subtitle prerequisites are checked before anything is paid for ----------

def test_missing_transcription_key_fails_at_intake_not_after_the_spend(home, reference):
    """Subtitles are burned in assembly, which runs after the clips are bought.
    A missing key discovered there fails a job that has spent its whole budget."""
    _cfg, store, engine, job = setup(home, reference, scenes=2,
                                     pipeline={"subtitles": {"enabled": True}})
    job = engine.run(job)
    assert job.state == "failed"
    assert "openai.api_key" in job.error
    backend = engine.providers.backend_for("image")
    assert [c for c in backend.calls if c["kind"] == "image"] == []


def test_a_missing_subtitle_font_is_caught_at_intake(home, reference, tmp_path):
    empty = tmp_path / "empty_assets"
    (empty / "fonts").mkdir(parents=True)
    write_config(home, pipeline={"subtitles": {"enabled": True}})
    import yaml
    cfg_file = home / "config" / "delivery.yaml"
    data = yaml.safe_load(cfg_file.read_text())
    data["assets_dir"] = str(empty)
    cfg_file.write_text(yaml.safe_dump(data))
    write_replies(home, analysis="a", text=scene_plan(1))
    (home / "config" / "auth.yaml").write_text(
        yaml.safe_dump({"openai": {"api_key": "sk-test"},
                        "mock": {"replies": {"analysis": "a",
                                             "text": scene_plan(1)}}}))
    cfg, store, engine = open_studio(home)
    job = make_job(store, reference, scenes=1, config=cfg)
    job = engine.run(job)
    assert job.state == "failed"
    assert "no font file" in job.error


# -- the plan cannot carry a duration the video model refuses ----------------

def test_short_scenes_are_clamped_where_the_plan_is_read():
    """LIPIL050: the writer returned 2s, 1s and 2s shots and the job died inside
    `clips`, after five plates had been paid for. A model instruction is a
    request; the provider's 4-15s floor is a fact."""
    from fjor_studio.stages.steps import _parse_scene_plan
    plan = json.dumps({"scenes": [
        {"idx": 0, "image_prompt": "a", "video_prompt": "b", "duration_s": 4},
        {"idx": 1, "image_prompt": "a", "video_prompt": "b", "duration_s": 2},
        {"idx": 2, "image_prompt": "a", "video_prompt": "b", "duration_s": 1},
    ]})
    scenes, notes = _parse_scene_plan(plan, 3, (4.0, 15.0))
    assert [s["duration_s"] for s in scenes] == [4.0, 4.0, 4.0]
    assert len(notes) == 2 and "below the 4.0s floor" in notes[0]


def test_long_scenes_are_clamped_too():
    from fjor_studio.stages.steps import _parse_scene_plan
    plan = json.dumps({"scenes": [{"idx": 0, "image_prompt": "a",
                                   "video_prompt": "b", "duration_s": 40}]})
    scenes, notes = _parse_scene_plan(plan, 1, (4.0, 15.0))
    assert scenes[0]["duration_s"] == 15.0
    assert "over the 15.0s ceiling" in notes[0]


def test_a_non_numeric_duration_does_not_crash_the_plan():
    from fjor_studio.stages.steps import _parse_scene_plan
    plan = json.dumps({"scenes": [{"idx": 0, "image_prompt": "a",
                                   "video_prompt": "b", "duration_s": "quick"}]})
    scenes, notes = _parse_scene_plan(plan, 1, (4.0, 15.0))
    assert scenes[0]["duration_s"] == 4.0
    assert "not a number" in notes[0]


def test_a_clamp_is_recorded_on_the_job_not_applied_silently(home, reference):
    """Stretching a 1s cut to 4s changes the pacing the writer intended, so it
    has to be visible in the job's history."""
    short = json.dumps({"scenes": [
        {"idx": 0, "image_prompt": "p0", "video_prompt": "m0", "duration_s": 2},
        {"idx": 1, "image_prompt": "p1", "video_prompt": "m1", "duration_s": 9}]})
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed", text=short,
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    job = make_job(store, reference, scenes=2, config=cfg)
    job = engine.run(job)
    assert [s["duration_s"] for s in job.scenes] == [4.0, 9.0]
    adjusted = [e for e in job.events if e["type"] == "plan_adjusted"]
    assert len(adjusted) == 1 and "scene 0" in adjusted[0]["msg"]


def test_every_planned_duration_is_one_kie_would_accept(home, reference):
    """The end-to-end guarantee: whatever the writer says, nothing illegal
    reaches the stage that pays."""
    from fjor_studio.gen.kie import DURATION_MAX, DURATION_MIN, KieBackend
    wild = json.dumps({"scenes": [
        {"idx": i, "image_prompt": "p", "video_prompt": "m", "duration_s": d}
        for i, d in enumerate([0.5, 2, 4, 15, 30, 99])]})
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="a", text=wild,
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    job = engine.run(make_job(store, reference, scenes=6, config=cfg))
    kie = KieBackend({"api_key": "x"})
    for s in job.scenes:
        assert DURATION_MIN <= s["duration_s"] <= DURATION_MAX
        # and KIE itself accepts every one of them
        kie.build_input("bytedance/seedance-2-fast", "p",
                        {"duration": s["duration_s"]})


def test_a_prompts_revision_note_reaches_the_writer(home, reference):
    """It was recorded and ignored, so a producer rewrote the plan and got the
    same plan back."""
    _cfg, _store, engine, job = setup(home, reference, scenes=2)
    job = engine.run(job)
    assert job.state == "GATE_PLAN"
    backend = engine.providers.backend_for("text")
    job = engine.revise(job, "prompts", "make the hook about joint pain")
    texts = [c["prompt"] for c in backend.calls
             if c["op"] == "submit" and c["kind"] == "text"]
    assert any("make the hook about joint pain" in t for t in texts), \
        "the reason the plan was sent back never reached the writer"


def test_a_consumed_prompts_revision_is_not_applied_twice(home, reference):
    _cfg, store, engine, job = setup(home, reference, scenes=2)
    job = engine.revise(engine.run(job), "prompts", "different angle")
    backend = engine.providers.backend_for("text")
    count = len([c for c in backend.calls
                 if c["op"] == "submit" and c["kind"] == "text"])
    from fjor_studio.stages import steps
    steps.prompts(engine._ctx(store.load(job.id)))
    texts = [c["prompt"] for c in backend.calls
             if c["op"] == "submit" and c["kind"] == "text"]
    assert len(texts) == count + 1
    assert "different angle" not in texts[-1]


# -- shipping a known defect on purpose --------------------------------------

def test_a_waived_scene_delivers_and_the_defect_travels_with_it(home, reference):
    """Sometimes a re-buy costs more than the flaw does, and that is the
    producer's call. What must not happen is the finding disappearing: turning
    QA off or editing the verdict would deliver a creative that looks clean to
    whoever opens the folder next year."""
    _cfg, store, engine, job = setup(home, reference, scenes=1,
                                     clip_qa=qa_critical())
    job = engine.approve(engine.approve(engine.approve(engine.run(job))))
    assert job.state == "failed"

    job = engine.waive(job, [0], "a swoosh nobody will see at 9:16; ships")
    job = engine.retry(job)
    assert job.state == "done"

    # the verdict is untouched -- it was accepted, not deleted
    assert job.scenes[0]["clip_qa"]["severity"] == "critical"
    report = json.loads((store.job_dir(job.id) / "review" / "preflight.json").read_text())
    qa = [c for c in report["checks"] if c["name"] == "clip QA"][0]
    assert "blocking: [0]" in qa["detail"]
    assert "WAIVED" in qa["detail"] and "ships" in qa["detail"]
    manifest = json.loads(
        (store.job_dir(job.id) / "finals" / "build_manifest.json").read_text())
    assert manifest["waived_clip_qa"] == [0]
    assert "swoosh" in manifest["waiver_note"]
    assert any(e["type"] == "qa_waived" for e in job.events)


def test_a_waiver_is_per_scene_and_needs_a_reason(home, reference):
    _cfg, _store, engine, job = setup(home, reference, scenes=1,
                                      clip_qa=qa_critical())
    job = engine.approve(engine.approve(engine.approve(engine.run(job))))
    with pytest.raises(TransitionError):
        engine.waive(job, [], "everything is fine")      # no blanket waiver
    with pytest.raises(TransitionError):
        engine.waive(job, [0], "   ")                    # no silent waiver
    with pytest.raises(TransitionError):
        engine.waive(job, [1], "not blocking")           # nothing to accept
    assert not job.meta.get("waived_clip_qa")


def test_waiving_one_scene_does_not_release_another(home, reference):
    _cfg, _store, engine, job = setup(home, reference, scenes=2,
                                      clip_qa=qa_critical())
    job = engine.approve(engine.approve(engine.approve(engine.run(job))))
    job = engine.waive(job, [0], "accepted on 0 only")
    job = engine.retry(job)
    assert job.state == "failed"                          # 1 still blocks
    assert "blocking: [0, 1]" in job.error
