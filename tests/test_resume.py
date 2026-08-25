"""Crash recovery around a paid generation.

KIE has no cancel endpoint: once `createTask` returns a taskId the credits are
committed. So the only acceptable behaviour after a crash mid-generation is to
COLLECT that task, never to submit a second one.
"""
import json

import pytest

from conftest import make_job, scene_plan, write_config, write_replies
from fjor_studio.app import open_studio
from fjor_studio.gen.base import ProviderBusy


def _setup(home, reference, scenes=1):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, text=scene_plan(scenes), analysis="analysed",
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    return cfg, store, engine, make_job(store, reference, scenes=scenes, config=cfg)


def _video_backend(engine):
    return engine.providers.backend_for("video")


def test_a_crash_after_submit_leaves_the_task_id_on_disk(home, reference):
    _cfg, store, engine, job = _setup(home, reference)
    job = engine.run(job)              # GATE_PLAN is skipped, plates are bought
    assert job.state == "GATE_PLATES"

    backend = _video_backend(engine)
    original_poll = backend.poll
    backend.poll = lambda *a, **k: (_ for _ in ()).throw(ProviderBusy("network died"))

    job = engine.approve(job)
    assert job.state == "failed"

    # the id we already paid for survived the crash
    on_disk = store.load(job.id)
    open_subs = on_disk.open_submissions()
    assert len(open_subs) == 1
    assert open_subs[0]["kind"] == "video"
    crashed_task = open_subs[0]["task_id"]

    # and the retry collects it instead of buying another
    backend.poll = original_poll
    submits_before = len([c for c in backend.calls
                          if c["op"] == "submit" and c["kind"] == "video"])
    job = engine.retry(store.load(job.id))
    submits_after = len([c for c in backend.calls
                         if c["op"] == "submit" and c["kind"] == "video"])
    assert submits_after == submits_before, "the retry re-bought a paid generation"
    assert job.scenes[0]["clip"]
    video_subs = [s for s in job.scenes[0]["submissions"] if s["kind"] == "video"]
    assert [s["task_id"] for s in video_subs] == [crashed_task]
    assert video_subs[0]["status"] == "completed"
    assert "collecting" in [e["type"] for e in job.events]


def test_the_ledger_charges_the_collected_task_exactly_once(home, reference):
    _cfg, store, engine, job = _setup(home, reference)
    job = engine.run(job)
    backend = _video_backend(engine)
    original_poll = backend.poll
    backend.poll = lambda *a, **k: (_ for _ in ()).throw(ProviderBusy("boom"))
    job = engine.approve(job)
    backend.poll = original_poll
    job = engine.retry(store.load(job.id))
    clip_lines = [e for e in job.ledger if e["stage"] == "clips"]
    assert len(clip_lines) == 1
    assert clip_lines[0]["credits"] == pytest.approx(124.0)


def test_rerunning_a_finished_stage_does_not_re_buy(home, reference):
    """A stage interrupted later must not redo work already on disk."""
    _cfg, store, engine, job = _setup(home, reference, scenes=2)
    job = engine.approve(engine.run(job))
    assert job.state == "GATE_DRAFT"
    backend = _video_backend(engine)
    submits = len([c for c in backend.calls if c["op"] == "submit"])
    from fjor_studio.stages import steps
    steps.clips(engine._ctx(job))              # run the stage again, directly
    assert len([c for c in backend.calls if c["op"] == "submit"]) == submits


def test_cancel_names_the_spend_it_cannot_stop(home, reference):
    """Reporting "cancelled" while paid tasks are still running would be a lie."""
    _cfg, store, engine, job = _setup(home, reference)
    job = engine.run(job)
    backend = _video_backend(engine)
    backend.poll = lambda *a, **k: (_ for _ in ()).throw(ProviderBusy("boom"))
    job = engine.approve(job)
    assert job.state == "failed"
    job = engine.cancel(store.load(job.id), "producer changed their mind")
    assert job.state == "cancelled"
    warned = [e for e in job.events if e["type"] == "cancel_with_open_spend"]
    assert len(warned) == 1
    assert warned[0]["data"]["task_ids"]


def test_a_moderation_refusal_fails_the_job_rather_than_retrying(home, reference):
    """A retry of the same prompt costs money and fails the same way."""
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed",
                  text=json.dumps({"scenes": [
                      {"idx": 0, "image_prompt": "plate __moderation__",
                       "video_prompt": "motion 0", "duration_s": 5}]}))
    cfg, store, engine = open_studio(home)
    job = make_job(store, reference, scenes=1, config=cfg)
    job = engine.run(job)
    assert job.state == "failed"
    assert "moderation" in job.error.lower()
    assert store.load(job.id).scenes[0]["submissions"] == []


def test_a_refused_generation_is_recorded_as_failed_not_still_running(home, reference):
    """It was left "submitted", so find_existing collected it on every retry and
    the job could never get past a refused generation -- it re-polled a corpse
    forever."""
    _cfg, store, engine, job = _setup(home, reference)
    job = engine.run(job)
    backend = _video_backend(engine)
    from fjor_studio.gen.base import GenError
    backend.poll = lambda *a, **k: (_ for _ in ()).throw(GenError("refused by the provider"))
    job = engine.approve(job)
    assert job.state == "failed"

    subs = [s for s in store.load(job.id).scenes[0]["submissions"]
            if s["kind"] == "video"]
    assert subs[-1]["status"] == "failed"
    assert store.load(job.id).open_submissions() == []


def test_a_retry_after_a_refusal_buys_a_new_generation(home, reference):
    """Nothing was produced, so there is nothing to collect -- the only way to
    a clip is another submission."""
    _cfg, store, engine, job = _setup(home, reference)
    job = engine.run(job)
    backend = _video_backend(engine)
    original = backend.poll
    from fjor_studio.gen.base import GenError
    backend.poll = lambda *a, **k: (_ for _ in ()).throw(GenError("refused"))
    job = engine.approve(job)
    backend.poll = original
    before = len([c for c in backend.calls
                  if c["op"] == "submit" and c["kind"] == "video"])
    job = engine.retry(store.load(job.id))
    after = len([c for c in backend.calls
                 if c["op"] == "submit" and c["kind"] == "video"])
    assert after == before + 1
    assert job.scenes[0]["clip"]


def test_a_timeout_is_still_treated_as_collectable(home, reference):
    """The distinction that matters: busy means alive, an error means finished
    and refused."""
    _cfg, store, engine, job = _setup(home, reference)
    job = engine.run(job)
    backend = _video_backend(engine)
    backend.poll = lambda *a, **k: (_ for _ in ()).throw(ProviderBusy("still going"))
    job = engine.approve(job)
    assert job.state == "failed"
    assert len(store.load(job.id).open_submissions()) == 1
