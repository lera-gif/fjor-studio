"""The job record and its store."""
import json

import pytest

from fjor_studio.engine import Job, JobStore, Scene, StoreError, Submission
from fjor_studio.ids import delivered_ids, next_id, parse


def test_create_and_roundtrip(tmp_path):
    store = JobStore(tmp_path / "jobs")
    job = store.create("LIPIL001", {"reference": "x.mp4"})
    job.analysis = {"text": "hello"}
    store.save(job)
    back = store.load("LIPIL001")
    assert back.id == "LIPIL001"
    assert back.analysis == {"text": "hello"}
    assert back.events[0]["type"] == "created"


def test_save_is_atomic_and_leaves_no_temp_files(tmp_path):
    store = JobStore(tmp_path / "jobs")
    job = store.create("LIPIL001", {})
    for i in range(5):
        job.meta["n"] = i
        store.save(job)
    leftovers = list(store.job_dir("LIPIL001").glob(".job.*"))
    assert leftovers == []
    assert json.loads((store.job_dir("LIPIL001") / "job.json").read_text())["meta"]["n"] == 4


def test_duplicate_id_is_refused(tmp_path):
    store = JobStore(tmp_path / "jobs")
    store.create("LIPIL001", {})
    with pytest.raises(StoreError, match="already exists"):
        store.create("LIPIL001", {})


def test_delete_frees_the_id_without_destroying_anything(tmp_path):
    store = JobStore(tmp_path / "jobs")
    store.create("LIPIL001", {})
    dest = store.delete("LIPIL001")
    assert store.list_ids() == []
    assert (dest / "job.json").exists()       # retired, not unlinked
    store.create("LIPIL001", {})              # the id is available again


# -- scenes and submissions --------------------------------------------------

def test_a_submission_is_recorded_before_it_resolves():
    scene = Scene(idx=0)
    scene.record(Submission(kind="video", backend="kie",
                            model="bytedance/seedance-2-fast", task_id="t1"))
    assert scene.submissions[0]["status"] == "submitted"
    assert scene.paid == 0.0
    scene.finish("t1", "completed", credits=124.0, url="https://x/v.mp4")
    assert scene.submissions[0]["status"] == "completed"
    assert scene.paid == 124.0


def test_finishing_an_unknown_task_is_an_error():
    scene = Scene(idx=0)
    with pytest.raises(KeyError):
        scene.finish("nope", "completed")


def test_open_submissions_are_the_ones_we_paid_for_and_never_collected(tmp_path):
    store = JobStore(tmp_path / "jobs")
    job = store.create("LIPIL001", {})
    s0, s1 = Scene(idx=0), Scene(idx=1)
    s0.record(Submission(kind="video", backend="kie", model="m", task_id="done"))
    s0.finish("done", "completed", credits=10)
    s1.record(Submission(kind="video", backend="kie", model="m", task_id="orphan"))
    job.put_scene(s0)
    job.put_scene(s1)
    store.save(job)
    back = store.load("LIPIL001")
    assert [s["task_id"] for s in back.open_submissions()] == ["orphan"]


def test_ledger_totals_per_backend(tmp_path):
    store = JobStore(tmp_path / "jobs")
    job = store.create("LIPIL001", {})
    job.spend("plates", "scene 0 image", 7.0, "kie", 0)
    job.spend("clips", "scene 0 video", 124.0, "kie", 0)
    job.spend("analysis", "pass 1", 2.0, "gemini")
    assert job.spent == pytest.approx(133.0)
    assert job.spent_by_backend() == {"kie": pytest.approx(131.0),
                                      "gemini": pytest.approx(2.0)}


def test_put_scene_replaces_rather_than_duplicates():
    job = Job(id="X", state="intake", intake={}, created_at="", updated_at="")
    job.put_scene(Scene(idx=1, plate="a.png"))
    job.put_scene(Scene(idx=0))
    job.put_scene(Scene(idx=1, plate="b.png"))
    assert [s["idx"] for s in job.scenes] == [0, 1]
    assert job.scene(1).plate == "b.png"


# -- ids ---------------------------------------------------------------------

def test_ids_increment_per_prefix():
    assert next_id("LIPIL", []) == "LIPIL001"
    assert next_id("LIPIL", ["LIPIL001", "LIPIL007", "MENY003"]) == "LIPIL008"
    assert next_id("MENY", ["LIPIL009"]) == "MENY001"


def test_single_letter_prefixes_work():
    """`yoga` is Y and `yoga_men` is YM -- no derivation rule produces those,
    which is why prefixes come from verticals.yaml."""
    assert next_id("Y", ["Y003", "YM007"]) == "Y004"
    assert next_id("YM", ["Y003", "YM007"]) == "YM008"


def test_ids_ignore_names_that_are_not_creative_ids():
    assert next_id("LIPIL", ["scratch", "LIPIL002", "_deleted"]) == "LIPIL003"


def test_four_digit_ids_are_read_and_kept_wide():
    assert parse("PIL901") == ("PIL", 901)
    assert next_id("PIL", ["PIL999"]) == "PIL1000"


def test_a_bad_prefix_is_rejected():
    with pytest.raises(ValueError):
        next_id("PI1", [])


# -- ids already shipped -----------------------------------------------------

def test_delivered_ids_are_read_off_the_week_folders(tmp_path):
    """Those folders hold work from more than one tool. An id reused across them
    puts two different creatives under one name in the ad platform."""
    week = tmp_path / "MENOPAUSE YOGA" / "34 week"
    week.mkdir(parents=True)
    (week / "n-MENY069_ch-fb_t-video_c-canu_pr-lp_ds-nano_w-34_s-1080x1920.mp4").touch()
    (week / "n-MENY071_ch-fb_t-video_c-julia-week_pr-lp_ds-nano_w-34_s-1080x1350.mp4").touch()
    (week / "MENY072_manifest.json").touch()
    (week / "notes.txt").touch()
    assert delivered_ids(tmp_path) == {"MENY069", "MENY071", "MENY072"}
    assert next_id("MENY", delivered_ids(tmp_path)) == "MENY073"


def test_delivered_ids_survives_a_missing_root(tmp_path):
    """Allocation must not break because a volume is offline."""
    assert delivered_ids(tmp_path / "nope") == set()
    assert delivered_ids(None) == set()


# -- reading a creative name a producer pasted -------------------------------

def test_a_pasted_name_yields_every_field_it_carries():
    from fjor_studio.naming import parse_name
    d = parse_name("n-LIPIL025_ch-fb_t-video_c-test_pr-lp_ds-nano_w-34_s-1080x1350")
    assert d["id"] == "LIPIL025" and d["week"] == 34
    assert d["concept"] == "test" and d["producer"] == "lp"
    assert d["pasted_size"] == [1080, 1350]


@pytest.mark.parametrize("raw", [
    "n-Y004_ch-fb_t-video_c-morph_pr-ts_ds-nano_w-34_s-1080x1350",
    "n-Y004_ch-fb_t-video_c-morph_pr-ts_ds-nano_w-34_s-1080x1350.mp4",
    '  "n-Y004_ch-fb_t-video_c-morph_pr-ts_ds-nano_w-34_s-1080x1350"  ',
])
def test_the_parser_forgives_how_a_name_gets_copied(raw):
    """Nobody types the .mp4 when copying a name out of a sheet."""
    from fjor_studio.naming import parse_name
    assert parse_name(raw)["id"] == "Y004"


@pytest.mark.parametrize("bad", ["LIPIL025", "", "n-LIPIL025_ch-fb", "some words"])
def test_a_name_that_is_not_one_is_refused(bad):
    from fjor_studio.naming import parse_name
    with pytest.raises(ValueError):
        parse_name(bad)


def test_a_round_trip_through_build_and_parse_agrees():
    from fjor_studio import naming
    built = naming.build("MENY077", "julia week", 35, 1080, 1350, producer="ag")
    d = naming.parse_name(built)
    assert (d["id"], d["week"], d["concept"], d["producer"]) == \
        ("MENY077", 35, "julia-week", "ag")
