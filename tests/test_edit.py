"""GATE_CLIPS and the editor that lives on it.

The rest of the suite skips this gate (see conftest) because it was written
before the gate existed. Everything about it is therefore proven here: that the
shipped config stops at it, that the edit reaches ffmpeg, and that a cut which
lost a shot cannot be delivered against stale subtitle timings.
"""
import json

import pytest
import yaml

from conftest import make_job, scene_plan, write_config, write_replies
from fjor_studio.app import open_studio
from fjor_studio.assemble import duration_of
from fjor_studio.engine import TransitionError
from pathlib import Path

from fjor_studio.stages.steps import cut_scenes, edit_of


def qa_ok():
    return json.dumps({"passed": True, "severity": "ok", "issues": [],
                       "summary": "fine"})


def setup(home, reference, scenes=3, skip=("GATE_PLAN",), **kw):
    """A job at GATE_CLIPS, with the gate ON."""
    pipeline = {"gates": {"skip": list(skip)}, "delivery": {"formats": ["9:16"]}}
    pipeline.update(kw)
    write_config(home, pipeline=pipeline)
    write_replies(home, text=scene_plan(scenes), analysis="analysed",
                  **{"qa:plate": qa_ok(), "qa:clip": qa_ok()})
    cfg, store, engine = open_studio(home)
    job = make_job(store, reference, scenes=scenes, config=cfg, packshot="formula")
    return cfg, store, engine, job


# -- the gate ---------------------------------------------------------------

def test_the_run_stops_on_the_shots_before_it_cuts_them(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))          # past GATE_PLATES
    assert job.state == "GATE_CLIPS"
    assert all(s["clip"] for s in job.scenes)      # the shots exist
    assert not (store.job_dir(job.id) / "draft" / "draft.mp4").exists()


def test_the_gate_writes_the_shots_and_their_verdicts(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    review = json.loads((store.job_dir(job.id) / "review" / "clips.json").read_text())
    assert [c["idx"] for c in review["clips"]] == [0, 1, 2]
    assert all(c["qa"] for c in review["clips"])
    assert all(c["in_cut"] for c in review["clips"])


def test_approving_it_cuts_the_draft(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    assert job.state == "GATE_DRAFT"
    assert (store.job_dir(job.id) / "draft" / "draft.mp4").exists()


def test_a_config_may_skip_it_because_everything_after_is_free(home, reference):
    _cfg, _store, engine, job = setup(home, reference,
                                      skip=("GATE_PLAN", "GATE_CLIPS"))
    job = engine.approve(engine.run(job))
    assert job.state == "GATE_DRAFT"
    assert any("GATE_CLIPS" in e.get("msg", "") for e in job.events
               if e["type"] == "gate_skipped")


def test_the_shipped_config_stops_there():
    """The owner asked for this gate. A default that skips it would be the
    feature not existing."""
    import pathlib
    cfg = yaml.safe_load(
        (pathlib.Path(__file__).resolve().parents[1] / "config" / "pipeline.yaml")
        .read_text())
    assert "GATE_CLIPS" not in (cfg.get("gates") or {}).get("skip", [])


def test_a_bad_shot_is_re_bought_from_this_gate(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    before = job.scenes[1]["clip_attempts"]
    job = engine.revise(job, "clip", "she looks away from camera", scenes=[1])
    assert job.state == "GATE_CLIPS"                       # back to the same gate
    assert job.scenes[1]["clip_attempts"] == before + 1
    assert job.scenes[0]["clip_attempts"] == before        # the others untouched


def test_assembly_is_not_revisable_here_because_there_is_no_cut_yet(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    with pytest.raises(TransitionError):
        engine.revise(job, "assembly")


# -- the edit ---------------------------------------------------------------

def test_dropping_a_shot_shortens_the_cut(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    full = duration_of(store.job_dir(job.id) / "draft" / "draft.mp4")

    job = engine.set_edit(job, {"order": [0, 2]})
    assert job.state == "GATE_DRAFT"                       # re-cut, same gate
    short = duration_of(store.job_dir(job.id) / "draft" / "draft.mp4")
    assert short < full - 0.5
    assert [s["idx"] for s in cut_scenes(job)] == [0, 2]
    # the shot is dropped from the CUT, not deleted: it can be put back
    assert job.scenes[1]["clip"]


def test_a_dropped_shot_can_be_put_back(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    full = duration_of(store.job_dir(job.id) / "draft" / "draft.mp4")
    job = engine.set_edit(job, {"order": [0, 2]})
    job = engine.set_edit(job, {"order": [0, 1, 2]})
    assert duration_of(store.job_dir(job.id) / "draft" / "draft.mp4") == \
        pytest.approx(full, abs=0.15)


def test_reordering_reaches_the_cut(home, reference):
    """Scenes have different durations, so the running order is measurable at
    the join rather than only in the manifest."""
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    job = engine.set_edit(job, {"order": [2, 1, 0]})
    manifest = json.loads(
        (store.job_dir(job.id) / "draft" / "edit_manifest.json").read_text())
    clips = [s["source"].split("/")[-1] for s in manifest["segments"]
             if s["role"] == "clip"]
    assert clips == ["scene_02.mp4", "scene_01.mp4", "scene_00.mp4"]


def test_the_edit_survives_into_delivery(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    job = engine.set_edit(job, {"order": [1, 0]})
    job = engine.approve(job)
    assert job.state == "done"
    manifest = json.loads(
        (store.job_dir(job.id) / "finals" / "build_manifest.json").read_text())
    clips = [s["source"].split("/")[-1]
             for s in manifest["finals"][0]["segments"] if s["role"] == "clip"]
    assert clips == ["scene_01.mp4", "scene_00.mp4"]


def test_an_edit_at_the_clip_gate_waits_for_the_approval_that_cuts(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    job = engine.set_edit(job, {"order": [0, 2]})
    assert job.state == "GATE_CLIPS"                       # nothing to re-cut yet
    assert not (store.job_dir(job.id) / "draft" / "draft.mp4").exists()
    job = engine.approve(job)
    manifest = json.loads(
        (store.job_dir(job.id) / "draft" / "edit_manifest.json").read_text())
    assert len([s for s in manifest["segments"] if s["role"] == "clip"]) == 2


def a_real_bed():
    """The suite runs against the real asset library, so the bed has to be one
    that is actually in it -- a made-up name is refused, which is its own test
    below. The name is folder-qualified (`Calm/Kyoto`); the cut records the
    FILE it used, which is the leaf."""
    import pathlib
    from fjor_studio.assemble import list_music
    beds = list_music(pathlib.Path(__file__).resolve().parents[1] / "assets")
    if not beds:
        pytest.skip("no music beds in assets/")
    return beds[0]


def leaf(bed_name):
    return bed_name.rsplit("/", 1)[-1]


def test_the_music_bed_is_chosen_at_a_gate_not_in_the_brief(home, reference):
    bed = a_real_bed()
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    assert job.meta["draft"]["music"] is None              # the brief did not ask
    job = engine.set_edit(job, {"music": bed})
    assert job.state == "GATE_DRAFT"                       # the re-cut succeeded
    assert job.meta["draft"]["music"].startswith(leaf(bed))
    assert edit_of(job)["music"] == bed                    # the edit keeps the folder
    job = engine.set_edit(job, {"music": ""})
    assert job.meta["draft"]["music"] is None              # and can be taken off


def test_a_bed_that_is_not_in_the_library_fails_the_cut_loudly(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    job = engine.set_edit(job, {"music": "no-such-bed"})
    assert job.state == "failed"
    assert "no-such-bed" in job.error


def test_a_bed_named_in_the_brief_still_reaches_an_old_job(home, reference):
    """`intake.music` seeds the edit -- the CLI still offers --music, and a job
    made before the editor existed must not lose its bed on a re-cut."""
    bed = a_real_bed()
    _cfg, _store, engine, job = setup(home, reference)
    job.intake["music"] = bed
    job = engine.approve(engine.approve(engine.run(job)))
    assert job.meta["draft"]["music"].startswith(leaf(bed))
    assert edit_of(job)["music"] == bed
    job = engine.set_edit(job, {"music": ""})              # the gate overrides it
    assert job.meta["draft"]["music"] is None


def test_the_edit_overrides_the_configured_subtitle_settings(home, reference):
    """Burning them needs a live transcription key, so this checks the settings
    the burner is handed -- test_subtitles.py owns the rendering itself."""
    from fjor_studio.stages.steps import _subtitle_settings
    cfg, store, engine, job = setup(
        home, reference, subtitles={"enabled": True, "colour": "yellow",
                                    "size": "medium"})

    class Ctx:
        pass
    ctx = Ctx()
    ctx.config, ctx.job = cfg, job

    style, on = _subtitle_settings(ctx)
    assert on and style.colour == "yellow" and style.size == "medium"

    job.meta["edit"] = {"subtitles": {"colour": "white", "size": "large"}}
    style, on = _subtitle_settings(ctx)
    assert on and style.colour == "white" and style.size == "large"

    job.meta["edit"] = {"subtitles": {"enabled": False}}
    style, on = _subtitle_settings(ctx)
    assert (style, on) == (None, False)


# -- what the editor refuses ------------------------------------------------

def test_an_edit_that_drops_every_shot_is_refused(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    with pytest.raises(TransitionError):
        engine.set_edit(job, {"order": []})


def test_an_edit_naming_a_scene_that_does_not_exist_is_refused(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    with pytest.raises(TransitionError) as exc:
        engine.set_edit(job, {"order": [0, 9]})
    assert "9" in str(exc.value)


def test_an_edit_repeating_a_shot_is_refused(home, reference):
    """Not a nice-to-have: the same clip twice would be transcribed once and
    subtitled over both, which is a defect nobody would look for."""
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    with pytest.raises(TransitionError):
        engine.set_edit(job, {"order": [0, 0, 1]})


def test_an_unknown_edit_key_is_refused_rather_than_ignored(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    with pytest.raises(TransitionError):
        engine.set_edit(job, {"crossfade_s": 1.0})
    with pytest.raises(TransitionError):
        engine.set_edit(job, {"subtitles": {"colour": "yellow", "styel": "x"}})


def test_the_edit_cannot_be_set_while_a_stage_is_running(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.run(job)                                  # at GATE_PLATES
    job.state = "clips"
    with pytest.raises(TransitionError):
        engine.set_edit(job, {"order": [0]})


def test_the_edit_is_recorded_as_an_event(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.approve(engine.run(job))
    job = engine.set_edit(job, {"order": [2, 0], "music": "bed"})
    said = [e["msg"] for e in job.events if e["type"] == "edit"][-1]
    assert "2-0" in said and "dropped [1]" in said and "music bed" in said


# -- mute, and the bed's level ------------------------------------------------
#
# The first slice of finer editing. Both were parameters that already existed
# on the assembly side with nothing wired to them.

def _tone_clip(path, seconds=2.0):
    """A clip that actually carries sound, unlike the mock's silent ones."""
    import subprocess
    from fjor_studio.assemble import ffmpeg_with_libass
    subprocess.run(
        [ffmpeg_with_libass(), "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=c=0x334455:size=270x480:rate=25:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(path)], check=True, capture_output=True)
    return path


def _mean_volume_db(path):
    import re
    import subprocess
    from fjor_studio.assemble import _bin
    out = subprocess.run(
        [_bin("ffmpeg"), "-v", "info", "-i", str(path), "-af", "volumedetect",
         "-f", "null", "-"], capture_output=True, text=True).stderr
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", out)
    return float(m.group(1)) if m else -91.0      # silence reports nothing


def test_a_muted_shot_is_actually_silent(tmp_path):
    """Measured, not asserted from the manifest: the parameter existed for a
    long time with nothing calling it, so the proof is the audio."""
    from fjor_studio.assemble import SIZES, build_final
    loud = _tone_clip(tmp_path / "loud.mp4")
    ref = build_final([loud], tmp_path / "ref.mp4", SIZES["9:16"])
    muted = build_final([loud], tmp_path / "muted.mp4", SIZES["9:16"],
                        clip_mute=[True])
    assert _mean_volume_db(tmp_path / "ref.mp4") > -40
    assert _mean_volume_db(tmp_path / "muted.mp4") < -80
    assert muted["segments"][0]["muted"] is True
    assert ref["segments"][0]["muted"] is False


def test_mute_does_not_silence_a_separately_spoken_line(tmp_path):
    """The voice is a separate asset. Muting the SHOT must not take it away --
    that is what the design promised, and it is the whole reason the toggle
    shows disabled on those shots."""
    from fjor_studio.assemble import SIZES, build_final
    import subprocess
    from fjor_studio.assemble import ffmpeg_with_libass
    clip = _tone_clip(tmp_path / "clip.mp4")
    voice = tmp_path / "voice.wav"
    subprocess.run([ffmpeg_with_libass(), "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=220:duration=1.5", str(voice)],
                   check=True, capture_output=True)
    rep = build_final([clip], tmp_path / "out.mp4", SIZES["9:16"],
                      clip_audio=[str(voice)], clip_mute=[True])
    assert _mean_volume_db(tmp_path / "out.mp4") > -40
    assert rep["segments"][0]["muted"] is False       # says what happened


def test_mute_reaches_the_cut_through_the_edit(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    job = engine.set_edit(job, {"mute": [1]})
    manifest = json.loads(
        (store.job_dir(job.id) / "draft" / "edit_manifest.json").read_text())
    muted = [s["source"].split("/")[-1] for s in manifest["segments"]
             if s["role"] == "clip" and s.get("muted")]
    assert muted == ["scene_01.mp4"]
    assert edit_of(job)["mute"] == [1]


def test_mute_naming_a_missing_scene_is_refused(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.run(job)
    with pytest.raises(TransitionError, match="do not exist"):
        engine.set_edit(job, {"mute": [7]}, recut=False)


def test_the_bed_level_is_the_producers_at_a_gate(home, reference, tmp_path):
    """Config gives a default; the edit overrides it; the cut reports which."""
    import shutil
    _cfg, store, engine, job = setup(home, reference)
    beds = Path(_cfg.assets_dir) / "music bed" / "Test"
    if not beds.is_dir():
        beds.mkdir(parents=True)
    bed = beds / "tone.mp3"
    if not bed.exists():
        import subprocess
        from fjor_studio.assemble import ffmpeg_with_libass
        subprocess.run([ffmpeg_with_libass(), "-y", "-v", "error", "-f", "lavfi",
                        "-i", "sine=frequency=330:duration=8",
                        "-c:a", "libmp3lame", str(bed)],
                       check=True, capture_output=True)
    job = engine.approve(engine.approve(engine.run(job)))
    job = engine.set_edit(job, {"music": "Test/tone.mp3",
                                "music_volume": 0.6, "music_duck": False})
    rep = job.meta["draft"]
    assert rep["music"] == "tone.mp3"
    assert rep["music_volume"] == pytest.approx(0.6)
    assert rep["music_duck"] is False


def test_a_bed_level_outside_0_to_1_is_refused(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.run(job)
    with pytest.raises(TransitionError, match="fraction"):
        engine.set_edit(job, {"music_volume": 60}, recut=False)


def test_the_bed_hook_and_insert_survive_every_new_control(home, reference):
    """The owner's one condition for this work: the bed and the library inserts
    must not be lost along the way. Pinned here so a later change cannot drop
    them quietly."""
    from conftest import a_finished_cut
    from fjor_studio import library
    _cfg, store, engine, job = setup(home, reference)
    assets = Path(_cfg.assets_dir)
    hook = library.add_upload(assets, a_finished_cut(Path(home) / "h.mp4",
                                                    w=270, h=480, seconds=1), "Hook")
    ins = library.add_upload(assets, a_finished_cut(Path(home) / "i.mp4",
                                                   w=270, h=480, seconds=1), "Insert")
    job = engine.approve(engine.approve(engine.run(job)))
    job = engine.set_edit(job, {"hook": hook["id"], "insert": ins["id"]})
    # now every new control, on top
    job = engine.set_edit(job, {"mute": [0], "music_volume": 0.4,
                                "music_duck": True})
    e = edit_of(job)
    assert e["hook"] == hook["id"] and e["insert"] == ins["id"]
    roles = [s["role"] for s in job.meta["draft"]["segments"]]
    assert roles[0] == "hook" and "demo" in roles


# -- trim ----------------------------------------------------------------------

def _two_part_clip(path):
    """0–1s: a 440Hz tone. 1–2s: silence. So WHICH half survives a trim is
    audible, not just a duration."""
    import subprocess
    from fjor_studio.assemble import ffmpeg_with_libass
    subprocess.run(
        [ffmpeg_with_libass(), "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=0x334455:size=270x480:rate=25:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000:duration=1",
         "-filter_complex", "[1:a][2:a]concat=n=2:v=0:a=1[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(path)], check=True, capture_output=True)
    return path


def test_a_trim_shortens_the_shot_by_exactly_what_was_cut(tmp_path):
    from fjor_studio.assemble import SIZES, build_final
    clip = _two_part_clip(tmp_path / "c.mp4")
    whole = build_final([clip], tmp_path / "w.mp4", SIZES["9:16"])
    cut = build_final([clip], tmp_path / "t.mp4", SIZES["9:16"],
                      clip_trim=[(0.5, 1.5)])
    assert cut["segments"][0]["duration_s"] == pytest.approx(1.0, abs=0.1)
    assert whole["segments"][0]["duration_s"] == pytest.approx(2.0, abs=0.1)
    assert cut["segments"][0]["trim"] == [0.5, 1.5]


def test_the_in_point_really_seeks_it_is_not_just_a_length_cap(tmp_path):
    """`trim_s` alone was a length cap from the start. An in-point must move
    the START: keep the silent second half and the result is silent."""
    from fjor_studio.assemble import SIZES, build_final
    clip = _two_part_clip(tmp_path / "c.mp4")
    build_final([clip], tmp_path / "loud.mp4", SIZES["9:16"], clip_trim=[(0.0, 1.0)])
    build_final([clip], tmp_path / "quiet.mp4", SIZES["9:16"], clip_trim=[(1.0, 2.0)])
    assert _mean_volume_db(tmp_path / "loud.mp4") > -40
    assert _mean_volume_db(tmp_path / "quiet.mp4") < -80


def test_a_trim_reaches_the_cut_through_the_edit(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    full = duration_of(store.job_dir(job.id) / "draft" / "draft.mp4")
    job = engine.set_edit(job, {"trim": {"1": [0.0, 0.5]}})
    short = duration_of(store.job_dir(job.id) / "draft" / "draft.mp4")
    assert short < full - 0.3
    manifest = json.loads(
        (store.job_dir(job.id) / "draft" / "edit_manifest.json").read_text())
    trimmed = [s for s in manifest["segments"] if s["role"] == "clip" and s.get("trim")]
    assert len(trimmed) == 1 and trimmed[0]["source"].endswith("scene_01.mp4")


def test_a_trim_shorter_than_the_crossfade_is_refused_naming_both(home, reference):
    """Every join eats its own duration. A shot trimmed under it would not
    error -- it would simply not be in the cut."""
    _cfg, _store, engine, job = setup(home, reference, edit={"crossfade_s": 0.5})
    job = engine.run(job)
    with pytest.raises(TransitionError, match="0.5s"):
        engine.set_edit(job, {"trim": {"0": [0.0, 0.4]}}, recut=False)


def test_a_trim_past_the_end_of_the_shot_is_refused(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.run(job)
    length = job.scenes[0].get("duration_s")
    if not length:
        pytest.skip("mock clips do not record a duration")
    with pytest.raises(TransitionError, match="past the end"):
        engine.set_edit(job, {"trim": {"0": [float(length) + 1, None]}}, recut=False)


def test_an_out_point_before_the_in_point_is_refused(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.run(job)
    with pytest.raises(TransitionError, match="not after"):
        engine.set_edit(job, {"trim": {"0": [1.0, 0.5]}}, recut=False)


def test_the_trim_reaches_the_subtitle_probe_as_well_as_the_cut():
    """Subtitles are timed against a throwaway cut. Trim one and not the other
    and every word lands at the wrong second. Both call sites carry it."""
    import inspect
    from fjor_studio.stages import steps
    src = inspect.getsource(steps.assembly)
    assert src.count("clip_trim=_clip_trim(ctx)") == 2


def test_a_trim_changes_the_subtitle_signature():
    """The cached word timings are keyed by what moves the timeline."""
    from fjor_studio.stages.steps import _edit_signature
    class Ctx:
        class job:
            meta = {"edit": {}}
            intake = {}
            scenes = [{"idx": 0, "clip": "c0"}]
    a = _edit_signature(Ctx(), {})
    Ctx.job.meta = {"edit": {"trim": {"0": [0.5, None]}}}
    assert _edit_signature(Ctx(), {}) != a


# -- the voice as a track ------------------------------------------------------
#
# A spoken line used to be baked into its shot by normalise(): it always
# started on the shot's first frame, could not run past it, and a recording
# longer than its shot was cut off in silence by -shortest. Now it is laid
# over the assembled cut like the bed is.

def _silent_clip(path, seconds):
    import subprocess
    from fjor_studio.assemble import ffmpeg_with_libass
    subprocess.run(
        [ffmpeg_with_libass(), "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=c=0x334455:size=270x480:rate=25:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True, capture_output=True)
    return path


def _tone_wav(path, seconds, hz=440):
    import subprocess
    from fjor_studio.assemble import ffmpeg_with_libass
    subprocess.run([ffmpeg_with_libass(), "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"sine=frequency={hz}:duration={seconds}", str(path)],
                   check=True, capture_output=True)
    return path


def _loud_in(path, start, length):
    """Mean volume of one window of the file, in dB."""
    import re
    import subprocess
    from fjor_studio.assemble import _bin
    out = subprocess.run(
        [_bin("ffmpeg"), "-v", "info", "-ss", f"{start:.2f}", "-t", f"{length:.2f}",
         "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True).stderr
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", out)
    return float(m.group(1)) if m else -91.0


def test_a_recording_longer_than_its_shot_is_no_longer_cut_off(tmp_path):
    """The bug the design named: 3s of voice on a 2s shot used to lose its
    last second. Now it runs on into the next shot."""
    from fjor_studio.assemble import SIZES, build_final
    a, b = _silent_clip(tmp_path / "a.mp4", 2), _silent_clip(tmp_path / "b.mp4", 2)
    voice = _tone_wav(tmp_path / "v.wav", 3)
    build_final([a, b], tmp_path / "out.mp4", SIZES["9:16"],
                voice_tracks=[{"path": str(voice), "segment": 0, "offset": 0}])
    assert _loud_in(tmp_path / "out.mp4", 0.2, 1.5) > -40      # in its shot
    assert _loud_in(tmp_path / "out.mp4", 2.2, 0.6) > -40      # runs into the next
    assert _loud_in(tmp_path / "out.mp4", 3.2, 0.6) < -80      # and then stops


def test_an_offset_moves_the_voice_and_a_crossfade_does_not_lose_it(tmp_path):
    """Where a shot starts is the same sum crossfade uses: every join eats one
    fade. A voice anchored to shot 3 with a 0.5s crossfade lands at
    2 + 2 - 2*0.5 = 3.0s, not at 4.0."""
    from fjor_studio.assemble import SIZES, build_final
    clips = [_silent_clip(tmp_path / f"c{i}.mp4", 2) for i in range(3)]
    voice = _tone_wav(tmp_path / "v.wav", 0.8)
    build_final(clips, tmp_path / "flat.mp4", SIZES["9:16"],
                voice_tracks=[{"path": str(voice), "segment": 2, "offset": 0.5}])
    assert _loud_in(tmp_path / "flat.mp4", 4.6, 0.6) > -40      # 4.0 + 0.5
    assert _loud_in(tmp_path / "flat.mp4", 3.6, 0.6) < -80
    build_final(clips, tmp_path / "xf.mp4", SIZES["9:16"], crossfade_s=0.5,
                voice_tracks=[{"path": str(voice), "segment": 2, "offset": 0.5}])
    assert _loud_in(tmp_path / "xf.mp4", 3.6, 0.6) > -40        # 3.0 + 0.5
    assert _loud_in(tmp_path / "xf.mp4", 2.6, 0.6) < -80


def test_the_voice_never_runs_over_the_packshot(tmp_path):
    """Clamped at speech_end, the picture boundary where the product begins."""
    from fjor_studio.assemble import SIZES, build_final
    clip = _silent_clip(tmp_path / "c.mp4", 2)
    pack = _silent_clip(tmp_path / "pack.mp4", 2)
    voice = _tone_wav(tmp_path / "v.wav", 4)
    rep = build_final([clip], tmp_path / "out.mp4", SIZES["9:16"], packshot=pack,
                      voice_tracks=[{"path": str(voice), "segment": 0, "offset": 0}])
    end = rep["speech_end_s"]
    assert _loud_in(tmp_path / "out.mp4", 0.2, 1.5) > -40
    assert _loud_in(tmp_path / "out.mp4", end + 0.3, 1.0) < -80
    assert rep["voices"][0]["clamped_at_s"] == pytest.approx(end, abs=0.05)


def test_an_untouched_job_cuts_exactly_as_it_did_before(home, reference):
    """The promise for the step that moves existing machinery: no vo edit, no
    change -- same length, same segments, the voice still where it was."""
    _cfg, store, engine, job = setup(home, reference)
    job = engine.approve(engine.approve(engine.run(job)))
    rep = job.meta["draft"]
    job = engine.set_edit(job, {"music_duck": True})             # any no-op re-cut
    rep2 = job.meta["draft"]
    assert rep2["duration_s"] == pytest.approx(rep["duration_s"], abs=0.05)
    assert [s["role"] for s in rep2["segments"]] == [s["role"] for s in rep["segments"]]
    for a, b in zip(rep["segments"], rep2["segments"]):
        assert b["duration_s"] == pytest.approx(a["duration_s"], abs=0.05)
    # and the voice sits where it always did: at the start of its shot
    assert all(v["at_s"] >= 0 and v.get("in_s", 0) == 0 for v in rep2.get("voices", []))


def test_the_voice_is_mixed_before_the_bed_so_the_bed_ducks_under_it():
    import inspect
    from fjor_studio import assemble
    src = inspect.getsource(assemble.build_final)
    assert src.index("mix_voices(") < src.index("mix_music(")


def test_the_voice_reaches_the_subtitle_probe_as_well_as_the_cut():
    import inspect
    from fjor_studio.stages import steps
    assert inspect.getsource(steps.assembly).count("voice_tracks=_voice_tracks(ctx)") == 2


def test_a_moved_voice_changes_the_subtitle_signature():
    from fjor_studio.stages.steps import _edit_signature
    class Ctx:
        class job:
            meta = {"edit": {}}
            intake = {}
            scenes = [{"idx": 0, "clip": "c0"}]
    a = _edit_signature(Ctx(), {})
    Ctx.job.meta = {"edit": {"vo": {"0": {"offset": 0.5, "in": 0, "out": None}}}}
    assert _edit_signature(Ctx(), {}) != a


def test_moving_a_voice_a_shot_does_not_have_is_refused(home, reference):
    _cfg, _store, engine, job = setup(home, reference)
    job = engine.run(job)
    with pytest.raises(TransitionError, match="no separately spoken line"):
        engine.set_edit(job, {"vo": {"0": {"offset": 1}}}, recut=False)


def test_a_voice_trim_past_the_recording_is_refused(home, reference):
    _cfg, store, engine, job = setup(home, reference)
    job = engine.run(job)
    job_dir = store.job_dir(job.id)
    (job_dir / "audio").mkdir(exist_ok=True)
    _tone_wav(job_dir / "audio" / "scene_00_vo.wav", 1.0)
    s0 = job.scene_objs()[0]; s0.vo_track = "audio/scene_00_vo.wav"; job.put_scene(s0)
    store.save(job)
    with pytest.raises(TransitionError, match="past the end"):
        engine.set_edit(job, {"vo": {"0": {"in": 0, "out": 5.0}}}, recut=False)
