"""The clip library, and the two places a library clip goes into a cut: the
opening hook and the product insert. Plus the bed preview route, which is the
other thing the editor serves from assets/ rather than from a job."""
import json
import shutil
import subprocess
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

from conftest import a_finished_cut, make_job, scene_plan, write_config, write_replies
from fjor_studio import library
from fjor_studio.app import open_studio
from fjor_studio.dashboard.server import Studio, make_handler
from fjor_studio.engine import TransitionError

REAL_ASSETS = Path(__file__).resolve().parents[1] / "assets"


def qa_ok():
    return json.dumps({"passed": True, "severity": "ok", "issues": []})


def private_assets(home: Path) -> Path:
    """A sandbox asset library, so the suite never writes into the repo's own
    assets/library/ -- and so a bed exists on a machine that has none."""
    assets = home / "assets"
    for sub in ("disclaimers", "packshots", "fonts"):
        shutil.copytree(REAL_ASSETS / sub, assets / sub)
    bed = assets / "music bed" / "Calm" / "Test Bed.wav"
    bed.parent.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=1", str(bed)],
                   check=True, capture_output=True)
    return assets


def setup(home, reference, scenes=2):
    assets = private_assets(home)
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}},
                 delivery={"assets_dir": str(assets)})
    write_replies(home, analysis="analysed", text=scene_plan(scenes),
                  **{"qa:plate": qa_ok(), "qa:clip": qa_ok()})
    cfg, store, engine = open_studio(home)
    job = make_job(store, reference, scenes=scenes, config=cfg, packshot="formula")
    return cfg, store, engine, job, assets


@pytest.fixture
def live(home, reference):
    cfg, store, _engine, job, assets = setup(home, reference)
    studio = Studio(home)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(studio))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, studio, store, job, assets
    server.shutdown()
    server.server_close()


def get(url, headers=None, method="GET"):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def post(url, payload=None):
    req = urllib.request.Request(
        url, data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def upload(base, path: Path):
    data = path.read_bytes()
    req = urllib.request.Request(f"{base}/api/uploads", data=data,
                                 headers={"X-Filename": path.name}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def wait(studio, job_id, seconds=120):
    import time
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not studio.worker.queued_for(job_id):
            return
        time.sleep(0.2)
    raise AssertionError("worker never finished")


# -- the library itself -------------------------------------------------------

def test_an_own_clip_is_filed_with_a_sidecar_and_listed(tmp_path):
    assets = tmp_path / "assets"
    src = a_finished_cut(tmp_path / "hook.mp4")
    item = library.add_upload(assets, src, "Proven hook")
    assert item["kind"] == "upload" and item["name"] == "Proven hook"
    assert item["duration_s"] == pytest.approx(1.0, abs=0.2)
    assert not src.exists(), "an upload is moved in, not left staged"
    listed = library.list_items(assets)
    assert [i["id"] for i in listed] == [item["id"]]
    assert library.item_path(assets, item["id"]).is_file()
    assert library.item_path(assets, "nope") is None
    assert library.item_path(assets, "../etc/passwd") is None


def test_removing_moves_the_clip_out_of_reach_rather_than_deleting_it(tmp_path):
    assets = tmp_path / "assets"
    item = library.add_upload(assets, a_finished_cut(tmp_path / "a.mp4"), "a")
    library.remove(assets, item["id"])
    assert library.list_items(assets) == []
    trash = list((assets / "library" / "_to_delete").iterdir())
    assert len(trash) == 2, "the media and its sidecar both go to _to_delete"
    with pytest.raises(library.LibraryError):
        library.remove(assets, item["id"])


def test_only_a_clip_is_accepted(tmp_path):
    (tmp_path / "x.png").write_bytes(b"not a clip")
    with pytest.raises(library.LibraryError):
        library.add_upload(tmp_path / "assets", tmp_path / "x.png", "x")


# -- the cut ------------------------------------------------------------------

def test_a_hook_opens_the_cut_and_an_insert_sits_before_the_packshot(home, reference):
    _cfg, store, engine, job, assets = setup(home, reference)
    job = engine.approve(engine.run(job))
    assert job.state == "GATE_DRAFT"
    hook = library.add_upload(assets, a_finished_cut(home / "h.mp4"), "hook")
    insert = library.add_upload(assets, a_finished_cut(home / "i.mp4"), "app demo")
    spent = job.spent

    job = engine.set_edit(job, {"hook": hook["id"], "insert": insert["id"]})
    assert job.state == "GATE_DRAFT"
    assert job.spent == pytest.approx(spent), "a re-cut buys nothing"
    manifest = json.loads((store.job_dir(job.id) / "draft"
                           / "edit_manifest.json").read_text())
    roles = [s["role"] for s in manifest["segments"]]
    assert roles == ["hook", "clip", "clip", "demo", "packshot"]
    assert any("hook " + hook["id"] in e.get("msg", "") for e in job.events
               if e["type"] == "edit")

    # taking them out again is the same gesture
    job = engine.set_edit(job, {"hook": "", "insert": ""})
    manifest = json.loads((store.job_dir(job.id) / "draft"
                           / "edit_manifest.json").read_text())
    assert [s["role"] for s in manifest["segments"]] == ["clip", "clip", "packshot"]


def test_an_edit_naming_a_clip_the_library_does_not_have_is_refused(home, reference):
    _cfg, _store, engine, job, _assets = setup(home, reference)
    job = engine.approve(engine.run(job))
    with pytest.raises(TransitionError, match="not in the clip library"):
        engine.set_edit(job, {"hook": "ghost-000000"})
    assert "hook" not in (job.meta.get("edit") or {})


def test_a_hook_removed_from_the_library_stops_the_re_cut_with_a_reason(home, reference):
    _cfg, _store, engine, job, assets = setup(home, reference)
    job = engine.approve(engine.run(job))
    hook = library.add_upload(assets, a_finished_cut(home / "h.mp4"), "hook")
    job = engine.set_edit(job, {"hook": hook["id"]})
    library.remove(assets, hook["id"])
    job = engine.set_edit(job, {"music": ""})       # any re-cut
    assert job.state == "failed"
    assert "not in the library any more" in (job.error or "")


# -- over HTTP ----------------------------------------------------------------

def test_an_upload_goes_into_the_library_and_is_served_with_ranges(live):
    base, _studio, _store, _job, _assets = live
    staged = upload(base, a_finished_cut(Path(_store.root).parent / "hook.mp4"))
    status, item = post(f"{base}/api/library", {"path": staged["path"], "name": "Hook A"})
    assert status == 200 and item["name"] == "Hook A"
    _s, _h, body = get(f"{base}/api/library")
    assert [i["id"] for i in json.loads(body)["items"]] == [item["id"]]

    status, headers, body = get(f"{base}/library/{item['id']}")
    assert status == 200 and headers["Accept-Ranges"] == "bytes"
    status, headers, body = get(f"{base}/library/{item['id']}",
                                {"Range": "bytes=0-9"})
    assert status == 206 and len(body) == 10
    status, _h, _b = get(f"{base}/library/{item['id']}", method="HEAD")
    assert status == 200
    status, _h, _b = get(f"{base}/library/nothing-here")
    assert status == 404

    status, gone = post(f"{base}/api/library/{item['id']}/delete")
    assert status == 200 and gone["removed"] == item["id"]
    assert json.loads(get(f"{base}/api/library")[2])["items"] == []


def test_a_path_that_was_not_staged_by_the_upload_route_is_refused(live):
    base, _studio, _store, _job, assets = live
    status, body = post(f"{base}/api/library",
                        {"path": str(assets / "packshots" / "formula_916.mp4"),
                         "name": "x"})
    assert status == 400 and "staged" in body["error"]


def test_a_shot_is_kept_from_its_job_with_the_prompts_that_made_it(live):
    base, studio, _store, job, assets = live
    post(f"{base}/api/jobs/{job.id}/run"); wait(studio, job.id)
    post(f"{base}/api/jobs/{job.id}/approve"); wait(studio, job.id)
    status, item = post(f"{base}/api/jobs/{job.id}/keep", {"scene": 1, "name": "her turn"})
    assert status == 200
    assert item["kind"] == "generated" and item["from_job"] == job.id
    assert item["scene"] == 1 and item["video_prompt"] == "motion 1"
    assert library.item_path(assets, item["id"]).is_file()
    # the job keeps its own copy: the library is for reuse, not for moving
    _s, _h, body = get(f"{base}/api/jobs/{job.id}")
    assert json.loads(body)["scenes"][1]["clip"]
    status, body = post(f"{base}/api/jobs/{job.id}/keep", {"scene": 9})
    assert status == 400


def test_the_editor_offers_the_library_and_records_the_choice(live):
    base, studio, _store, job, assets = live
    hook = library.add_upload(assets, a_finished_cut(Path(_store.root).parent / "h.mp4"), "H")
    post(f"{base}/api/jobs/{job.id}/run"); wait(studio, job.id)
    post(f"{base}/api/jobs/{job.id}/approve"); wait(studio, job.id)
    d = json.loads(get(f"{base}/api/jobs/{job.id}")[2])
    assert d["edit"]["open"] and d["edit"]["hook"] == ""
    assert [i["id"] for i in d["edit"]["library"]] == [hook["id"]]
    post(f"{base}/api/jobs/{job.id}/edit", {"edit": {"hook": hook["id"]}})
    wait(studio, job.id)
    d = json.loads(get(f"{base}/api/jobs/{job.id}")[2])
    assert d["state"] == "GATE_DRAFT" and d["edit"]["hook"] == hook["id"]
    assert json.loads(get(f"{base}/api/state")[2])["options"]["library"][0]["id"] == hook["id"]


# -- listening to a bed -------------------------------------------------------

def test_a_bed_is_served_by_its_picker_name(live):
    base, *_ = live
    status, headers, body = get(f"{base}/music/Calm/Test%20Bed")
    assert status == 200 and headers["Accept-Ranges"] == "bytes" and len(body) > 1000
    status, headers, body = get(f"{base}/music/Calm/Test%20Bed", {"Range": "bytes=0-3"})
    assert status == 206 and body == b"RIFF"
    assert get(f"{base}/music/Calm/Test%20Bed", method="HEAD")[0] == 200
    assert get(f"{base}/music/Calm/No%20Such%20Bed")[0] == 404
    assert get(f"{base}/music/..%2F..%2Fconfig%2Fauth.yaml")[0] in (400, 404)


# -- a clip dropped into the folder by hand -----------------------------------
#
# The beds and the packshots are simply scanned; the library used to demand an
# upload through the dashboard, so a file plainly sitting in the folder did not
# exist as far as the picker was concerned.

def test_a_clip_dropped_into_the_folder_is_picked_up(tmp_path):
    from conftest import a_finished_cut
    from fjor_studio import library

    root = tmp_path / "library"
    root.mkdir()
    a_finished_cut(root / "Product demo.mp4", w=270, h=480, seconds=1)

    items = library.list_items(tmp_path)
    assert len(items) == 1
    assert items[0]["name"] == "Product demo"
    assert items[0]["kind"] == "dropped"
    assert items[0]["missing"] is False


def test_a_dropped_clip_keeps_the_name_the_producer_gave_it(tmp_path):
    """Renaming someone's file to suit our scheme loses the only handle they
    have on it."""
    from conftest import a_finished_cut
    from fjor_studio import library

    root = tmp_path / "library"
    root.mkdir()
    a_finished_cut(root / "Product demo.mp4", w=270, h=480, seconds=1)
    library.list_items(tmp_path)
    assert (root / "Product demo.mp4").is_file()      # still there, still named


def test_a_dropped_clips_id_is_stable_across_scans(tmp_path):
    """A job stores `insert: <id>`. If the id were random per scan, the cut
    would stop resolving the moment the dashboard restarted."""
    from conftest import a_finished_cut
    from fjor_studio import library

    root = tmp_path / "library"
    root.mkdir()
    a_finished_cut(root / "hook.mp4", w=270, h=480, seconds=1)
    first = library.list_items(tmp_path)[0]["id"]
    (root / f"{first}.json").unlink()                 # force a fresh adoption
    assert library.list_items(tmp_path)[0]["id"] == first


def test_a_dropped_clip_resolves_to_its_media(tmp_path):
    """The picker returns an id; the cut has to turn it back into a file."""
    from conftest import a_finished_cut
    from fjor_studio import library

    root = tmp_path / "library"
    root.mkdir()
    a_finished_cut(root / "Product demo.mp4", w=270, h=480, seconds=1)
    item_id = library.list_items(tmp_path)[0]["id"]
    assert library.item_path(tmp_path, item_id) == root / "Product demo.mp4"
    assert library.get(tmp_path, item_id)["id"] == item_id


def test_adopting_does_not_duplicate_an_uploaded_item(tmp_path):
    """An uploaded clip already has a sidecar; the scan must not list it twice."""
    from conftest import a_finished_cut
    from fjor_studio import library

    src = tmp_path / "src.mp4"
    a_finished_cut(src, w=270, h=480, seconds=1)
    library.add_upload(tmp_path, src, "Uploaded one")
    before = library.list_items(tmp_path)
    assert len(before) == 1
    assert len(library.list_items(tmp_path)) == 1      # and again, after adoption
