"""Banner mode as a pipeline: what four stages do differently, and what three
of them skip.

The mock backend is told to ECHO the image it is given, which is what an
edit-in-place model does. That matters here more than anywhere else in the
suite: every check in this mode compares the result with its input, and a double
that hands back an unrelated picture could not fail one of them honestly.
"""
import json
from pathlib import Path

from conftest import a_banner, banner_answers, write_config, write_replies

from fjor_studio.app import new_job, open_studio


def to_gate(engine, job, gate):
    """Walk the pipeline, approving each gate, until `gate` or a stop."""
    job = engine.run(job)
    while job.state != gate and job.state.startswith("GATE_"):
        job = engine.run(engine.approve(job))
    return job


def submitted(engine, kind):
    """Every call of one kind. Every kind is routed to the same mock here, so
    the backend's own log is shared and has to be filtered by kind."""
    return [c for c in engine.providers.backend_for(kind).calls
            if c["op"] == "submit" and c["kind"] == kind]


def qa_systems(engine, kind=None):
    return [c["params"]["system"] for c in submitted(engine, "analysis")
            if c["params"].get("qa_kind")
            and (kind is None or c["params"]["qa_kind"] == kind)]


def banner_job(home, banner_path, echo=True, **intake):
    write_config(home)
    write_replies(home, echo_images=echo, text=banner_answers(),
                  **{"qa:plate": json.dumps({"verdict": "ok", "issues": []}),
                     "qa:clip": json.dumps({"verdict": "ok", "issues": []})})
    cfg, store, engine = open_studio(home)
    payload = {"banner": str(banner_path), "week": 34, "concept": "banner",
               "producer": "lp"}
    payload.update(intake)
    job = new_job(store, cfg, "lipedema_pilates", payload)
    return cfg, store, engine, job


# -- which pipeline is this? -------------------------------------------------

def test_a_job_with_both_a_banner_and_a_reference_is_refused(tmp_path, home):
    """Two different pipelines. Their tool announces which one is about to run,
    because mixing them wastes a whole generation; ours refuses the ambiguity."""
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job.intake["reference"] = str(tmp_path / "ref.mp4")
    store.save(job)
    job = engine.run(job)
    assert job.state == "failed"
    assert "two different pipelines" in json.dumps(job.events)


def test_a_video_handed_in_as_a_banner_is_refused(tmp_path):
    home = tmp_path / "h"
    ref = tmp_path / "clip.mp4"
    ref.write_bytes(b"NOT AN IMAGE")
    cfg, store, engine, job = banner_job(home, ref)
    job = engine.run(job)
    assert job.state == "failed"
    assert "must be an image" in json.dumps(job.events)


# -- intake ------------------------------------------------------------------

def test_intake_settles_the_geometry_before_the_gate(tmp_path):
    """Whether there is anything to expand decides what the job costs. Finding
    that out after the gate is finding it out too late."""
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job = to_gate(engine, job, "GATE_PLAN")
    state = job.meta["banner"]
    assert (state["width"], state["height"]) == (1080, 1080)
    assert state["needs_expansion"] is True
    assert state["placement"]["top"] == state["placement"]["bottom"] == 420


def test_a_banner_already_vertical_is_never_expanded(tmp_path):
    cfg, store, engine, job = banner_job(tmp_path / "h",
                             a_banner(tmp_path / "b.png", 1080, 1920))
    job = to_gate(engine, job, "GATE_PLATES")
    assert job.meta["banner"]["needs_expansion"] is False
    # no canvas was built, and no expansion was bought
    assert len(submitted(engine, "image")) == 1              # the small-print pass only


# -- what the mode skips -----------------------------------------------------

def test_the_reference_analysis_is_skipped_entirely(tmp_path):
    """Their v4 keeps the video instruction, the niche and the voice out of this
    mode on purpose: none of them describes a banner, and each competes with the
    one asset that does."""
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job = to_gate(engine, job, "GATE_PLAN")
    assert job.analysis.get("skipped") == "banner mode"
    assert not [c for c in submitted(engine, "analysis")
                if not c["params"].get("qa_kind")]
    assert any(e["type"] == "analysis_skipped" for e in job.events)


def test_subtitles_are_off_because_the_clip_is_silent(tmp_path):
    """Burning subtitles over a banner would also cover the client's own
    approved copy, which is the whole creative."""
    home = tmp_path / "h"
    cfg, store, engine, job = banner_job(home, a_banner(tmp_path / "b.png"))
    write_config(home, pipeline={"subtitles": {"enabled": True}})
    cfg, store, engine = open_studio(home)
    job = store.load(job.id)
    from fjor_studio.engine.engine import StageContext
    from fjor_studio.stages.steps import _subtitle_settings
    ctx = StageContext(job=job, config=cfg, store=store,
                       providers=engine.providers,
                       job_dir=store.job_dir(job.id))
    assert _subtitle_settings(ctx) == (None, False)


def test_no_voiceover_is_spoken(tmp_path):
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job = to_gate(engine, job, "GATE_DRAFT")
    assert not submitted(engine, "speech")
    assert job.scenes[0]["voice"] == "vo" and not job.scenes[0]["line"]


# -- the plan ----------------------------------------------------------------

def test_the_canvas_is_sent_a_short_instruction_that_describes_no_scene(tmp_path):
    """AW025, 2026-09-01: the four-question playbook was assembled into 2,361
    characters of scene description and sent WITH the canvas. An editing model
    handed a description of a scene draws the scene, and both attempts came back
    with the banner's photograph replaced. The playbook belongs to the
    bare-image engine; the canvas gets a short fixed fill instruction."""
    from fjor_studio.banner import MARKER, check_prompt, fill_prompt
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job = to_gate(engine, job, "GATE_PLAN")
    sent = job.scenes[0]["image_prompt"]
    assert sent == fill_prompt()
    assert len(sent) < 900
    assert "magenta" in sent
    # nothing about what is IN the banner: no quoted copy, no sky, no water
    for leak in ("LOSE THE SWELLING", "GET THE PLAN", "EXTEND", "above --"):
        assert leak not in sent
    # and the fixed prompt obeys the rule the playbook enforces on written ones
    assert check_prompt(sent)["ok"] is True


def test_the_animation_prompt_is_still_assembled_from_the_answers(tmp_path):
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job = to_gate(engine, job, "GATE_PLAN")
    scene = job.scenes[0]
    assert "pixel-locked" in scene["video_prompt"]     # inserted, not asked for
    assert "steam" in scene["video_prompt"]            # the writer's own answer
    assert scene["duration_s"] == 7.0


def test_a_brief_edit_is_refused_out_loud_rather_than_dropped(tmp_path):
    """An edit inside the banner would be painted by the expansion and then
    overwritten when the original is re-composited. A brief silently not applied
    is worse than one refused."""
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"),
                                         brief="the date is now 24 August")
    job = to_gate(engine, job, "GATE_PLAN")
    assert any(e["type"] == "banner_brief_ignored" for e in job.events)


# -- the expansion -----------------------------------------------------------

def test_the_expanded_frame_becomes_the_plate_and_the_banner_survived(tmp_path):
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job = to_gate(engine, job, "GATE_PLATES")
    assert job.state == "GATE_PLATES"
    assert (store.job_dir(job.id) / job.scenes[0]["plate"]).exists()
    survived = job.meta["banner"]["survived"]
    assert survived["intact"] is True and survived["changed_pixels"] == 0


def test_an_expansion_that_redrew_the_banner_is_refused(tmp_path):
    """Everything printed on it was approved by a client, so shipping a redrawn
    one is worse than shipping nothing. The mock is left returning its own
    prototype here -- a picture that is not the banner at all."""
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"),
                             echo=False)
    job = to_gate(engine, job, "GATE_PLATES")
    assert job.state == "failed"
    events = json.dumps(job.events)
    assert "banner_redrawn" in events
    assert "approved by a client" in events


def test_the_small_print_pass_reports_when_it_changed_nothing(tmp_path):
    """A skipped pass is otherwise identical to a clean one, which is how it
    reaches delivery. The echoing mock changes nothing, so it must say so."""
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job = to_gate(engine, job, "GATE_PLATES")
    assert any(e["type"] == "banner_small_print" for e in job.events)


def test_the_forecast_counts_the_small_print_pass(tmp_path):
    """One scene, but two certain image buys. Retries are conditional and said
    out loud rather than priced."""
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job = to_gate(engine, job, "GATE_PLAN")
    assert len(job.forecasts["plates"]["items"]) == 2
    assert any(e["type"] == "banner_forecast" for e in job.events)


# -- QA ----------------------------------------------------------------------

def test_qa_is_told_the_burnt_in_text_is_intended(tmp_path):
    """Our normal media QA calls readable text in frame a critical defect, which
    would fail every banner ever made."""
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    to_gate(engine, job, "GATE_PLATES")
    systems = qa_systems(engine)
    assert systems, "no plate QA ran"
    for system in systems:
        assert "INTENDED" in system
        assert "NO TEXT" not in system


def test_the_clip_qa_asks_whether_anything_moves_in_the_middle(tmp_path):
    """The 4:5 final is cropped from there and ships as its own deliverable."""
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    to_gate(engine, job, "GATE_DRAFT")
    systems = qa_systems(engine, "clip")
    assert systems and "MIDDLE of the frame" in systems[0]


# -- the CLI -----------------------------------------------------------------

def test_the_cli_routes_an_image_to_banner_mode_and_a_video_to_the_reference(tmp_path):
    """One positional, two pipelines. The producer types the path they have."""
    from fjor_studio.cli import main
    from fjor_studio.engine.store import JobStore

    home = tmp_path / "h"
    banner = a_banner(tmp_path / "b.png")
    video = tmp_path / "ref.mp4"
    video.write_bytes(b"REFERENCE VIDEO BYTES")
    write_config(home)
    write_replies(home, echo_images=True, text=banner_answers())

    for source, expect in ((banner, "banner"), (video, "reference")):
        assert main(["--home", str(home), "new", "lipedema_pilates", str(source),
                     "--week", "34", "--concept", "banner"]) == 0
    ids = sorted(JobStore(home / "jobs").list_ids())
    intakes = [JobStore(home / "jobs").load(i).intake for i in ids]
    assert sorted(k for i in intakes for k in i
                  if k in ("banner", "reference")) == ["banner", "reference"]


def test_a_revision_at_the_plate_gate_really_re_expands(tmp_path):
    """Without this the finished plate is skipped as already-made and the
    producer's request does nothing -- a flag the CLI accepts and no stage
    honours."""
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job = to_gate(engine, job, "GATE_PLATES")
    before = len(submitted(engine, "image"))
    job = engine.run(engine.revise(job, "plates", scenes=[0],
                                   note="more room above the headline"))
    after = submitted(engine, "image")
    assert len(after) > before
    assert "more room above the headline" in after[before]["prompt"]


def test_the_expansion_is_bought_at_2k(tmp_path):
    """At 1K this model answers a 1080x1920 canvas with a 768-wide frame, and
    the final is exported 1080 wide. Their notes price Banana Pro at "$0.09 for
    1-2K", so the wider frame is the same money."""
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    to_gate(engine, job, "GATE_PLATES")
    expansions = [c for c in submitted(engine, "image")
                  if "magenta" in (c["prompt"] or "")]
    assert expansions and expansions[0]["params"]["resolution"] == "2K"


def test_a_retry_sends_the_current_prompt_not_the_one_stored_on_the_job(tmp_path):
    """AW025 stored its fill instruction on the job at plan time. When the
    prompt was fixed, a retry was still about to re-send the very text that
    caused the failure. A constant belongs in the module, not in job.json."""
    from fjor_studio.banner import fill_prompt
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job = to_gate(engine, job, "GATE_PLAN")
    stale = "PAINT WHATEVER YOU LIKE, describing the whole scene at length"
    job.meta["banner"]["expansion_prompt"] = stale
    scene = job.scene(0); scene.image_prompt = stale; job.put_scene(scene)
    store.save(job)
    job = to_gate(engine, store.load(job.id), "GATE_PLATES")
    sent = [c["prompt"] for c in submitted(engine, "image")]
    assert stale not in sent
    assert fill_prompt() in sent
    assert job.scenes[0]["image_prompt"] == fill_prompt()   # and the page agrees


def test_an_expansion_already_paid_for_is_not_bought_again(tmp_path):
    """AW025's first retry re-bought an expansion that had already passed the
    model's half and only fell over on our own arithmetic. Every other stage
    re-runs over work on disk without paying twice; so does this one."""
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job = to_gate(engine, job, "GATE_PLATES")
    bought = len(submitted(engine, "image"))
    # a re-run of the stage, with the finished plate cleared as a failure leaves it
    scene = job.scene(0); scene.plate = None; job.put_scene(scene)
    job.state = "plates"; job.gate_ready = False; store.save(job)
    job = to_gate(engine, store.load(job.id), "GATE_PLATES")
    again = submitted(engine, "image")
    assert len(again) == bought + 1          # the small-print pass only
    assert not [c for c in again[bought:] if "magenta" in (c["prompt"] or "")]
    assert any(e["type"] == "collecting" for e in job.events)


# The size a real nano-banana-pro answers a 1080x1920 canvas with, at 2K.
# Measured on AW025, not chosen: 768x1376 at 1K, exactly double at 2K.
PROVIDER_BUCKET = (1536, 2752)


def test_the_whole_stage_survives_a_provider_that_answers_in_its_own_size(tmp_path):
    """Two paid failures came of this. The double answered in the exact size it
    was handed, so no test ever ran the STAGE against a provider that does what
    every real one does."""
    home = tmp_path / "h"
    write_config(home)
    write_replies(home, echo_images=True, echo_size=PROVIDER_BUCKET,
                  text=banner_answers(),
                  **{"qa:plate": json.dumps({"verdict": "ok", "issues": []}),
                     "qa:clip": json.dumps({"verdict": "ok", "issues": []})})
    cfg, store, engine = open_studio(home)
    job = new_job(store, cfg, "lipedema_pilates",
                  {"banner": str(a_banner(tmp_path / "b.png")), "week": 34,
                   "concept": "banner", "producer": "lp"})
    job = to_gate(engine, job, "GATE_PLATES")
    assert job.state == "GATE_PLATES", job.error
    survived = job.meta["banner"]["survived"]
    assert survived["intact"] is True and survived["changed_pixels"] == 0
    assert (store.job_dir(job.id) / job.scenes[0]["plate"]).exists()


def test_a_thumbnail_is_refused_before_anything_is_bought(tmp_path):
    """SL040 (2026-09-02): a 220x220 file named `..._s-1080x1080.jpg`. The name
    claimed the artwork and the file was a preview. It was enlarged 4.9x to fill
    the canvas, and every check downstream then preserved that blurry upscale
    pixel-perfectly and reported success."""
    cfg, store, engine, job = banner_job(tmp_path / "h",
                                         a_banner(tmp_path / "b.png", 220, 220))
    job = engine.run(job)
    assert job.state == "failed"
    events = json.dumps(job.events)
    assert "4.91x" in events and "thumbnail, not the artwork" in events
    assert job.spent == 0
    assert not submitted(engine, "image")


def test_a_modest_enlargement_is_allowed_and_said_out_loud(tmp_path):
    """A little softness is a judgement call, not a refusal -- but the producer
    should be told the number rather than discovering it in the plate."""
    cfg, store, engine, job = banner_job(tmp_path / "h",
                                         a_banner(tmp_path / "b.png", 540, 540))
    job = to_gate(engine, job, "GATE_PLAN")
    assert job.state == "GATE_PLAN"
    assert "enlarged 2.0x" in json.dumps(job.events)


def test_qa_judges_the_frame_that_ships(tmp_path):
    """SL040 again: QA read the model's RAW return, while the plate delivered is
    the one produced afterwards by re-compositing and removing the small print.
    It reported garbled footer text the re-composite had already repaired, and
    had never once seen the frame that gets animated."""
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job = to_gate(engine, job, "GATE_PLATES")
    plate = job.scenes[0]["plate"]
    judged = [c["medias"][0] for c in submitted(engine, "analysis")
              if c["params"].get("qa_kind") == "plate"]
    assert judged, "no plate QA ran"
    assert judged[-1].endswith(Path(plate).name), (
        f"QA looked at {judged[-1]}, the job ships {plate}")


# -- re-formatting, the other engine -----------------------------------------

def redraw_job(home, banner_path, **intake):
    intake.setdefault("banner_engine", "redraw")
    return banner_job(home, banner_path, **intake)


def test_a_redraw_sends_the_bare_banner_and_no_canvas(tmp_path):
    """Their tool moved to this after live tests: compositing 'don't touch the
    square' gave sharpness seams, picture-in-picture and duplicate faces
    (r146, 2026-08-16). SL040 reproduced all three."""
    cfg, store, engine, job = redraw_job(tmp_path / "h", a_banner(tmp_path / "b.png"))
    job = to_gate(engine, job, "GATE_PLATES")
    assert job.state == "GATE_PLATES", job.error
    calls = [c for c in submitted(engine, "image")]
    assert len(calls) == 1, "a redraw is ONE call: no canvas, no small-print pass"
    sent = calls[0]
    assert sent["medias"][0].endswith("b.png")        # the banner itself
    assert "magenta" not in sent["prompt"]            # there is no marker
    assert "LAYOUT LOCK" in sent["prompt"]
    assert sent["params"]["resolution"] == "2K"
    assert (store.job_dir(job.id) / job.scenes[0]["plate"]).exists()


def test_a_redraw_refuses_to_run_with_qa_switched_off(tmp_path):
    """A redraw leaves no original pixels, so nothing arithmetic can vouch for
    it. Running one with QA off would be a stage that cannot fail."""
    home = tmp_path / "h"
    cfg, store, engine, job = redraw_job(home, a_banner(tmp_path / "b.png"))
    write_config(home, pipeline={"qa": {"plates": {"enabled": False}}})
    cfg, store, engine = open_studio(home)
    job = to_gate(engine, store.load(job.id), "GATE_PLATES")
    assert job.state == "failed"
    assert "needs plate QA" in job.error


def test_the_brief_changes_the_visual_in_a_redraw_and_is_refused_on_a_canvas(tmp_path):
    """The honest split. A redraw regenerates the picture, so an edit is simply
    part of the instruction; on a canvas it would be painted and then overwritten
    when the original is re-composited back."""
    home = tmp_path / "h"
    write_config(home)
    write_replies(home, echo_images=True,
                  text=banner_answers(edits='replace "24 July" with "24 August"'),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    job = new_job(store, cfg, "lipedema_pilates",
                  {"banner": str(a_banner(tmp_path / "b.png")), "week": 34,
                   "concept": "banner", "producer": "lp",
                   "banner_engine": "redraw",
                   "brief": "change the date to 24 August"})
    job = to_gate(engine, job, "GATE_PLAN")
    # the producer's words reached the writer...
    asked = [c["prompt"] for c in submitted(engine, "text")][0]
    assert "change the date to 24 August" in asked
    # ...and the writer's edit reached the prompt that redraws the banner
    sent = job.scenes[0]["image_prompt"]
    assert "and only these" in sent and '"24 August"' in sent
    assert not [e for e in job.events if e["type"] == "banner_brief_ignored"]

    cfg2, store2, engine2, job2 = banner_job(tmp_path / "h2", a_banner(tmp_path / "b.png"),
                                             brief="change the date to 24 August")
    job2 = to_gate(engine2, job2, "GATE_PLAN")
    assert any(e["type"] == "banner_brief_ignored" for e in job2.events)


def test_an_unknown_engine_is_refused_by_name(tmp_path):
    cfg, store, engine, job = banner_job(tmp_path / "h", a_banner(tmp_path / "b.png"),
                                         banner_engine="outpaint")
    job = engine.run(job)
    assert job.state == "failed"
    assert "is not a banner engine" in job.error


def test_the_page_explains_which_guarantee_each_engine_gives():
    from fjor_studio.dashboard.page import PAGE
    for needle in ("How to reach 9:16", "zero changed pixels",
                   "QA is the only guard", "visual changes go", "f_bengine"):
        assert needle in PAGE, needle
