"""What a producer can now do by hand from the dashboard: register a vertical,
rewrite a prompt, regenerate a shot from its card, and reopen a finished cut."""
import json

import pytest

from conftest import make_job, scene_plan, write_config, write_replies
from fjor_studio.app import open_studio
from fjor_studio.engine import TransitionError
from test_dashboard import _finish, get, live, wait  # noqa: F401


def post(url, payload=None):
    """Like test_dashboard's, but a refusal comes back as (status, body)
    rather than raising -- half of what is checked here is the refusal."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(
        url, data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def qa_ok():
    return json.dumps({"passed": True, "severity": "ok", "issues": []})


def setup(home, reference, scenes=2):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed", text=scene_plan(scenes),
                  **{"qa:plate": qa_ok(), "qa:clip": qa_ok()})
    cfg, store, engine = open_studio(home)
    return cfg, store, engine, make_job(store, reference, scenes=scenes, config=cfg,
                                        packshot="formula")


# -- a vertical that is not in the list yet -----------------------------------

def test_a_vertical_added_from_the_dashboard_is_registered_and_usable(live, reference):
    base, _studio, _store, _job = live
    cfg_file = _store.root.parent / "config" / "verticals.yaml"
    cfg_file.write_text("# keep this note\n" + cfg_file.read_text())

    status, body = post(f"{base}/api/verticals",
                        {"name": "Strong Legs", "prefix": "sl", "folder": "STRONG LEGS"})
    assert status == 200 and body == {"name": "strong_legs", "prefix": "SL",
                                      "folder": "STRONG LEGS"}
    opts = get(f"{base}/api/state")[1]["options"]
    assert "strong_legs" in opts["verticals"]
    assert opts["prefix_map"]["SL"] == "strong_legs"
    text = cfg_file.read_text()
    assert text.startswith("# keep this note"), "appended as text, comments kept"

    # a pasted name with the new prefix now places itself
    status, body = post(f"{base}/api/jobs", {
        "creative_name": "n-SL001_ch-fb_t-video_c-ugc_pr-lp_ds-nano_w-34_s-1080x1920",
        "reference": str(reference)})
    assert status == 200 and body["id"] == "SL001"
    d = get(f"{base}/api/jobs/SL001")[1]
    assert d["intake"]["vertical"] == "strong_legs"
    assert d["intake"]["folder"] == "STRONG LEGS"


def test_a_vertical_that_collides_or_is_malformed_is_refused(live):
    base, *_ = live
    for form, why in [
        ({"name": "yoga", "prefix": "ZZ", "folder": "Z"}, "already a vertical"),
        ({"name": "yoga_two", "prefix": "Y", "folder": "YOGA TWO"}, "prefix Y already"),
        ({"name": "yoga_two", "prefix": "YT", "folder": "yoga"}, "folder 'yoga' already"),
        ({"name": "!!!", "prefix": "BN", "folder": "BAD"}, "lowercase"),
        ({"name": "fine", "prefix": "TOOLONG", "folder": "FINE"}, "1-5 capital"),
        ({"name": "fine", "prefix": "F", "folder": "../up"}, "single folder"),
        ({"name": "fine", "prefix": "F", "folder": ""}, "single folder"),
    ]:
        status, body = post(f"{base}/api/verticals", form)
        assert status == 400 and why in body["error"], (form, body)
    assert "fine" not in get(f"{base}/api/state")[1]["options"]["verticals"]


# -- prompts rewritten by hand ------------------------------------------------

def test_a_prompt_edited_by_hand_is_what_the_regeneration_buys(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.run(job)
    assert job.state == "GATE_PLATES"
    backend = engine.providers.backend_for("image")
    before = len([c for c in backend.calls if c["op"] == "submit" and c["kind"] == "image"])

    job = engine.set_prompt(job, 0, {"image_prompt": "she stands at the window"})
    assert job.scenes[0]["image_prompt"] == "she stands at the window"
    assert job.scenes[0]["plate"], "editing the words does not throw the plate away"
    ev = [e for e in job.events if e["type"] == "prompt_edited"]
    assert ev and ev[-1]["data"] == {"scene": 0, "fields": ["image_prompt"]}

    job = engine.revise(job, "plates", "", scenes=[0])
    submits = [c for c in backend.calls if c["op"] == "submit" and c["kind"] == "image"]
    assert len(submits) - before == 1
    assert "she stands at the window" in submits[-1]["prompt"]
    assert "plate 0" not in submits[-1]["prompt"]
    assert job.state == "GATE_PLATES"


def test_a_prompt_edit_is_refused_off_a_gate_and_for_the_wrong_things(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    with pytest.raises(TransitionError, match="not at a gate"):
        engine.set_prompt(job, 0, {"image_prompt": "x"})
    job = engine.run(job)
    with pytest.raises(TransitionError, match="unknown field"):
        engine.set_prompt(job, 0, {"line": "hello"})
    with pytest.raises(TransitionError, match="cannot be empty"):
        engine.set_prompt(job, 0, {"video_prompt": "  "})
    with pytest.raises(TransitionError, match="does not transform"):
        engine.set_prompt(job, 0, {"end_image_prompt": "after"})
    with pytest.raises(TransitionError, match="no scene 7"):
        engine.set_prompt(job, 7, {"image_prompt": "x"})
    with pytest.raises(TransitionError, match="nothing changed"):
        engine.set_prompt(job, 0, {"image_prompt": "plate 0"})


def test_a_prompt_is_edited_over_http(live):
    base, studio, _store, job = live
    post(f"{base}/api/jobs/{job.id}/run"); wait(studio, job.id)
    status, body = post(f"{base}/api/jobs/{job.id}/prompt",
                        {"scene": 1, "fields": {"video_prompt": "she turns to camera"}})
    assert status == 200 and body["queued"] == "prompt"
    wait(studio, job.id)
    d = get(f"{base}/api/jobs/{job.id}")[1]
    assert d["scenes"][1]["video_prompt"] == "she turns to camera"
    assert d["state"] == "GATE_PLATES" and d["spent"] > 0


# -- a finished cut, reopened -------------------------------------------------

def test_a_finished_job_is_reopened_at_the_cut_and_redelivered_over_the_old_files(live):
    base, studio, _store, job = live
    d = _finish(base, studio, job.id)
    delivered = [p.split("/")[-1] for p in d["meta"]["delivered_to"]]
    assert delivered

    status, body = post(f"{base}/api/jobs/{job.id}/reopen")
    assert status == 200 and body["queued"] == "reopen"
    wait(studio, job.id)
    d = get(f"{base}/api/jobs/{job.id}")[1]
    assert d["state"] == "GATE_DRAFT" and d["gate_ready"]
    assert d["edit"]["open"], "the editor is back"
    assert "plates" in d["revisable"] and "clips" in d["revisable"]
    assert any(e["type"] == "reopened" for e in d["events"])

    post(f"{base}/api/jobs/{job.id}/approve"); wait(studio, job.id, seconds=180)
    d = get(f"{base}/api/jobs/{job.id}")[1]
    assert d["state"] == "done", d.get("error")
    assert [p.split("/")[-1] for p in d["meta"]["delivered_to"]] == delivered
    replaced = d["meta"].get("replaced") or []
    assert len(replaced) == len(delivered)
    assert all("_to_delete" in p for p in replaced)


def test_only_a_finished_job_is_reopened(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    with pytest.raises(TransitionError, match="only a finished job"):
        engine.reopen(job)
    job = engine.run(job)
    with pytest.raises(TransitionError, match="only a finished job"):
        engine.reopen(job)


# -- the page -----------------------------------------------------------------

def test_the_page_carries_the_new_controls():
    from fjor_studio.dashboard.page import PAGE
    for needle in ("function openRevise(what,scene)", "openRevise('${target}',${s.idx})",
                   "keepClip(", "reopenCut()", "savePrompt(", "toggleBed(",
                   "openLibrary", "/api/verticals", "libSelect(", "setEdit('hook'"):
        assert needle in PAGE.replace("\\'", "'"), needle
