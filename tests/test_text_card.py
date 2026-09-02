"""Our offer, set the way the reference sets its own text.

The manner is copied; the words are ours. The two things this must never do are
copy the reference's disclaimer, and cover our own.
"""
import json
import subprocess

import pytest

from conftest import make_job, scene_plan, write_config, write_replies
from fjor_studio.app import open_studio
from fjor_studio.gen.base import GenError


def make_the_mock_draw_cards(engine, cfg, y="300", text="28 DAYS"):
    """The mock writes a placeholder png. A text card has to LOOK like one --
    flat key colour with our words on it -- or the keying has nothing to remove
    and the bottom-band check has nothing to measure."""
    from pathlib import Path
    from fjor_studio.assemble import ffmpeg_with_libass
    font = cfg.assets_dir / "fonts" / "Inter-Bold.ttf"
    backend = engine.providers.backend_for("image")
    # `_write` is where the mock puts bytes on disk, at POLL time. Hooking
    # `generate` is too early: the prototype is copied over it afterwards.
    original = backend._write

    def write(result):
        path = original(result)
        if Path(path).name.startswith("text_card"):
            subprocess.run(
                [ffmpeg_with_libass(), "-y", "-v", "error", "-f", "lavfi",
                 "-i", "color=c=0x00B140:size=1080x1920", "-vf",
                 f"drawtext=fontfile={font}:text='{text}':fontcolor=white:"
                 f"fontsize=110:x=(w-tw)/2:y={y}:borderw=8:bordercolor=black",
                 "-frames:v", "1", str(path)], check=True, capture_output=True)
        return path

    backend._write = write
    return backend


@pytest.fixture
def carded(home, reference):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]},
                                 "delivery": {"formats": ["9:16"]}})
    write_replies(home, analysis="analysed", text=scene_plan(2),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    make_the_mock_draw_cards(engine, cfg)
    job = make_job(store, reference, scenes=2, config=cfg, packshot="formula",
                   text_card="LOSE THE SWELLING\nIN 28 DAYS")
    return cfg, store, engine, job


def test_the_analysis_is_asked_how_the_reference_sets_type(carded):
    _cfg, _store, engine, job = carded
    job = engine.run(job)
    backend = engine.providers.backend_for("analysis")
    # the FIRST analysis call is the reference read; the later ones are QA
    brief = [c for c in backend.calls if c.get("kind") == "analysis"][0]["prompt"]
    assert "TYPOGRAPHY" in brief
    assert "BLOCK LAYOUT" in brief
    # the one thing it must never carry forward
    assert "never" in brief and "disclaimer" in brief


def test_a_job_without_a_card_is_not_asked_about_typography(home, reference):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed", text=scene_plan(2),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    job = engine.run(make_job(store, reference, scenes=2, config=cfg))
    backend = engine.providers.backend_for("analysis")
    # the FIRST analysis call is the reference read; the later ones are QA
    brief = [c for c in backend.calls if c.get("kind") == "analysis"][0]["prompt"]
    assert "TYPOGRAPHY" not in brief


def test_the_card_carries_our_words_and_a_flat_key(carded):
    _cfg, store, engine, job = carded
    job = engine.run(job)
    assert job.meta.get("text_card"), "no card was made"
    assert (store.job_dir(job.id) / job.meta["text_card"]).is_file()

    backend = engine.providers.backend_for("image")
    card = [c for c in backend.calls
            if c["op"] == "submit" and "TEXT CARD" in c["prompt"]][0]
    assert "LOSE THE SWELLING" in card["prompt"]
    assert "FLAT, EVEN green" in card["prompt"]
    assert "BOTTOM 15% OF THE FRAME" in card["prompt"]
    assert "NEVER reproduce the" in card["prompt"]


def test_the_card_is_bought_once_for_the_whole_creative(carded):
    """It is laid over every size at assembly. Buying it per format would pay
    twice for one picture."""
    _cfg, _store, engine, job = carded
    job = engine.run(job)
    backend = engine.providers.backend_for("image")
    cards = [c for c in backend.calls
             if c["op"] == "submit" and "TEXT CARD" in c["prompt"]]
    assert len(cards) == 1


def test_the_gate_prices_the_card(carded):
    _cfg, _store, engine, job = carded
    job = engine.run(job)
    # 2 scenes + 1 card
    assert len(job.forecasts["plates"]["items"]) == 3


def test_the_card_reaches_the_cut(carded):
    _cfg, store, engine, job = carded
    job = engine.approve(engine.run(job))
    assert job.state == "GATE_DRAFT"
    assert job.meta["draft"]["text_card"] == "text_card.png"


def test_a_card_over_the_disclaimer_band_is_regenerated_then_refused(home, reference):
    """That band holds the disclaimer and the badge. A card drawn over an
    approved compliance asset cannot ship, so it is checked before assembly --
    where finding out costs the whole clip spend."""
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]},
                                 "qa": {"plates": {"max_attempts": 2}}})
    write_replies(home, analysis="analysed", text=scene_plan(1),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)

    make_the_mock_draw_cards(engine, cfg, y="h-140", text="SMALL PRINT")
    job = engine.run(make_job(store, reference, scenes=1, config=cfg,
                              text_card="OUR OFFER"))
    assert job.state == "failed"
    assert "bottom of the frame" in job.error
    assert any(e["type"] == "card_regen" for e in job.events)
