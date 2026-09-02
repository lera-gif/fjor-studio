"""The lore: what a vertical IS, reaching the prompts that make it.

Until this existed the pipeline knew a vertical's prefix and folder and nothing
else, and everything that decides whether a creative is right for its niche
lived in documents beside the work.
"""
import json
import pathlib

import pytest

from conftest import make_job, scene_plan, write_config, write_replies
from fjor_studio import config as config_mod
from fjor_studio import lore
from fjor_studio.app import open_studio
from fjor_studio.config import UnknownVertical

ROOT = pathlib.Path(__file__).resolve().parents[1]


def shipped():
    return config_mod.load(ROOT)


# -- the file itself ---------------------------------------------------------

def test_every_lore_entry_belongs_to_a_registered_vertical():
    """Lore for a vertical nobody registered would never be read, and a silent
    no-op is how a producer comes to believe a niche is configured."""
    cfg = shipped()
    registered = set(cfg.verticals["verticals"])
    for name in cfg.lore["lore"]:
        assert name in registered, name


def test_lore_for_an_unregistered_vertical_is_refused(tmp_path):
    import yaml
    home = tmp_path / "h"
    (home / "config").mkdir(parents=True)
    (home / "config" / "verticals.yaml").write_text(
        yaml.safe_dump({"verticals": {"yoga": {"prefix": "Y", "folder": "YOGA"}}}))
    (home / "config" / "lore.yaml").write_text(
        yaml.safe_dump({"lore": {"atlantis": {"mechanic": "swimming to a myth"}}}))
    with pytest.raises(UnknownVertical, match="atlantis"):
        config_mod.load(home)


def test_the_verticals_that_ship_creatives_all_have_lore():
    """The six the owner called active, 2026-09-02."""
    cfg = shipped()
    for name in ("lymph_exercise", "lymph_massage", "bp_walking",
                 "back_pain", "apostolic_walking"):
        entry = lore.for_vertical(cfg, name)
        assert entry, name
        for field in ("mechanic", "names", "forbidden_lexicon", "objections",
                      "cast_lock", "negative_tokens"):
            assert entry.get(field), (name, field)


def test_a_registered_vertical_without_lore_is_not_an_error():
    """The registry is the authority on what exists; lore is added as written."""
    cfg = shipped()
    assert lore.writer_block(cfg, "strong_legs") == ""
    assert lore.negatives(cfg, "strong_legs") == ""


# -- what the writer is told -------------------------------------------------

def test_the_writer_is_given_the_lore_of_the_job_s_vertical(home, reference):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed", text=scene_plan(1),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    # the sandbox registers its own verticals; give it real lore to find
    cfg.lore = {"lore": {"lipedema_pilates": {
        "mechanic": "gentle pilates for heavy, painful legs",
        "forbidden_lexicon": "no gym-bro, no calorie talk",
        "negative_tokens": "dumbbells, barbells, bathroom scale"}}}
    engine.config = cfg
    job = make_job(store, reference, scenes=1, config=cfg)
    engine.run(job)
    brief = [c["prompt"] for c in engine.providers.backend_for("text").calls
             if c["op"] == "submit" and c["kind"] == "text"][0]
    assert "NICHE LORE -- LIPEDEMA PILATES" in brief
    assert "gentle pilates for heavy, painful legs" in brief
    assert "no gym-bro, no calorie talk" in brief
    # it does not outrank the reference, and says so
    assert "mirror the reference" in brief.lower()


def test_the_niche_negatives_reach_every_generated_frame(home, reference):
    """Appended by the code, not asked of the writer: the source templates call
    this list mandatory for every generation, and a list a language model is
    asked to reproduce is a list that drifts."""
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed", text=scene_plan(1),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    cfg.lore = {"lore": {"lipedema_pilates": {
        "negative_tokens": "dumbbells, barbells, bathroom scale",
        "keep_out_of_negatives": "a mat, a chair"}}}
    engine.config = cfg
    job = make_job(store, reference, scenes=1, config=cfg)
    job = engine.approve(engine.run(job))
    for kind in ("image", "video"):
        calls = [c for c in engine.providers.backend_for(kind).calls
                 if c["op"] == "submit" and c["kind"] == kind]
        assert calls, kind
        for call in calls:
            assert "bathroom scale" in call["prompt"], kind
            # and the niche's own subject is protected from the negatives
            assert "Do NOT negate these: a mat, a chair" in call["prompt"], kind


# -- provenance --------------------------------------------------------------

def test_the_ported_lore_still_matches_its_source():
    """Ported, never invented. If fjor-video's entry changes, ours is stale --
    and a stale niche rule is worse than none, because it reads as current."""
    import yaml
    src_path = ROOT.parent / "fjor-video" / "config" / "verticals.yaml"
    if not src_path.exists():
        pytest.skip("fjor-video is not beside this checkout")
    src = yaml.safe_load(src_path.read_text())["verticals"]
    ours = shipped().lore["lore"]
    drifted = []
    for name, entry in src.items():
        if name not in ours:
            continue
        for field, value in entry.items():
            if field in ("group", "id_prefix", "folder"):
                continue          # the registry owns these, and only it
            if ours[name].get(field) != value:
                drifted.append(f"{name}.{field}")
    assert not drifted, f"drifted from fjor-video: {drifted}"


# -- the two families disagree about time, and that is the point -------------

def test_a_diet_vertical_forbids_the_lexicon_an_activity_one_requires():
    """The rule that most often goes wrong across the two families. An activity
    vertical's offer IS the time ('just five minutes a day'); in a diet vertical
    the same phrase sounds like an exercise ad and is categorically forbidden."""
    cfg = shipped()
    for diet in ("mediterranean_diet", "cortisol_diet", "biblical_diet",
                 "intermittent_fasting"):
        forbidden = lore.for_vertical(cfg, diet)["forbidden_lexicon"]
        assert "ZERO TIME-BASED LEXICON" in forbidden, diet
    for activity in ("back_pain", "apostolic_walking"):
        required = lore.for_vertical(cfg, activity)["power_words"]
        assert "REQUIRED time lexicon" in required, activity


def test_the_nutrition_verticals_are_registered_and_loreful():
    cfg = shipped()
    for name, prefix in (("mediterranean_diet", "M"), ("cortisol_diet", "COR"),
                         ("biblical_diet", "R"), ("intermittent_fasting", "IF")):
        assert cfg.vertical(name, strict=True)["prefix"] == prefix
        assert cfg.vertical_for_prefix(prefix) == name
        assert lore.for_vertical(cfg, name).get("mechanic")


def test_the_two_names_the_voice_model_mangles_are_never_spoken():
    """Both were found by a broken take, not by reading a doc: 'Cortisol Detox'
    renders as 'Cortizal Dax', and 'Intermittent' is simply too long."""
    cfg = shipped()
    assert "NEVER used inside the creative" in \
        lore.for_vertical(cfg, "cortisol_diet")["forbidden_names"]
    assert "NEVER SPOKEN" in \
        lore.for_vertical(cfg, "intermittent_fasting")["forbidden_names"]
