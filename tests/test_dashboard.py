"""The dashboard, driven over real HTTP against a real server."""
import json
import pathlib
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from conftest import make_job, scene_plan, write_config, write_replies
from fjor_studio.app import open_studio
from fjor_studio.dashboard.server import Studio, make_handler


@pytest.fixture
def live(home, reference):
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed", text=scene_plan(2),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, _engine = open_studio(home)
    job = make_job(store, reference, scenes=2, config=cfg)
    studio = Studio(home)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(studio))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, studio, store, job
    server.shutdown()
    server.server_close()


def get(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, json.loads(r.read().decode())


def post(url, payload=None):
    req = urllib.request.Request(
        url, data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status, json.loads(r.read().decode())


def wait(studio, job_id, seconds=60):
    import time
    deadline = time.time() + seconds
    while time.time() < deadline:
        if not studio.worker.queued_for(job_id):
            return
        time.sleep(0.2)
    raise AssertionError("worker never finished")


# -- reads -------------------------------------------------------------------

def test_the_page_is_served(live):
    base, *_ = live
    with urllib.request.urlopen(base + "/", timeout=10) as r:
        body = r.read().decode()
    assert r.status == 200
    assert "<title>FJOR Studio</title>" in body
    assert "api/state" in body


def test_state_lists_jobs_and_the_asset_library(live):
    base, _studio, _store, job = live
    _s, data = get(base + "/api/state")
    assert [j["id"] for j in data["jobs"]] == [job.id]
    assert "formula" in data["options"]["packshots"]   # tracked: assembly needs it
    assert isinstance(data["options"]["music"], list)  # optional, may be empty
    assert data["pipeline"][0] == "intake"
    assert "GATE_PLATES" in data["gates"]


def test_detail_exposes_what_a_gate_needs(live):
    base, studio, store, job = live
    post(f"{base}/api/jobs/{job.id}/run")
    wait(studio, job.id)
    _s, d = get(f"{base}/api/jobs/{job.id}")
    assert d["state"] == "GATE_PLATES"
    assert d["gate_ready"] is True
    assert d["next_forecast"]["total"] > 0
    assert d["revisable"]
    assert len(d["scenes"]) == 2
    assert all(s["plate"] for s in d["scenes"])


# -- actions -----------------------------------------------------------------

def test_approve_advances_the_job(live):
    base, studio, store, job = live
    post(f"{base}/api/jobs/{job.id}/run")
    wait(studio, job.id)
    post(f"{base}/api/jobs/{job.id}/approve", {"note": "looks right"})
    wait(studio, job.id)
    _s, d = get(f"{base}/api/jobs/{job.id}")
    assert d["state"] == "GATE_DRAFT"


def test_revise_carries_the_scene_and_the_note(live):
    base, studio, store, job = live
    post(f"{base}/api/jobs/{job.id}/run")
    wait(studio, job.id)
    post(f"{base}/api/jobs/{job.id}/revise",
         {"what": "plates", "note": "warmer light", "scenes": [1]})
    wait(studio, job.id)
    _s, d = get(f"{base}/api/jobs/{job.id}")
    assert d["revisions"][-1]["scenes"] == [1]
    assert d["revisions"][-1]["note"] == "warmer light"
    assert d["state"] == "GATE_PLATES"


def test_an_unknown_action_is_rejected(live):
    base, _studio, _store, job = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(f"{base}/api/jobs/{job.id}/detonate")
    assert exc.value.code == 400


def test_an_id_prefix_nobody_uses_is_refused(live):
    """The prefix is the only part of a creative name that says what the ad is
    for, so an unknown one has to fail rather than guess."""
    base, *_ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base + "/api/jobs", {
            "creative_name": "n-KETL001_ch-fb_t-video_c-x_pr-lp_ds-nano_w-34_s-1080x1350",
            "reference": "/tmp/a.mp4"})
    assert exc.value.code == 400
    assert "id prefix" in exc.value.read().decode()


def test_a_pasted_name_supplies_id_week_concept_producer_and_vertical(live):
    """It replaces four fields the producer would otherwise retype from a sheet
    they already have open."""
    base, _studio, store, _job = live
    _s, r = post(base + "/api/jobs", {
        "creative_name":
            "n-MENY077_ch-fb_t-video_c-julia-week_pr-ag_ds-nano_w-35_s-1080x1350",
        "reference": str(store.job_dir(_job.id) / "ref"),
        "brief": "lean on the joint-friendly angle"})
    assert r["id"] == "MENY077"
    job = store.load("MENY077")
    assert job.intake["vertical"] == "menopause_yoga"
    assert job.intake["week"] == 35
    assert job.intake["concept"] == "julia-week"
    assert job.intake["producer"] == "ag"
    assert job.intake["brief"] == "lean on the joint-friendly angle"
    # not asked for, so the reference's own shot list decides
    assert job.intake.get("scene_count") is None


def test_a_malformed_creative_name_is_refused_with_the_shape(live):
    base, *_ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base + "/api/jobs", {"creative_name": "LIPIL025",
                                  "reference": "/tmp/a.mp4"})
    assert exc.value.code == 400
    body = exc.value.read().decode()
    assert "not a creative name" in body and "n-LIPIL025_ch-fb" in body


def test_the_pasted_size_does_not_choose_the_formats(live):
    """Both sizes are always built; the s- token only says which one they copied."""
    base, _studio, store, _job = live
    post(base + "/api/jobs", {
        "creative_name": "n-MENY078_ch-fb_t-video_c-x_pr-lp_ds-nano_w-34_s-1080x1350",
        "reference": str(store.job_dir(_job.id) / "ref")})
    job = store.load("MENY078")
    assert "pasted_size" not in job.intake
    assert job.intake["creative_name"].endswith("s-1080x1350")


# -- media serving is not a file browser -------------------------------------

def test_media_is_served_from_the_job_directory(live):
    base, studio, store, job = live
    post(f"{base}/api/jobs/{job.id}/run")
    wait(studio, job.id)
    _s, d = get(f"{base}/api/jobs/{job.id}")
    with urllib.request.urlopen(
            f"{base}/media/{job.id}/{d['scenes'][0]['plate']}", timeout=10) as r:
        assert r.status == 200
        assert r.headers["Content-Type"] == "image/png"
        assert len(r.read()) > 0


@pytest.mark.parametrize("evil", [
    "../../../../etc/passwd",
    "..%2f..%2fconfig%2fauth.yaml",
    "config/auth.yaml",
    "job.json",
])
def test_media_refuses_to_leave_the_servable_directories(live, evil):
    """auth.yaml holds live keys. The media route must not be a file browser."""
    base, _studio, _store, job = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{base}/media/{job.id}/{evil}", timeout=10)
    assert exc.value.code in (400, 404, 500)


def test_a_missing_media_file_is_a_404(live):
    base, _studio, _store, job = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{base}/media/{job.id}/plates/nope.png", timeout=10)
    assert exc.value.code == 404


# -- the worker --------------------------------------------------------------

def test_the_worker_runs_one_thing_at_a_time(live):
    """A generation stage blocks for minutes; running several at once multiplies
    the ways a crash can strand a paid task id."""
    base, studio, _store, job = live
    post(f"{base}/api/jobs/{job.id}/run")
    _s, data = get(base + "/api/state")
    assert data["jobs"][0]["busy"] is True
    wait(studio, job.id)
    _s, data = get(base + "/api/state")
    assert data["busy"] is None


def test_a_failing_action_is_recorded_not_swallowed(live):
    base, studio, _store, job = live
    post(f"{base}/api/jobs/{job.id}/approve")   # not at a gate yet
    wait(studio, job.id)
    _s, data = get(base + "/api/state")
    failed = [a for a in data["activity"] if a["state"] == "failed"]
    assert failed and "not at a gate" in failed[0]["detail"]


# -- byte ranges: a video the browser can actually seek ----------------------

def _raw(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def test_parse_range_covers_the_forms_a_browser_sends():
    from fjor_studio.dashboard.server import INVALID_RANGE, parse_range
    assert parse_range(None, 1000) is None
    assert parse_range("bytes=0-99", 1000) == (0, 99)
    assert parse_range("bytes=100-", 1000) == (100, 999)
    assert parse_range("bytes=-500", 1000) == (500, 999)
    assert parse_range("bytes=0-99999", 1000) == (0, 999)      # clamped
    for bad in ("bytes=9999-", "bytes=abc", "bytes=-0", "bytes=50-10",
                "bytes=-", "items=0-9"):
        assert parse_range(bad, 1000) is INVALID_RANGE, bad
    assert parse_range("bytes=0-10", 0) is INVALID_RANGE       # empty file


def _a_clip(base, studio, job_id):
    post(f"{base}/api/jobs/{job_id}/run")
    wait(studio, job_id)
    post(f"{base}/api/jobs/{job_id}/approve")
    wait(studio, job_id)
    _s, d = get(f"{base}/api/jobs/{job_id}")
    clip = next(s["clip"] for s in d["scenes"] if s["clip"])
    return f"{base}/media/{job_id}/{clip}"


def test_media_advertises_ranges_and_serves_them(live):
    """Chrome will not seek a response that says Accept-Ranges: none, even once
    the whole file is buffered -- the draft player could only be watched
    straight through, which is useless at a gate for reviewing the cut."""
    base, studio, _store, job = live
    url = _a_clip(base, studio, job.id)

    status, headers, whole = _raw(url)
    assert status == 200
    assert headers["Accept-Ranges"] == "bytes"
    total = len(whole)

    status, headers, part = _raw(url, {"Range": "bytes=0-99"})
    assert status == 206
    assert headers["Content-Range"] == f"bytes 0-99/{total}"
    assert headers["Content-Length"] == "100"
    assert part == whole[:100]


def test_an_open_ended_range_runs_to_the_end(live):
    base, studio, _store, job = live
    url = _a_clip(base, studio, job.id)
    _s, _h, whole = _raw(url)
    offset = len(whole) // 2
    status, headers, part = _raw(url, {"Range": f"bytes={offset}-"})
    assert status == 206
    assert part == whole[offset:]
    assert headers["Content-Range"] == f"bytes {offset}-{len(whole)-1}/{len(whole)}"


def test_a_suffix_range_returns_the_tail(live):
    base, studio, _store, job = live
    url = _a_clip(base, studio, job.id)
    _s, _h, whole = _raw(url)
    _status, _headers, part = _raw(url, {"Range": "bytes=-64"})
    assert part == whole[-64:]


def test_an_unsatisfiable_range_is_a_416(live):
    base, studio, _store, job = live
    url = _a_clip(base, studio, job.id)
    status, headers, _ = _raw(url, {"Range": "bytes=999999999-"})
    assert status == 416
    assert headers["Content-Range"].startswith("bytes */")


def test_head_reports_the_size_without_the_body(live):
    base, studio, _store, job = live
    url = _a_clip(base, studio, job.id)
    req = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(req, timeout=10) as r:
        assert r.status == 200
        assert int(r.headers["Content-Length"]) > 0
        assert r.headers["Accept-Ranges"] == "bytes"
        assert r.read() == b""


def test_ranges_do_not_bypass_the_directory_guard(live):
    """The range path must not become a way out of the job directory."""
    base, _studio, _store, job = live
    status, _h, _b = _raw(f"{base}/media/{job.id}/config/auth.yaml",
                          {"Range": "bytes=0-10"})
    assert status in (400, 404, 500)


# -- the page carries the guards a producer relies on ------------------------

def test_the_page_confirms_before_committing_a_spend():
    """One click at GATE_PLATES used to commit the whole video budget, and KIE
    has no cancel endpoint."""
    from fjor_studio.dashboard.page import PAGE
    assert "openApprove()" in PAGE
    assert "okDlg.showModal()" in PAGE
    assert "cannot be" in PAGE and "cancelled once submitted" in PAGE


def test_the_page_surfaces_an_action_that_failed_without_changing_state():
    from fjor_studio.dashboard.page import PAGE
    assert "did not run" in PAGE
    assert "STATE.activity" in PAGE


def test_head_is_refused_on_the_json_routes(live):
    """Delegating every route to GET would answer HEAD with a body."""
    base, *_ = live
    req = urllib.request.Request(base + "/api/state", method="HEAD")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 405
    assert exc.value.headers["Allow"] == "GET, POST"


# -- dropped reference videos ------------------------------------------------

def _upload(base, name, data):
    req = urllib.request.Request(
        base + "/api/uploads", data=data,
        headers={"X-Filename": name, "Content-Type": "application/octet-stream"},
        method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, json.loads(r.read().decode())


def _real_video(tmp_path, seconds=1, audio=True):
    import subprocess
    p = tmp_path / "dropped.mp4"
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
           "-i", f"color=c=teal:size=180x320:rate=30:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
                "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(p)]
    subprocess.run(cmd, check=True, capture_output=True)
    return p


def test_safe_filename_keeps_only_a_bare_name():
    """A dropped file's name is attacker-controlled in principle and a path in
    practice on some platforms."""
    from fjor_studio.dashboard.server import safe_filename
    assert safe_filename("ref.mp4") == "ref.mp4"
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename(r"C:\Users\x\clip.mov") == "clip.mov"
    assert safe_filename("") == "reference.mp4"
    assert "/" not in safe_filename("a/b/c.mp4")


def test_a_long_name_keeps_its_extension():
    """Truncating the suffix would turn a long filename into a rejected one."""
    from fjor_studio.dashboard.server import safe_filename
    out = safe_filename("a" * 300 + ".mp4")
    assert out.endswith(".mp4") and len(out) <= 120


def test_a_dropped_video_is_stored_and_probed(live, tmp_path):
    base, *_ = live
    src = _real_video(tmp_path, seconds=1)
    status, r = _upload(base, "my reference.mp4", src.read_bytes())
    assert status == 200
    assert r["name"] == "my reference.mp4"
    assert r["size"] == src.stat().st_size
    assert (r["width"], r["height"]) == (180, 320)
    assert r["duration_s"] == pytest.approx(1.0, abs=0.3)
    assert r["has_audio"] is True
    assert Path(r["path"]).is_file()


def test_the_uploaded_path_is_usable_as_a_reference(live, tmp_path):
    """The whole point: a drop has no path, so the server has to supply one that
    a job can actually read."""
    base, studio, store, _job = live
    _s, up = _upload(base, "ref.mp4", _real_video(tmp_path).read_bytes())
    _s, created = post(base + "/api/jobs", {
        "creative_name": "n-MENY079_ch-fb_t-video_c-drop_pr-lp_ds-nano_w-34_s-1080x1350",
        "reference": up["path"], "scenes": 1})
    post(f"{base}/api/jobs/{created['id']}/run")
    wait(studio, created["id"], seconds=120)
    _s, d = get(f"{base}/api/jobs/{created['id']}")
    assert d["error"] is None
    assert d["intake"]["reference_local"].startswith("ref/")


def test_a_file_with_no_video_stream_is_refused(live, tmp_path):
    """Rejected here, in a dialog, rather than three stages into a paid run."""
    import subprocess
    audio = tmp_path / "sound.mp4"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=300:duration=1", "-c:a", "aac",
                    str(audio)], check=True, capture_output=True)
    base, *_ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        _upload(base, "sound.mp4", audio.read_bytes())
    assert exc.value.code == 400
    assert "no video stream" in exc.value.read().decode()


def test_a_file_that_is_neither_a_reference_nor_a_banner_is_refused(live):
    base, *_ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        _upload(base, "notes.txt", b"hello")
    assert exc.value.code == 400
    body = exc.value.read().decode()
    assert "neither a reference video" in body and "banner image" in body


def test_an_empty_upload_is_refused(live):
    base, *_ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        _upload(base, "ref.mp4", b"")
    assert exc.value.code == 400


def test_a_rejected_upload_leaves_nothing_behind(live, tmp_path):
    base, studio, _store, _job = live
    cfg, _s, _e = studio.open()
    before = list((cfg.home / "uploads").glob("*")) if (cfg.home / "uploads").is_dir() else []
    with pytest.raises(urllib.error.HTTPError):
        _upload(base, "junk.mp4", b"not really a video at all")
    after = list((cfg.home / "uploads").glob("*")) if (cfg.home / "uploads").is_dir() else []
    assert len(after) == len(before)


def test_the_dialog_will_not_submit_without_a_dropped_file():
    from fjor_studio.dashboard.page import PAGE
    assert "Drop a reference video or a banner first" in PAGE
    assert "if(!UPLOAD){" in PAGE


def test_the_page_has_no_dead_selectors():
    """A selector for an element that does not exist threw inside the click
    handler, so the dialog silently never opened -- and because its inputs are
    in the DOM regardless, driving them still 'worked'.

    Checks EVERY id the script reaches for, not a prefix: an earlier version of
    this test only looked at `f_*`, so a missing `#vertWarn` slipped past it and
    a grep for the name matched the script's own reference to it."""
    import re as _re
    from fjor_studio.dashboard.page import PAGE
    referenced = set(_re.findall(r"\$\('#([A-Za-z0-9_-]+)'\)", PAGE))
    referenced |= set(_re.findall(r"getElementById\('([A-Za-z0-9_-]+)'\)", PAGE))
    referenced |= set(_re.findall(r"querySelector\('#([A-Za-z0-9_-]+)'\)", PAGE))
    defined = set(_re.findall(r'id="([A-Za-z0-9_-]+)"', PAGE))
    missing = referenced - defined
    assert not missing, f"referenced by the script but not in the markup: {sorted(missing)}"


def test_the_dialog_opens_before_it_is_populated():
    """So a future dead selector cannot stop it opening."""
    from fjor_studio.dashboard.page import PAGE
    handler = PAGE.split("$('#newBtn').onclick=")[1].split("};")[0]
    assert handler.index("newDlg.showModal()") < handler.index("$('#f_packshot')")


# -- target vertical: suggested by the prefix, chosen by the producer --------

def test_an_explicit_vertical_overrides_the_one_the_prefix_implies(live):
    """The prefix suggests it; the producer decides it. An adaptation can
    legitimately target a vertical other than the one its id came from."""
    base, _studio, store, _job = live
    _s, r = post(base + "/api/jobs", {
        "creative_name": "n-LIPIL077_ch-fb_t-video_c-x_pr-lp_ds-nano_w-34_s-1080x1350",
        "vertical": "menopause_yoga",
        "reference": str(store.job_dir(_job.id) / "ref")})
    job = store.load(r["id"])
    assert job.id == "LIPIL077"                     # id still comes from the name
    assert job.intake["vertical"] == "menopause_yoga"
    assert job.intake["folder"] == "MENOPAUSE YOGA"  # and delivery follows it


def test_without_an_explicit_vertical_the_prefix_decides(live):
    base, _studio, store, _job = live
    _s, r = post(base + "/api/jobs", {
        "creative_name": "n-LIPIL078_ch-fb_t-video_c-x_pr-lp_ds-nano_w-34_s-1080x1350",
        "reference": str(store.job_dir(_job.id) / "ref")})
    assert store.load(r["id"]).intake["vertical"] == "lipedema_pilates"


def test_the_dialog_keeps_a_hand_picked_vertical(live):
    """Re-parsing the name must not quietly put the derived one back."""
    from fjor_studio.dashboard.page import PAGE
    assert "VERTICAL_TOUCHED=true" in PAGE
    assert "!VERTICAL_TOUCHED" in PAGE


def test_the_dialog_warns_when_the_vertical_and_the_prefix_disagree():
    """Not an error, but the file would land somewhere its own name does not
    suggest -- the id comes from the name, the folder from the vertical."""
    from fjor_studio.dashboard.page import PAGE
    assert "checkVertical" in PAGE
    assert "will deliver into the" in PAGE


# -- polling must not fight the person using the page ------------------------
#
# These are structural checks on the page script. They cannot prove playback
# continues -- that was verified in a browser, where a forced re-render left the
# draft player at 20.0s on the same element -- but each one pins a specific
# regression that actually happened.

def test_the_draft_player_is_mounted_not_re_emitted():
    """Re-emitting `<video src=…>` on every poll destroyed the element, so the
    draft restarted from zero every four seconds and could not be watched
    through."""
    from fjor_studio.dashboard.page import PAGE
    assert 'id="draftSlot"' in PAGE
    assert "mountDraft(" in PAGE
    body = PAGE.split("function renderMain")[1].split("function mountDraft")[0]
    assert "<video class=\"draft\"" not in body, \
        "the draft player is being written into the markup again"


def test_a_poll_that_changes_nothing_does_not_re_render():
    from fjor_studio.dashboard.page import PAGE
    body = PAGE.split("async function refresh()")[1].split("function pillClass")[0]
    assert "signature(DETAIL)" in body
    assert "if(sig!==LAST_RENDER)" in body
    assert "LAST_SIDE" in body


def test_selecting_a_job_always_paints():
    """The skip must not make a click do nothing."""
    from fjor_studio.dashboard.page import PAGE
    body = PAGE.split("async function select(id)")[1].split("function track(")[0]
    assert "renderMain()" in body
    assert "DRAFT_NODE=null" in body      # a different job means a different cut


def test_an_action_forces_the_next_render():
    from fjor_studio.dashboard.page import PAGE
    body = PAGE.split("async function act(")[1].split("function openApprove")[0]
    assert "LAST_RENDER=null" in body


def test_open_panels_survive_a_render():
    from fjor_studio.dashboard.page import PAGE
    assert "details[open]" in PAGE
    assert "openCards" in PAGE


# -- finals and variations on the page ---------------------------------------

def _finish(base, studio, job_id):
    post(f"{base}/api/jobs/{job_id}/run"); wait(studio, job_id)
    post(f"{base}/api/jobs/{job_id}/approve"); wait(studio, job_id)
    post(f"{base}/api/jobs/{job_id}/approve"); wait(studio, job_id, seconds=180)
    _s, d = get(f"{base}/api/jobs/{job_id}")
    assert d["state"] == "done", d.get("error")
    return d


def test_the_finals_are_served_from_the_job_not_only_the_week_folder(live):
    base, studio, _store, job = live
    d = _finish(base, studio, job.id)
    assert d["finals"], "no finals exposed to the page"
    for f in d["finals"]:
        assert f["file"].startswith("n-")
        status, headers, body = _raw(f"{base}/media/{job.id}/{f['rel']}")
        assert status == 200 and headers["Content-Type"] == "video/mp4"
        assert len(body) > 0


def test_each_final_carries_what_it_is(live):
    base, studio, _store, job = live
    d = _finish(base, studio, job.id)
    f = d["finals"][0]
    assert f["format"] in ("9:16", "4:5")
    assert f["duration_s"] > 0
    assert f["actual"] == [1080, 1920]


def test_a_finished_job_offers_every_starting_point_with_a_price(live):
    base, studio, _store, job = live
    d = _finish(base, studio, job.id)
    opts = {o["from"]: o for o in d["derive"]}
    assert set(opts) == {"assembly", "clips", "plates", "prompts"}
    assert opts["assembly"]["cost"] == 0            # a re-cut is ffmpeg
    assert opts["clips"]["cost"] > 0
    assert opts["plates"]["cost"] > opts["clips"]["cost"]
    assert d["next_id"]


def test_an_unfinished_job_offers_none(live):
    base, studio, _store, job = live
    post(f"{base}/api/jobs/{job.id}/run"); wait(studio, job.id)
    _s, d = get(f"{base}/api/jobs/{job.id}")
    assert d["state"] == "GATE_PLATES"
    assert d["derive"] == []


def test_a_variation_is_created_over_http_and_inherits_the_reference(live):
    base, studio, store, job = live
    _finish(base, studio, job.id)
    _s, r = post(f"{base}/api/jobs/{job.id}/derive", {
        "creative_name":
            "n-LIPIL930_ch-fb_t-video_c-variant_pr-lp_ds-nano_w-34_s-1080x1350",
        "from": "assembly", "note": "swap the bed"})
    assert r["id"] == "LIPIL930"
    child = store.load("LIPIL930")
    assert child.state == "assembly"
    assert child.meta["derived_from"] == job.id
    assert list((store.job_dir("LIPIL930") / "ref").glob("*"))
    assert "swap the bed" in child.intake["brief"]
    _s, parent = get(f"{base}/api/jobs/{job.id}")
    assert "LIPIL930" in parent["derivatives"]


def test_a_variation_needs_its_own_name(live):
    base, studio, _store, job = live
    _finish(base, studio, job.id)
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(f"{base}/api/jobs/{job.id}/derive",
             {"creative_name": "not-a-name", "from": "assembly"})
    assert exc.value.code == 400


def test_the_page_has_a_variation_button_and_final_players():
    from fjor_studio.dashboard.page import PAGE
    assert "openDerive()" in PAGE
    assert 'video class="final"' in PAGE
    assert "download=" in PAGE


# -- starting it without me --------------------------------------------------

def test_there_is_a_double_clickable_launcher():
    """The server kept dying between sessions and needed someone to restart it
    from a shell."""
    import os
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    cmd = root / "FJOR Studio.command"
    assert cmd.exists(), "no double-clickable launcher"
    assert os.access(cmd, os.X_OK), "launcher is not executable"
    body = cmd.read_text()
    assert "dashboard.sh" in body
    assert "already running" in body          # a second launch is harmless


def test_the_launcher_refuses_to_fight_for_the_port():
    """A second instance used to bind-fail with a bare traceback."""
    from pathlib import Path
    sh = (Path(__file__).resolve().parents[1] / "scripts" / "dashboard.sh").read_text()
    assert "already serving" in sh
    assert "127.0.0.1:$PORT" in sh


# -- the editor --------------------------------------------------------------

def test_the_editor_is_offered_only_where_there_are_shots_to_arrange(live):
    base, studio, _store, job = live
    _s, d = get(f"{base}/api/jobs/{job.id}")
    assert d["edit"]["open"] is False              # nothing generated yet
    post(f"{base}/api/jobs/{job.id}/run")
    wait(studio, job.id)
    post(f"{base}/api/jobs/{job.id}/approve")      # through GATE_PLATES
    wait(studio, job.id)
    _s, d = get(f"{base}/api/jobs/{job.id}")
    assert d["state"] == "GATE_DRAFT"
    assert d["edit"]["open"] is True
    assert d["edit"]["order"] == [0, 1]
    assert d["edit"]["dropped"] == []
    assert isinstance(d["edit"]["music_library"], list)
    # a control that does nothing is worse than no control: only `bold-pop` is
    # implemented, so no style picker is offered
    assert "subtitle_styles" not in d["edit"]


def test_an_edit_posted_over_http_re_cuts_the_draft(live):
    base, studio, store, job = live
    post(f"{base}/api/jobs/{job.id}/run")
    wait(studio, job.id)
    post(f"{base}/api/jobs/{job.id}/approve")
    wait(studio, job.id)
    before = json.loads((store.job_dir(job.id) / "draft"
                         / "edit_manifest.json").read_text())
    spent_before = get(f"{base}/api/jobs/{job.id}")[1]["spent"]

    status, body = post(f"{base}/api/jobs/{job.id}/edit", {"edit": {"order": [1, 0]}})
    assert status == 200 and body["queued"] == "edit"
    wait(studio, job.id)

    _s, d = get(f"{base}/api/jobs/{job.id}")
    assert d["state"] == "GATE_DRAFT"              # re-cut, back to the same gate
    assert d["edit"]["order"] == [1, 0]
    after = json.loads((store.job_dir(job.id) / "draft"
                        / "edit_manifest.json").read_text())
    names = lambda m: [s["source"].split("/")[-1] for s in m["segments"]
                       if s["role"] == "clip"]
    assert names(after) == list(reversed(names(before)))
    assert d["spent"] == pytest.approx(spent_before)   # a re-cut buys nothing


def test_a_rejected_edit_answers_with_the_reason_and_changes_nothing(live):
    base, studio, _store, job = live
    post(f"{base}/api/jobs/{job.id}/run")
    wait(studio, job.id)
    post(f"{base}/api/jobs/{job.id}/approve")
    wait(studio, job.id)
    post(f"{base}/api/jobs/{job.id}/edit", {"edit": {"order": [0, 7]}})
    wait(studio, job.id)
    _s, d = get(f"{base}/api/jobs/{job.id}")
    assert d["state"] == "GATE_DRAFT"
    assert d["edit"]["order"] == [0, 1]
    failed = [a for a in get(base + "/api/state")[1]["activity"]
              if a["job_id"] == job.id and a["state"] == "failed"]
    assert failed and "7" in failed[0]["detail"]


def test_the_page_has_no_dead_click_handlers():
    """The sibling of the dead-selector test above. A button whose onclick names
    a function that does not exist renders, highlights, depresses -- and does
    nothing, with the error going to a console nobody has open. That is exactly
    what a producer reports as 'the arrows do nothing', so it is worth a check
    that cannot be argued with."""
    import re as _re
    from fjor_studio.dashboard.page import PAGE
    # every on*= attribute, not a hand-listed few: the strip's gesture moved
    # from onclick to onpointerdown/onkeydown, and a check that only knew about
    # clicks would have stopped covering the very control that prompted it
    called = set(_re.findall(r'\son[a-z]+="([A-Za-z_][A-Za-z0-9_]*)\(', PAGE))
    defined = set(_re.findall(r'function ([A-Za-z_][A-Za-z0-9_]*)\(', PAGE))
    defined |= set(_re.findall(r'(?:const|let|var) ([A-Za-z_][A-Za-z0-9_]*)\s*=\s*'
                              r'(?:async\s*)?\(', PAGE))
    defined |= {"select"}          # defined as `async function select(id)`
    missing = called - defined
    assert not missing, f"wired to a function that does not exist: {sorted(missing)}"


def test_the_strip_is_dragged_with_pointer_events_not_html5_dnd():
    """HTML5 drag-and-drop cannot be driven by synthetic input, so a strip built
    on it cannot be verified end to end -- and an unverifiable gesture is how
    the arrow buttons shipped looking dead. Pointer events also give touch and
    trackpad for free. Dragging the real strip with a real mouse was checked in
    the browser: reorder, drag to the tray, drag back in."""
    from fjor_studio.dashboard.page import PAGE
    assert "onpointerdown=" in PAGE
    assert 'draggable="true"' not in PAGE          # the two would fight
    assert "ondragstart" not in PAGE or 'ondragstart="return false"' in PAGE
    for fn in ("shotDown", "shotMove", "shotUp", "endDrag", "placeShot"):
        assert f"function {fn}(" in PAGE
    # the gesture must survive a mouse released outside the strip, and a press
    # that never moved must stay a click
    assert "pointercancel" in PAGE and "DRAG_SLOP" in PAGE
    # setPointerCapture throws on an id it does not know, inside the handler --
    # the CALL, not the comment explaining why it is not made
    assert "setPointerCapture(" not in PAGE
    # keyboard, because a strip you can only drag is a strip some people cannot use
    assert "ArrowLeft" in PAGE and "function shotKey(" in PAGE


def test_the_shot_strip_is_recognisable_and_says_when_the_cut_is_stale():
    """Five identical boxes are not an editor: reordering them is invisible, and
    the player above keeps the old cut until the edit is applied, which reads as
    the buttons doing nothing."""
    from fjor_studio.dashboard.page import PAGE
    assert 'class="thumb"' in PAGE            # a shot you can recognise
    assert "flashShot(" in PAGE               # a move you can follow
    assert "This is the <b>old</b> cut" in PAGE
    assert ".shot.ghost{" in PAGE             # something follows the pointer
    assert ".shot.dropL{" in PAGE and ".shot.dropR{" in PAGE   # where it lands
    assert 'class="tray"' in PAGE             # somewhere to drop it out of the cut


# -- access: the dashboard is a spend button ---------------------------------

@pytest.fixture
def guarded(home, reference):
    """The same server, with a token configured."""
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed", text=scene_plan(2),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": json.dumps({"passed": True, "severity": "ok"})})
    cfg, store, _engine = open_studio(home)
    job = make_job(store, reference, scenes=2, config=cfg)
    studio = Studio(home)
    from fjor_studio.dashboard.server import make_handler as mh
    server = ThreadingHTTPServer(("127.0.0.1", 0), mh(studio, "s3cret-token"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    yield base, studio, store, job
    server.shutdown()
    server.server_close()


def raw(url, headers=None, method="GET"):
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode(), dict(r.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(), dict(exc.headers)


def test_without_a_token_nothing_is_served(guarded):
    base, _studio, _store, job = guarded
    for path in ("/", "/api/state", f"/api/jobs/{job.id}", f"/media/{job.id}/ref/x.mp4"):
        status, body, _h = raw(base + path)
        assert status == 401, f"{path} answered {status}"
        assert "token" in body.lower()


def test_a_post_without_a_token_does_not_run_the_action(guarded):
    base, studio, _store, job = guarded
    req = urllib.request.Request(f"{base}/api/jobs/{job.id}/run", data=b"{}",
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        raise AssertionError("the run was accepted without a token")
    except urllib.error.HTTPError as exc:
        assert exc.code == 401
    assert not studio.worker.queued_for(job.id)     # nothing was queued


def test_the_token_works_as_a_header(guarded):
    base, _studio, _store, _job = guarded
    status, _b, _h = raw(base + "/api/state", {"X-Studio-Token": "s3cret-token"})
    assert status == 200


def test_a_wrong_token_is_refused(guarded):
    base, _studio, _store, _job = guarded
    status, _b, _h = raw(base + "/api/state", {"X-Studio-Token": "s3cret-toker"})
    assert status == 401


def test_the_link_form_is_exchanged_for_a_cookie_and_redirected_away(guarded):
    """So the token stops travelling in URLs the moment it has been used once."""
    base, _studio, _store, _job = guarded
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *a, **kw):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    try:
        opener.open(base + "/?token=s3cret-token", timeout=10)
        raise AssertionError("expected a redirect")
    except urllib.error.HTTPError as exc:
        assert exc.code == 302
        assert exc.headers["Location"] == "/"
        cookie = exc.headers["Set-Cookie"]
        assert "s3cret-token" in cookie
        assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    # and the cookie alone then works
    status, _b, _h = raw(base + "/api/state", {"Cookie": "fjor_token=s3cret-token"})
    assert status == 200


def test_a_wrong_token_in_the_query_is_not_exchanged(guarded):
    base, _studio, _store, _job = guarded
    status, _b, _h = raw(base + "/?token=nope")
    assert status == 401


def test_serving_off_loopback_without_a_token_is_refused(home):
    """The failure that matters is the silent one: binding 0.0.0.0 and finding
    out later that anyone on the network could approve a gate."""
    from fjor_studio.dashboard.server import serve
    write_config(home)
    with pytest.raises(SystemExit) as exc:
        serve(home, host="0.0.0.0", port=0)
    assert "token" in str(exc.value).lower()
    assert "credits" in str(exc.value).lower()


def test_loopback_still_needs_no_token(live):
    """Nothing changes for a producer running it on their own machine."""
    base, _studio, _store, _job = live
    status, _b, _h = raw(base + "/api/state")
    assert status == 200


def test_the_token_comes_from_the_environment_or_auth_yaml(home, monkeypatch):
    from fjor_studio.dashboard.server import resolve_token
    write_config(home)
    cfg, _s, _e = open_studio(home)
    monkeypatch.delenv("FJOR_STUDIO_TOKEN", raising=False)
    assert resolve_token(cfg) == ""
    cfg.auth["dashboard"] = {"token": "from-auth"}
    assert resolve_token(cfg) == "from-auth"
    monkeypatch.setenv("FJOR_STUDIO_TOKEN", "from-env")
    assert resolve_token(cfg) == "from-env"          # the environment wins
    assert resolve_token(cfg, "explicit") == "explicit"


def test_the_token_is_never_printed_by_config(home, monkeypatch):
    """`config` is the command people paste into chat threads."""
    write_config(home)
    cfg, _s, _e = open_studio(home)
    cfg.auth["dashboard"] = {"token": "s3cret-token"}
    assert "s3cret-token" not in json.dumps(cfg.redacted())


def test_the_bed_picker_groups_by_folder_and_keeps_a_legacy_name(live):
    """109 beds flat is not a picker. And a job recorded before the library was
    filed carries a bare name that is no longer in the list -- dropping it would
    silently clear the bed on the next re-cut."""
    from fjor_studio.dashboard.page import PAGE
    assert "function musicOptions(" in PAGE
    assert "<optgroup" in PAGE
    assert "(as recorded)" in PAGE          # not "missing": it still resolves
    # both pickers go through it rather than building their own list
    assert PAGE.count("musicOptions(") >= 3


def test_the_launcher_asks_the_server_a_question_not_the_port():
    """A server can hold the port and be unable to read its own config -- that
    is what happened on 2026-08-27. A launcher that only checks whether the port
    answers reports "already running" and opens a dashboard where nothing works,
    which is worse than saying nothing."""
    import pathlib
    launcher = (pathlib.Path(__file__).resolve().parents[1]
                / "FJOR Studio.command").read_text()
    assert "/api/state" in launcher            # a real question
    assert "cannot answer for itself" in launcher
    assert "stop_it" in launcher               # and it takes over
    # it must never kill something that is not ours
    assert "*fjor_studio*" in launcher
    assert "is held by something that is not FJOR Studio" in launcher


def test_the_restart_launcher_reuses_the_one_launcher():
    """Two copies of this logic would drift, and the copy nobody runs is the
    one that stays broken."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    restart = (root / "Restart FJOR Studio.command").read_text()
    assert "FJOR_STUDIO_RESTART=1" in restart
    assert "./FJOR Studio.command" in restart
    assert "FJOR_STUDIO_RESTART" in (root / "FJOR Studio.command").read_text()


# -- the new features on the page --------------------------------------------

def test_a_dropped_banner_is_recognised_and_its_expansion_measured(live, tmp_path):
    """The dialog has to be able to SAY which pipeline is about to run, before
    anything is created. Their tool toasts it for the same reason: the two modes
    look alike from the outside and mixing them wastes a whole generation."""
    from conftest import a_banner
    base, *_ = live
    status, out = _upload(base, "banner.png",
                          a_banner(tmp_path / "b.png").read_bytes())
    assert status == 200
    assert out["kind"] == "banner"
    assert (out["width"], out["height"]) == (1080, 1080)
    assert out["expansion"] == {"top": 420, "bottom": 420}
    assert "duration_s" not in out           # an image has none, so none is claimed


def test_a_dropped_video_is_still_a_reference(live, tmp_path):
    base, *_ = live
    status, out = _upload(base, "ref.mp4",
                          _real_video(tmp_path).read_bytes())
    assert status == 200 and out["kind"] == "reference"
    assert out["duration_s"] > 0


def test_creating_from_a_banner_makes_a_banner_job(live, tmp_path):
    from conftest import a_banner
    base, studio, store, _job = live
    _s, up = _upload(base, "banner.png", a_banner(tmp_path / "b.png").read_bytes())
    _s, made = post(base + "/api/jobs", {
        "creative_name": "n-LIPIL301_ch-fb_t-video_c-banner_pr-lp_ds-nano_w-34_s-1080x1350",
        "banner": up["path"]})
    intake = store.load(made["id"]).intake
    assert intake["banner"] == up["path"]
    assert "reference" not in intake          # two pipelines, never both


def test_the_transformation_and_the_card_reach_the_job(live, tmp_path):
    base, _studio, store, _job = live
    _s, up = _upload(base, "ref.mp4", _real_video(tmp_path).read_bytes())
    _s, made = post(base + "/api/jobs", {
        "creative_name": "n-LIPIL302_ch-fb_t-video_c-morph_pr-lp_ds-nano_w-34_s-1080x1350",
        "reference": up["path"],
        "morph": "her posture straightens and the swelling goes down",
        "text_card": "5 minutes a day"})
    intake = store.load(made["id"]).intake
    assert intake["morph"].startswith("her posture")
    assert intake["text_card"] == "5 minutes a day"


def test_a_driver_is_registered_and_attached_in_one_action(live, tmp_path):
    """Splitting them would let a producer leave a driver attached to nothing --
    or pass the plan gate with the shots not yet retimed to the driver."""
    base, studio, store, job = live
    _s, up = _upload(base, "driver.mp4", _real_video(tmp_path, seconds=2).read_bytes())
    post(base + f"/api/jobs/{job.id}/run")
    wait(studio, job.id)
    _s, out = post(base + f"/api/jobs/{job.id}/driver",
                   {"source": up["path"], "engine": "kling-mc-3.0",
                    "note": "the sit-up", "scenes": [0]})
    assert out["queued"] == "driver"
    wait(studio, job.id)
    job = store.load(job.id)
    drivers = job.meta["drivers"]
    assert len(drivers) == 1 and drivers[0]["engine"] == "kling-mc-3.0"
    assert job.scenes[0]["driver"] == drivers[0]["id"]
    # Motion Control runs exactly as long as the driver, so the shot was retimed
    assert job.scenes[0]["duration_s"] == drivers[0]["duration_s"]
    assert job.scenes[1].get("driver") in (None, "")


def test_a_driver_attached_to_no_shot_is_refused(live, tmp_path):
    base, studio, store, job = live
    _s, up = _upload(base, "driver.mp4", _real_video(tmp_path).read_bytes())
    post(base + f"/api/jobs/{job.id}/run")
    wait(studio, job.id)
    post(base + f"/api/jobs/{job.id}/driver", {"source": up["path"], "scenes": []})
    wait(studio, job.id)
    assert not store.load(job.id).meta.get("drivers")


def test_the_page_offers_the_new_controls():
    from fjor_studio.dashboard.page import PAGE
    for needle in ("Add a driver…", "Motion drivers", "Transformation on camera",
                   "Text card in the reference", "Banner mode", "the banner survived",
                   "openDriver()", "/driver"):
        assert needle in PAGE, needle


# -- a blocked job is decidable, on the page ---------------------------------

def _blocked(home, reference):
    """A job stopped by preflight on a critical clip verdict."""
    critical = json.dumps({"passed": False, "severity": "critical",
                           "issues": ["body-type mismatch"],
                           "summary": "wrong build"})
    write_config(home, pipeline={"gates": {"skip": ["GATE_PLAN", "GATE_CLIPS"]}})
    write_replies(home, analysis="analysed", text=scene_plan(2),
                  **{"qa:plate": json.dumps({"passed": True, "severity": "ok"}),
                     "qa:clip": critical})
    cfg, store, engine = open_studio(home)
    job = make_job(store, reference, scenes=2, config=cfg)
    job = engine.approve(engine.approve(engine.approve(engine.run(job))))
    return cfg, store, engine, job


def test_a_blocked_job_reports_which_shots_and_stays_at_the_gate(live, home, reference):
    base, studio, _s, _j = live
    _cfg, store, _engine, job = _blocked(home, reference)
    _st, d = get(f"{base}/api/jobs/{job.id}")
    assert d["state"] == "GATE_DRAFT"        # not 'failed': it is decidable here
    assert d["blocking"] == [0, 1]
    assert "waive" in d["error"] and "revise" in d["error"]
    # and the still can be re-bought from here, not only the animation
    assert "plates" in d["revisable"] and "clip" in d["revisable"]


def test_waiving_from_the_page_ships_it_and_keeps_the_finding(live, home, reference):
    base, studio, _s, _j = live
    _cfg, store, _engine, job = _blocked(home, reference)
    post(f"{base}/api/jobs/{job.id}/waive",
         {"scenes": [0, 1], "note": "checked both; ships"})
    wait(studio, job.id)
    post(f"{base}/api/jobs/{job.id}/approve")
    wait(studio, job.id)
    job = store.load(job.id)
    assert job.state == "done"
    # accepted, not deleted
    assert job.scenes[0]["clip_qa"]["severity"] == "critical"


def test_the_page_offers_both_ways_past_a_block():
    from fjor_studio.dashboard.page import PAGE
    for needle in ("Blocking the delivery", "Accept and ship", "Buy it again",
                   "openWaive()", "there is no accept-all",
                   "not repaired by buying the animation"):
        assert needle in PAGE, needle


# -- keys arrive with the producer -------------------------------------------

def test_the_page_is_told_which_providers_answered_and_never_a_value(live):
    base, *_ = live
    _st, d = get(base + "/api/state")
    keys = d["options"]["keys"]
    assert set(keys) == {"source", "providers"}
    assert all(isinstance(p, str) for p in keys["providers"])
    # the whole page, searched for anything key-shaped
    with urllib.request.urlopen(base + "/", timeout=10) as r:
        page = r.read().decode()
    assert "api_key" not in page


def test_a_kit_is_read_into_memory_and_never_written_to_disk(live, tmp_path):
    base, studio, _s, _j = live
    cfg, _store, _engine = studio.open()
    before = {p for p in cfg.home.rglob("*") if p.is_file()}
    secret = "SK-KIT-DO-NOT-PERSIST-0001"
    req = urllib.request.Request(
        base + "/api/kit",
        data=json.dumps({"kie": {"api_key": secret}}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        assert json.loads(r.read().decode())["providers"] == ["kie"]
    after = {p for p in cfg.home.rglob("*") if p.is_file()}
    for path in after:
        try:
            assert secret not in path.read_text(errors="ignore"), path
        except (UnicodeDecodeError, IsADirectoryError):
            pass
    assert after == before, "a kit upload created a file"
    # and the studio can now see the key it was given
    from fjor_studio import kit as kit_mod
    assert kit_mod.providers() == ["kie"]
    kit_mod.clear()


def test_a_kit_with_nothing_usable_is_refused_rather_than_loaded_empty(live):
    base, *_ = live
    req = urllib.request.Request(
        base + "/api/kit", data=json.dumps({"nonsense": 1}).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=10)
    assert exc.value.code == 400
    assert "no usable API keys" in exc.value.read().decode()


def test_the_page_says_plainly_when_there_are_no_keys():
    from fjor_studio.dashboard.page import PAGE
    for needle in ("No API keys", "Load a kit", "never written to disk",
                   "renderKit()", "/api/kit"):
        assert needle in PAGE, needle


# -- the delivery folder, set from the page ----------------------------------

def test_the_page_is_told_where_finals_land_and_whether_it_can_work(live):
    base, *_ = live
    _st, d = get(base + "/api/state")
    dl = d["options"]["delivery"]
    assert dl["set"] is True and dl["problem"] == ""
    # an example is worth more than a description
    assert "34 week" in dl["example"]


def test_an_unset_root_is_reported_as_a_setting_not_a_crash(tmp_path, reference):
    """A producer on a new machine should meet this as something to fill in.
    The pipeline still refuses to START a job -- that check is at intake, before
    anything is bought -- but they should never have to discover it that way."""
    import yaml
    home = tmp_path / "h"
    write_config(home)
    delivery = home / "config" / "delivery.yaml"
    raw = yaml.safe_load(delivery.read_text())
    raw["root"] = ""
    delivery.write_text(yaml.safe_dump(raw))
    studio = Studio(home)
    status = studio.delivery_status()
    assert status["set"] is False and status["root"] == ""
    assert status["week_folder"]          # still says what the shape will be


def test_setting_the_root_from_the_page_keeps_the_file_s_comments(live, tmp_path):
    """A whole-file rewrite through a YAML dumper would throw away every comment
    in delivery.yaml, and those comments are the only explanation of the naming
    template a deployer gets."""
    base, studio, _s, _j = live
    cfg, _store, _engine = studio.open()
    path = cfg.home / "config" / "delivery.yaml"
    # the fixture writes this file through a dumper, so give it the comments a
    # real one has, and check they are all still there afterwards
    path.write_text("# how finals are named and where they go\n"
                    "# week_folder must contain {week}\n" + path.read_text())
    before = path.read_text()
    target = tmp_path / "somewhere else"
    target.mkdir()
    _st, out = post(base + "/api/delivery", {"root": str(target)})
    assert out["set"] is True and out["root"] == str(target)
    after = path.read_text()
    assert after.count("#") == before.count("#")
    assert "how finals are named" in after
    assert str(target) in after


def test_a_week_folder_without_the_week_is_refused(live, tmp_path):
    """Every week of every vertical would deliver into one directory."""
    base, *_ = live
    target = tmp_path / "root"
    target.mkdir()
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base + "/api/delivery",
             {"root": str(target), "week_folder": "weekly"})
    assert exc.value.code == 400
    assert "{week}" in exc.value.read().decode()


def test_a_root_whose_parent_is_missing_is_refused(live):
    """That is what separates 'nothing has shipped yet' from a typo, or a
    network volume nobody mounted."""
    base, *_ = live
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(base + "/api/delivery", {"root": "/no/such/place/VIDEO"})
    assert exc.value.code == 400
    assert "does not exist" in exc.value.read().decode()


def test_the_page_offers_the_setting_rather_than_only_the_error():
    from fjor_studio.dashboard.page import PAGE
    for needle in ("No delivery folder yet", "Set the delivery folder…",
                   "renderSetup()", "/api/delivery", "It can be ANY folder"):
        assert needle in PAGE, needle


def test_a_studio_with_no_keys_can_still_be_opened_and_looked_at(tmp_path):
    """The bug a shipped zip exposed: backends were built when a studio was
    OPENED, so a fresh deploy with no keys could not render the dashboard at
    all -- and the controls that load the keys and set the delivery folder were
    both on that page. A key is needed to RUN a job, not to look at one."""
    import yaml
    home = tmp_path / "h"
    write_config(home)                      # no auth.yaml at all
    (home / "config" / "models.yaml").write_text(yaml.safe_dump({
        "providers": {"analysis": "gemini", "text": "gemini", "image": "kie",
                      "video": "kie", "speech": "gemini"}}))
    studio = Studio(home)
    assert studio.overview()["jobs"] == []          # renders
    assert studio.delivery_status()["set"] in (True, False)
    from fjor_studio import kit as kit_mod
    kit_mod.clear()


def test_but_a_missing_key_still_stops_a_job_before_anything_is_bought(tmp_path,
                                                                      reference):
    """The protection laziness could have cost. Same guarantee, same moment."""
    import yaml
    from fjor_studio.gen.base import GenError
    home = tmp_path / "h"
    write_config(home)
    (home / "config" / "models.yaml").write_text(yaml.safe_dump({
        "providers": {"analysis": "gemini", "text": "gemini", "image": "kie",
                      "video": "kie", "speech": "gemini"}}))
    cfg, store, engine = open_studio(home)
    job = make_job(store, reference, scenes=1, config=cfg)
    job = engine.run(job)
    assert job.state == "failed"
    assert "api_key" in job.error and "intake" in job.error
    assert job.spent == 0                           # nothing was bought
    assert "Load a kit" in job.error                # and it says what to do


# -- retiring a job, and getting its id back ---------------------------------

def test_deleting_a_job_frees_its_id_and_unlinks_nothing(live):
    """A cancelled attempt still holds its number, which is the usual reason to
    want this. Nothing is destroyed: the job moves to jobs/_deleted/."""
    base, studio, store, job = live
    cfg, _s, _e = studio.open()
    assert job.id in store.list_ids()
    _st, out = post(f"{base}/api/jobs/{job.id}/delete")
    assert out["id"] == job.id
    assert job.id not in store.list_ids()             # the id is free again
    moved = pathlib.Path(out["moved_to"])
    assert moved.is_dir() and (moved / "job.json").is_file()
    assert "_deleted" in str(moved)


def test_a_running_job_is_not_deleted_out_from_under_itself(live, monkeypatch):
    """Removing a directory mid-stage loses a generation that may already be
    paid for."""
    base, studio, _store, job = live
    monkeypatch.setattr(studio.worker, "queued_for", lambda _id: "run")
    with pytest.raises(urllib.error.HTTPError) as exc:
        post(f"{base}/api/jobs/{job.id}/delete")
    assert exc.value.code == 400
    assert "Cancel it first" in exc.value.read().decode()


def test_the_page_offers_it_and_says_what_it_costs():
    from fjor_studio.dashboard.page import PAGE
    for needle in ("Delete…", "deleteJob()", "free its id", "recoverable"):
        assert needle in PAGE, needle
