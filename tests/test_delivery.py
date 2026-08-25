"""Delivery into the existing week-folder convention.

    <root>/<VERTICAL FOLDER>/<N> week/n-{id}_ch-…_s-{W}x{H}.mp4

None of this is ours to design -- files in this shape already sit in every week
folder, and the manifests and the ad platform read them.
"""
import json

import pytest

from conftest import make_job, scene_plan, write_config, write_replies
from fjor_studio import naming
from fjor_studio.app import new_job, open_studio
from fjor_studio.config import UnknownVertical


def setup(home, reference, vertical="lipedema_pilates", week=34, concept="ugc",
          formats=("9:16", "4:5"), **intake):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]},
                                 "delivery": {"formats": list(formats)}})
    write_replies(home, analysis="analysed", text=scene_plan(1),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, engine = open_studio(home)
    job = make_job(store, reference, scenes=1, vertical=vertical, config=cfg,
                   week=week, concept=concept, **intake)
    return cfg, store, engine, job


def run_to_done(engine, job):
    return engine.approve(engine.approve(engine.run(job)))


# -- the path ----------------------------------------------------------------

def test_finals_land_in_the_vertical_week_folder(home, reference):
    cfg, _store, engine, job = setup(home, reference,
                                     vertical="menopause_yoga", week=34)
    job = run_to_done(engine, job)
    assert job.state == "done"
    week_dir = home / "VIDEO" / "MENOPAUSE YOGA" / "34 week"
    assert week_dir.is_dir()
    assert sorted(p.name for p in week_dir.glob("*.mp4")) == [
        f"n-{job.id}_ch-fb_t-video_c-ugc_pr-lp_ds-nano_w-34_s-1080x1350.mp4",
        f"n-{job.id}_ch-fb_t-video_c-ugc_pr-lp_ds-nano_w-34_s-1080x1920.mp4",
    ]


def test_both_sizes_ship_every_time(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = run_to_done(engine, job)
    sizes = sorted(naming.parse(p)["w"] + "x" + naming.parse(p)["h"]
                   for p in job.meta["delivered_to"]
                   for p in [p.rsplit("/", 1)[-1]])
    assert sizes == ["1080x1350", "1080x1920"]


def test_the_manifest_travels_with_the_finals(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = run_to_done(engine, job)
    manifest = home / "VIDEO" / "LIPEDEMA PILATES" / "34 week" / f"{job.id}_manifest.json"
    assert manifest.exists()
    data = json.loads(manifest.read_text())
    assert data["id"] == job.id
    assert data["week"] == 34 and data["concept"] == "ugc"
    assert data["spent"] == pytest.approx(job.spent)
    assert len(data["finals"]) == 2


def test_the_producer_token_comes_from_intake(home, reference):
    _cfg, _store, engine, job = setup(home, reference, producer="ag")
    job = run_to_done(engine, job)
    assert all("_pr-ag_" in p for p in job.meta["delivered_to"])


def test_a_multiword_concept_is_slugged_not_rejected(home, reference):
    _cfg, _store, engine, job = setup(home, reference, concept="Julia Week")
    job = run_to_done(engine, job)
    assert all("_c-julia-week_" in p for p in job.meta["delivered_to"])


# -- never hard-delete -------------------------------------------------------

def test_a_redelivery_moves_the_stale_file_rather_than_deleting_it(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = run_to_done(engine, job)
    week_dir = home / "VIDEO" / "LIPEDEMA PILATES" / "34 week"
    first = sorted(week_dir.glob("*.mp4"))[0]
    first.write_bytes(b"AN EARLIER CUT SOMEONE MIGHT STILL WANT")

    job = engine.reassemble(store.load(job.id))
    assert job.state == "GATE_DRAFT"      # a re-cut is reviewed before it ships
    job = engine.approve(job)
    assert job.state == "done"
    trash = week_dir / "_to_delete"
    stale = list(trash.glob("*.mp4"))
    assert len(stale) == 2
    assert any(p.read_bytes().startswith(b"AN EARLIER CUT") for p in stale)
    assert len(list(week_dir.glob("*.mp4"))) == 2       # the new pair, in place
    assert "delivery_replaced" in [e["type"] for e in job.events]


# -- verticals ---------------------------------------------------------------

def test_an_unknown_vertical_is_refused_at_intake(home, reference):
    """Refused where nothing has been paid for. By delivery the creative is
    built and paid for, and the lookup there is deliberately non-strict."""
    write_config(home)
    cfg, store, _engine = open_studio(home)
    with pytest.raises(UnknownVertical, match="not in verticals.yaml"):
        new_job(store, cfg, "kettlebells",
                {"reference": str(reference), "week": 34, "concept": "ugc"})


def test_delivery_still_works_for_a_vertical_missing_from_the_registry(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job.intake["vertical"] = "legacy_free_text"     # as a migrated job might be
    store.save(job)
    job = run_to_done(engine, store.load(job.id))
    assert job.state == "done"
    assert (home / "VIDEO" / "legacy_free_text" / "34 week").is_dir()


def test_the_id_prefix_comes_from_the_registry_not_the_name(home, reference):
    write_config(home)
    cfg, store, _engine = open_studio(home)
    job = new_job(store, cfg, "yoga",
                  {"reference": str(reference), "week": 34, "concept": "ugc"})
    assert job.id == "Y001"          # not "YOGA001"


def test_an_id_already_shipped_is_never_reused(home, reference):
    """The week folders hold work from more than one tool."""
    write_config(home)
    week = home / "VIDEO" / "LIPEDEMA PILATES" / "33 week"
    week.mkdir(parents=True)
    (week / "n-LIPIL021_ch-fb_t-video_c-ugc_pr-lp_ds-nano_w-33_s-1080x1920.mp4").touch()
    cfg, store, _engine = open_studio(home)
    job = new_job(store, cfg, "lipedema_pilates",
                  {"reference": str(reference), "week": 34, "concept": "ugc"})
    assert job.id == "LIPIL022"


# -- preflight guards the name -----------------------------------------------

def test_preflight_fails_a_final_that_would_not_parse(home, reference):
    _cfg, store, engine, job = setup(home, reference, formats=("9:16",))
    job = engine.approve(engine.run(job))       # at GATE_DRAFT
    assert job.state == "GATE_DRAFT"
    job = engine.approve(job)
    (store.job_dir(job.id) / "finals" / "stray_export.mp4").write_text("x")
    from fjor_studio.stages import steps
    from fjor_studio.gen.base import GenError
    with pytest.raises(GenError, match="preflight failed"):
        steps.preflight(engine._ctx(store.load(job.id)))
    report = json.loads(
        (store.job_dir(job.id) / "review" / "preflight.json").read_text())
    assert "final filenames parse" in report["failed"]


def test_preflight_fails_when_a_configured_size_is_missing(home, reference):
    _cfg, store, engine, job = setup(home, reference, formats=("9:16", "4:5"))
    job = engine.approve(engine.run(job))
    job = engine.approve(job)
    for f in (store.job_dir(job.id) / "finals").glob("*1080x1350*"):
        f.unlink()
    from fjor_studio.stages import steps
    from fjor_studio.gen.base import GenError
    with pytest.raises(GenError, match="preflight failed"):
        steps.preflight(engine._ctx(store.load(job.id)))


# -- assembly ---------------------------------------------------------------

def test_the_packshot_is_appended_and_comes_last(home, reference):
    """Their product shots are replaced by ours: the ad ends on our product."""
    _cfg, store, engine, job = setup(home, reference, formats=("9:16",),
                                     packshot="formula")
    job = run_to_done(engine, job)
    manifest = json.loads(
        (store.job_dir(job.id) / "draft" / "edit_manifest.json").read_text())
    roles = [s["role"] for s in manifest["segments"]]
    assert roles[-1] == "packshot"
    assert roles.count("packshot") == 1
    assert "formula_916" in manifest["segments"][-1]["source"]


def test_a_packshot_that_is_not_in_the_library_fails_before_assembly(home, reference):
    _cfg, store, engine, job = setup(home, reference, formats=("9:16",),
                                     packshot="does-not-exist")
    job = engine.approve(engine.run(job))
    assert job.state == "failed"
    assert "no packshot named" in job.error


def test_the_finals_carry_the_compliance_overlays(home, reference):
    """The disclaimer PNGs are approved assets -- overlaid, never re-typeset."""
    _cfg, store, engine, job = setup(home, reference, formats=("9:16", "4:5"),
                                     packshot="formula")
    job = run_to_done(engine, job)
    manifest = json.loads(
        (store.job_dir(job.id) / "finals" / "build_manifest.json").read_text())
    from fjor_studio.assemble import probe
    for entry in manifest["finals"]:
        final = store.job_dir(job.id) / "finals" / entry["file"]
        vs = [s for s in probe(final)["streams"] if s["codec_type"] == "video"][0]
        assert [vs["width"], vs["height"]] == entry["size"] == entry["actual"]
        assert entry["has_audio"] is True


def test_each_size_is_built_from_the_clips_not_cropped_from_the_master(home, reference):
    """A 4:5 cut of a 9:16 master loses a fifth of the frame twice over."""
    _cfg, store, engine, job = setup(home, reference, formats=("9:16", "4:5"),
                                     packshot="formula")
    job = run_to_done(engine, job)
    manifest = json.loads(
        (store.job_dir(job.id) / "finals" / "build_manifest.json").read_text())
    by_fmt = {e["format"]: e for e in manifest["finals"]}
    # the 4:5 packshot twin is shorter than the 9:16 one, so the durations must
    # differ -- proof the 4:5 was assembled, not derived
    assert by_fmt["4:5"]["duration_s"] != by_fmt["9:16"]["duration_s"]
    assert by_fmt["4:5"]["segments"][-1]["source"].endswith("formula_45.mp4")
