"""Character consistency: one portrait per person, attached everywhere."""
import json

import pytest

from conftest import make_job, write_config, write_replies
from fjor_studio.app import open_studio
from fjor_studio.engine import Character, Job, Scene
from fjor_studio.stages.steps import _parse_cast, _parse_scene_plan, _with_anchor


def plan_with_cast(scene_chars, cast=(("host", "late 30s, dark bob"),
                                      ("runner", "40s, blonde braid"))):
    return json.dumps({
        "cast": [{"id": i, "description": d} for i, d in cast],
        "scenes": [{"idx": n, "characters": list(cs), "image_prompt": f"p{n}",
                    "video_prompt": f"m{n}", "duration_s": 5}
                   for n, cs in enumerate(scene_chars)]})


# -- the plan ----------------------------------------------------------------

def test_the_cast_is_parsed_and_lowercased():
    plan = plan_with_cast([["host"], ["runner"]], cast=(("Host", "a"), ("RUNNER", "b")))
    scenes, _ = _parse_scene_plan(plan, 2, (4.0, 15.0))
    cast, notes = _parse_cast(plan, scenes)
    assert [c["id"] for c in cast] == ["host", "runner"]
    assert notes == []


def test_a_cast_member_in_no_scene_costs_nothing():
    plan = plan_with_cast([["host"], ["host"]])
    scenes, _ = _parse_scene_plan(plan, 2, (4.0, 15.0))
    cast, notes = _parse_cast(plan, scenes)
    assert [c["id"] for c in cast] == ["host"]
    assert any("appears in no scene" in n for n in notes)


def test_a_scene_naming_an_undeclared_person_is_reported():
    plan = plan_with_cast([["host", "stranger"]])
    scenes, _ = _parse_scene_plan(plan, 1, (4.0, 15.0))
    _cast, notes = _parse_cast(plan, scenes)
    assert any("does not declare" in n and "stranger" in n for n in notes)


def test_scenes_carry_their_characters():
    plan = plan_with_cast([["host"], ["runner"], ["host"]])
    scenes, _ = _parse_scene_plan(plan, 3, (4.0, 15.0))
    assert [s["characters"] for s in scenes] == [["host"], ["runner"], ["host"]]


# -- anchor selection --------------------------------------------------------

def test_anchors_come_from_cast_portraits_that_exist():
    job = Job(id="X", state="intake", intake={}, created_at="", updated_at="")
    job.put_character(Character(id="host", plate="plates/cast_host.png"))
    job.put_character(Character(id="runner"))          # no portrait yet
    scene = Scene(idx=0, characters=["host", "runner", "ghost"])
    assert job.anchors_for(scene) == ["plates/cast_host.png"]


def test_anchors_are_capped():
    """Beyond two the references compete and the result drifts toward an
    average of them."""
    job = Job(id="X", state="intake", intake={}, created_at="", updated_at="")
    for n in "abcd":
        job.put_character(Character(id=n, plate=f"plates/cast_{n}.png"))
    scene = Scene(idx=0, characters=list("abcd"))
    assert len(job.anchors_for(scene, limit=2)) == 2


def test_the_identity_block_only_appears_when_there_is_an_anchor():
    assert _with_anchor("a prompt", 0) == "a prompt"
    one = _with_anchor("a prompt", 1)
    assert "THE IMAGE WINS" in one and "reference image show" in one
    assert _with_anchor("a prompt", 2).startswith("IDENTITY ANCHOR")


def test_the_identity_block_says_the_image_outranks_the_words():
    """Otherwise the model averages the two and the face drifts anyway."""
    block = _with_anchor("x", 1)
    assert "OUTRANKS THE DESCRIPTION" in block
    assert "wardrobe" in block and "setting" in block


# -- end to end --------------------------------------------------------------

@pytest.fixture
def anchored(home, reference):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed",
                  text=plan_with_cast([["host"], ["runner"], ["host"]]),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    return cfg, store, engine, make_job(store, reference, scenes=3, config=cfg)


def test_a_portrait_is_bought_once_per_character(anchored):
    _cfg, store, engine, job = anchored
    job = engine.run(job)
    assert job.state == "GATE_PLATES"
    assert {c["id"] for c in job.cast} == {"host", "runner"}
    for c in job.cast:
        assert c["plate"] == f"plates/cast_{c['id']}.png"
        assert (store.job_dir(job.id) / c["plate"]).exists()
    backend = engine.providers.backend_for("image")
    images = [c for c in backend.calls if c["op"] == "submit" and c["kind"] == "image"]
    assert len(images) == 5          # two portraits + three scenes


def test_every_scene_plate_is_generated_with_its_anchor(anchored):
    _cfg, _store, engine, job = anchored
    job = engine.run(job)
    backend = engine.providers.backend_for("image")
    scene_calls = [c for c in backend.calls
                   if c["op"] == "submit" and c["kind"] == "image"
                   and c["medias"]]
    assert len(scene_calls) == 3
    for call in scene_calls:
        assert len(call["medias"]) == 1
        assert "cast_" in call["medias"][0]
        assert call["prompt"].startswith("IDENTITY ANCHOR")


def test_the_two_host_scenes_share_one_portrait(anchored):
    """The whole point: scenes 0 and 2 must be anchored to the same face."""
    _cfg, _store, engine, job = anchored
    job = engine.run(job)
    backend = engine.providers.backend_for("image")
    used = {}
    for call in backend.calls:
        if call["op"] == "submit" and call["kind"] == "image" and call["medias"]:
            used[call["prompt"].rsplit("\n", 1)[-1]] = call["medias"][0]
    hosts = [v for k, v in used.items() if k in ("p0", "p2")]
    assert len(hosts) == 2 and hosts[0] == hosts[1]
    assert "cast_host" in hosts[0]


def test_portraits_are_not_re_bought_on_a_re_run(anchored):
    _cfg, store, engine, job = anchored
    job = engine.run(job)
    backend = engine.providers.backend_for("image")
    before = len([c for c in backend.calls
                  if c["op"] == "submit" and c["kind"] == "image"])
    from fjor_studio.stages import steps
    steps.cast_plates(engine._ctx(store.load(job.id)))
    assert len([c for c in backend.calls
                if c["op"] == "submit" and c["kind"] == "image"]) == before


def test_anchoring_can_be_switched_off(home, reference):
    """Backwards compatible: without it, plates behave exactly as before."""
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]},
                                 "characters": {"enabled": False}})
    write_replies(home, analysis="a", text=plan_with_cast([["host"], ["host"]]),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    job = engine.run(make_job(store, reference, scenes=2, config=cfg))
    assert job.cast == []
    backend = engine.providers.backend_for("image")
    calls = [c for c in backend.calls if c["op"] == "submit" and c["kind"] == "image"]
    assert len(calls) == 2 and all(not c["medias"] for c in calls)


def test_a_portrait_records_what_it_paid_for(anchored):
    """A character buys a plate, so it must persist a task id like a scene."""
    _cfg, store, engine, job = anchored
    job = engine.run(job)
    for c in job.cast:
        assert c["submissions"] and c["submissions"][0]["status"] == "completed"
    lines = [e for e in job.ledger if e["item"].startswith("cast ")]
    assert len(lines) == 2


def test_the_plate_forecast_counts_the_portraits(anchored):
    """A forecast that leaves them out is the same under-quote the per-second
    clip rate exists to prevent, just smaller."""
    _cfg, _store, engine, job = anchored
    write_config(engine.config.home, pipeline={"gates": {"skip": []}})
    from fjor_studio.app import open_studio
    cfg, store, engine = open_studio(engine.config.home)
    job = engine.run(store.load(job.id))
    assert job.state == "GATE_PLAN"
    f = job.forecasts["plates"]
    # three scenes plus two cast portraits
    assert len(f["items"]) == 5
    import json as _j
    plan = _j.loads((store.job_dir(job.id) / "review" / "plan.json").read_text())
    assert {c["id"] for c in plan["cast"]} == {"host", "runner"}
    assert plan["scenes"][0]["characters"] == ["host"]


# -- a variation stars the same person ---------------------------------------

def test_a_derived_job_keeps_the_cast_and_the_portraits(anchored):
    """LME109: derived from LME108 at 'plates', it inherited the prompts --
    every scene still naming 'host' -- but not the cast. `anchors_for` found
    nothing, each plate invented a face, and the producer got five different
    women at the gate, all of them paid for."""
    from fjor_studio.derive import derive
    _cfg, store, engine, job = anchored
    job = engine.approve(engine.run(job))          # through the plates
    child = derive(store, job.id, "LME999", "plates")

    assert {c["id"] for c in child.cast} == {"host", "runner"}
    for member in child.cast:
        assert member["plate"], f"{member['id']} came across without a portrait"
        assert (store.job_dir(child.id) / member["plate"]).is_file()
    # the scene plates are NOT inherited -- those are what the variation re-buys
    assert all(not s["plate"] for s in child.scenes)


def test_the_re_bought_plates_of_a_variation_are_anchored(anchored):
    """The point of carrying the portrait: the new plates are the same person."""
    from fjor_studio.derive import derive
    _cfg, store, engine, job = anchored
    job = engine.approve(engine.run(job))
    child = derive(store, job.id, "LME999", "plates")

    backend = engine.providers.backend_for("image")
    images = lambda: [c for c in backend.calls
                      if c["op"] == "submit" and c["kind"] == "image"]
    before = len(images())
    child = engine.run(child)
    scene_calls = images()[before:]

    assert scene_calls, "the variation bought nothing"
    for call in scene_calls:
        assert call.get("medias"), "a scene plate was generated with no anchor"
    # and no portrait was re-bought: the parent's came across
    assert not any("cast_" in str(c.get("params", {}).get("out_path", ""))
                   for c in scene_calls)


def test_a_rewrite_declares_its_own_cast(anchored):
    """from='prompts' re-runs the writer, so carrying the old cast would pin a
    rewritten creative to the face of the one it replaced."""
    from fjor_studio.derive import derive
    _cfg, store, engine, job = anchored
    job = engine.approve(engine.run(job))
    child = derive(store, job.id, "LME999", "prompts")
    assert child.cast == []


def test_a_portrait_the_parent_lost_is_re_bought_not_skipped(anchored):
    """A check that could not look never reports all-clear: if the file is gone,
    the description still travels and the portrait is bought again."""
    from fjor_studio.derive import derive
    _cfg, store, engine, job = anchored
    job = engine.approve(engine.run(job))
    (store.job_dir(job.id) / "plates" / "cast_host.png").unlink()
    child = derive(store, job.id, "LME999", "plates")
    host = [c for c in child.cast if c["id"] == "host"][0]
    assert host["plate"] is None
    assert host["description"]                     # still knows who they are


# -- and nothing unanchorable is ever paid for -------------------------------

def test_plates_refuse_to_spend_on_a_person_the_cast_does_not_describe(home, reference):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed",
                  text=json.dumps({"scenes": [
                      {"idx": 0, "characters": ["host"], "image_prompt": "p0",
                       "video_prompt": "m0", "duration_s": 5}]}),   # no cast
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    job = engine.run(make_job(store, reference, scenes=1, config=cfg))

    assert job.state == "failed"
    assert "host" in job.error and "cast" in job.error
    backend = engine.providers.backend_for("image")
    assert not [c for c in backend.calls
                if c["op"] == "submit" and c["kind"] == "image"], \
        "it bought a plate before noticing nothing could anchor it"
    assert job.spent == 0 or all(l["stage"] != "plates" for l in job.ledger)


def test_the_refusal_lifts_when_anchoring_is_off(home, reference):
    """characters.enabled: false is a real choice -- text-only plates, and the
    producer has said so."""
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]},
                                 "characters": {"enabled": False}})
    write_replies(home, analysis="analysed",
                  text=json.dumps({"scenes": [
                      {"idx": 0, "characters": ["host"], "image_prompt": "p0",
                       "video_prompt": "m0", "duration_s": 5}]}),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    job = engine.run(make_job(store, reference, scenes=1, config=cfg))
    assert job.state == "GATE_PLATES"
    assert job.scenes[0]["plate"]


def test_a_variation_can_ask_for_a_new_face(anchored):
    """Same person or new person are both variations; five different women is
    not. The pipeline cannot guess between the first two, so `recast` asks."""
    from fjor_studio.derive import derive
    _cfg, store, engine, job = anchored
    job = engine.approve(engine.run(job))
    child = derive(store, job.id, "LME999", "plates", recast=True)

    # the descriptions travel -- the shots must still agree with each other
    assert {c["id"] for c in child.cast} == {"host", "runner"}
    assert all(c["description"] for c in child.cast)
    # the faces do not
    assert all(c["plate"] is None for c in child.cast)
    assert not (store.job_dir(child.id) / "plates" / "cast_host.png").exists()


def test_a_recast_buys_its_own_portraits_and_anchors_to_them(anchored):
    from fjor_studio.derive import derive
    _cfg, store, engine, job = anchored
    job = engine.approve(engine.run(job))
    child = engine.run(derive(store, job.id, "LME999", "plates", recast=True))

    for member in child.cast:
        assert member["plate"], f"{member['id']} was never given a face"
        assert (store.job_dir(child.id) / member["plate"]).is_file()
    backend = engine.providers.backend_for("image")
    scene_calls = [c for c in backend.calls
                   if c["op"] == "submit" and c["kind"] == "image"][-3:]
    for call in scene_calls:
        assert call.get("medias"), "a recast scene plate went unanchored"


def test_a_rewritten_description_replaces_the_person(anchored):
    """Another draw of the same words is another woman of the same description.
    Changing the words is how a variation gets a visibly different one."""
    from fjor_studio.derive import derive
    _cfg, store, engine, job = anchored
    job = engine.approve(engine.run(job))
    child = derive(store, job.id, "LME999", "plates",
                   cast_descriptions={"host": "early 50s, silver crop, tall"})
    host = [c for c in child.cast if c["id"] == "host"][0]
    assert host["description"] == "early 50s, silver crop, tall"
    assert host["plate"] is None                  # the old face cannot stand for it
    runner = [c for c in child.cast if c["id"] == "runner"][0]
    assert runner["plate"], "an untouched character lost their portrait"
