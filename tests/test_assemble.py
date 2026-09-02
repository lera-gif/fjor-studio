"""Assembly, run for real. ffmpeg is the deliverable here, so nothing is faked."""
import subprocess

import pytest

from fjor_studio.assemble import (SIZES, AssembleError, build_final, concat, duration_of,
                                  disclaimer_for, has_audio, list_packshots,
                                  packshot_for, probe)

ASSETS = pytest.importorskip("pathlib").Path(__file__).resolve().parents[1] / "assets"


def clip(path, seconds=2, audio=True, w=180, h=320, colour="blue"):
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-f", "lavfi", "-i", f"color=c={colour}:size={w}x{h}:rate=30:duration={seconds}"]
    if audio:
        cmd += ["-f", "lavfi", "-i",
                f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-shortest", str(path)]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


def band_bytes(video, at_s, height=240):
    """The bottom strip of a frame, as raw pixels."""
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at_s), "-i", str(video),
         "-vf", f"crop=iw:{height}:0:ih-{height}", "-frames:v", "1",
         "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True).stdout
    return out


def test_clips_are_joined_in_order_with_the_packshot_last(tmp_path):
    clips = [clip(tmp_path / f"c{i}.mp4", 2) for i in range(3)]
    r = build_final(clips, tmp_path / "out.mp4", SIZES["9:16"],
                    packshot=packshot_for(ASSETS, "formula", SIZES["9:16"]))
    roles = [s["role"] for s in r["segments"]]
    assert roles == ["clip", "clip", "clip", "packshot"]
    assert (r["width"], r["height"]) == (1080, 1920)


def test_a_silent_clip_does_not_destroy_the_audio_track(tmp_path):
    """Concatenating a mixture drops audio entirely unless every segment has one."""
    clips = [clip(tmp_path / "a.mp4", 2, audio=True),
             clip(tmp_path / "b.mp4", 2, audio=False),
             clip(tmp_path / "c.mp4", 2, audio=True)]
    r = build_final(clips, tmp_path / "out.mp4", SIZES["9:16"])
    assert r["has_audio"] is True
    assert has_audio(tmp_path / "out.mp4")


def test_the_disclaimer_is_present_over_the_packshot_at_the_very_end(tmp_path):
    """LIPIL025: the disclaimer tracked for 34 seconds and then stopped dead at
    the packshot boundary, so the end card shipped without it. The file looked
    fine everywhere anyone had thought to check."""
    clips = [clip(tmp_path / "c0.mp4", 3)]
    size = SIZES["9:16"]
    packshot = packshot_for(ASSETS, "formula", size)
    common = dict(packshot=packshot, crf=34, preset="ultrafast")
    plain = build_final(clips, tmp_path / "plain.mp4", size, **common)
    stamped = build_final(clips, tmp_path / "stamped.mp4", size,
                          disclaimer=disclaimer_for(ASSETS, size), **common)
    # a second before the end -- inside the packshot, well past the join
    late = stamped["duration_s"] - 1.0
    assert band_bytes(tmp_path / "stamped.mp4", late) != \
        band_bytes(tmp_path / "plain.mp4", late), \
        "the disclaimer is missing from the end of the video"
    # and still present early, so this is not just a shifted overlay
    assert band_bytes(tmp_path / "stamped.mp4", 1.0) != \
        band_bytes(tmp_path / "plain.mp4", 1.0)


def strip(video, at_s, y, height):
    return subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at_s), "-i", str(video),
         "-vf", f"crop=iw:{height}:0:{y}", "-frames:v", "1", "-f", "rawvideo",
         "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout


def test_the_ai_badge_covers_only_the_opening(tmp_path):
    """Both overlays are full-frame PNGs with their content placed internally --
    the badge lives at rows 1579-1603, well below the top of the frame."""
    clips = [clip(tmp_path / "c0.mp4", 6)]
    size = SIZES["9:16"]
    common = dict(crf=34, preset="ultrafast")
    build_final(clips, tmp_path / "plain.mp4", size, **common)
    build_final(clips, tmp_path / "badged.mp4", size,
                badge=disclaimer_for(ASSETS, size, badge=True),
                badge_s=3.0, **common)
    BADGE_Y, BADGE_H = 1540, 120
    assert strip(tmp_path / "badged.mp4", 1.0, BADGE_Y, BADGE_H) != \
        strip(tmp_path / "plain.mp4", 1.0, BADGE_Y, BADGE_H)
    assert strip(tmp_path / "badged.mp4", 5.0, BADGE_Y, BADGE_H) == \
        strip(tmp_path / "plain.mp4", 5.0, BADGE_Y, BADGE_H)


def test_each_size_crops_rather_than_pads(tmp_path):
    """A padded frame reads as a mistake; the reference is always full bleed."""
    clips = [clip(tmp_path / "c0.mp4", 2, w=320, h=180, colour="red")]  # landscape
    r = build_final(clips, tmp_path / "out.mp4", SIZES["4:5"], crf=34,
                    preset="ultrafast")
    assert (r["width"], r["height"]) == (1080, 1350)
    # a padded result would have black bars: sample the top-left corner
    px = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(tmp_path / "out.mp4"),
         "-vf", "crop=40:40:0:0", "-frames:v", "1", "-f", "rawvideo",
         "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    assert max(px) > 20, "top-left is black -- the frame was padded, not cropped"


def test_a_missing_clip_fails_before_any_encoding(tmp_path):
    with pytest.raises(AssembleError, match="missing clips"):
        build_final([tmp_path / "nope.mp4"], tmp_path / "o.mp4", SIZES["9:16"])


def test_concat_with_nothing_is_an_error(tmp_path):
    with pytest.raises(AssembleError, match="nothing to join"):
        concat([], tmp_path / "o.mp4")


def test_the_library_lists_the_packshot_and_finds_both_twins():
    assert "formula" in list_packshots(ASSETS)
    assert packshot_for(ASSETS, "formula", SIZES["9:16"]).name == "formula_916.mp4"
    assert packshot_for(ASSETS, "formula", SIZES["4:5"]).name == "formula_45.mp4"
    assert packshot_for(ASSETS, "nope", SIZES["9:16"]) is None


# -- crossfade ---------------------------------------------------------------

def test_a_crossfade_shortens_the_cut_by_one_fade_per_join(tmp_path):
    """Every transition eats its own duration. Anything that sums the parts
    instead of measuring the whole will be wrong, subtitles included."""
    clips = [clip(tmp_path / f"c{i}.mp4", 3) for i in range(3)]
    hard = build_final(clips, tmp_path / "hard.mp4", SIZES["9:16"],
                       crf=34, preset="ultrafast")
    faded = build_final(clips, tmp_path / "faded.mp4", SIZES["9:16"],
                        crossfade_s=0.5, crf=34, preset="ultrafast")
    assert hard["duration_s"] == pytest.approx(9.0, abs=0.3)
    # three 3s clips, two joins, half a second each
    assert faded["duration_s"] == pytest.approx(8.0, abs=0.3)
    assert faded["crossfade_s"] == 0.5


def test_speech_end_is_measured_after_the_fades_not_summed(tmp_path):
    """The subtitle clamp reads this. Summing would put it half a second late
    and let the last word draw over the packshot."""
    clips = [clip(tmp_path / f"c{i}.mp4", 3) for i in range(3)]
    r = build_final(clips, tmp_path / "out.mp4", SIZES["9:16"],
                    packshot=packshot_for(ASSETS, "formula", SIZES["9:16"]),
                    crossfade_s=0.5, crf=34, preset="ultrafast")
    assert r["speech_end_s"] == pytest.approx(8.0, abs=0.3)
    assert r["speech_end_s"] < 9.0


def test_a_fade_longer_than_a_shot_is_refused(tmp_path):
    clips = [clip(tmp_path / "a.mp4", 3), clip(tmp_path / "b.mp4", 1)]
    with pytest.raises(AssembleError, match="longer than a segment"):
        build_final(clips, tmp_path / "out.mp4", SIZES["9:16"],
                    crossfade_s=2.0, crf=34, preset="ultrafast")


def test_a_single_clip_with_a_fade_set_still_assembles(tmp_path):
    r = build_final([clip(tmp_path / "a.mp4", 3)], tmp_path / "out.mp4",
                    SIZES["9:16"], crossfade_s=0.5, crf=34, preset="ultrafast")
    assert r["duration_s"] == pytest.approx(3.0, abs=0.3)


def test_the_packshot_can_be_joined_hard_while_shots_dissolve(tmp_path):
    clips = [clip(tmp_path / f"c{i}.mp4", 3) for i in range(2)]
    pack = packshot_for(ASSETS, "formula", SIZES["9:16"])
    soft = build_final(clips, tmp_path / "soft.mp4", SIZES["9:16"],
                       packshot=pack, crossfade_s=0.5, crf=34, preset="ultrafast")
    hard = build_final(clips, tmp_path / "hard.mp4", SIZES["9:16"],
                       packshot=pack, crossfade_s=0.5,
                       crossfade_into_packshot=False, crf=34, preset="ultrafast")
    assert hard["duration_s"] > soft["duration_s"]


# -- music bed ---------------------------------------------------------------
#
# The beds are 11M of optional media and deliberately not in the repo (see
# assets/README.md), so these skip rather than fail where they are absent. A
# fresh deployment is told to read a green suite as "this install works" --
# three failures it is supposed to ignore is how a real one gets ignored too.

def a_bed():
    from fjor_studio.assemble import list_music
    beds = list_music(ASSETS)
    if not beds:
        pytest.skip("no music beds in assets/music bed/ (optional, not shipped)")
    return beds[0]


def test_a_music_bed_is_mixed_without_changing_the_length(tmp_path):
    """duration=first: a bed longer than the cut must not extend it."""
    from fjor_studio.assemble import music_for
    beds = [a_bed()]
    clips = [clip(tmp_path / "c0.mp4", 3)]
    dry = build_final(clips, tmp_path / "dry.mp4", SIZES["9:16"],
                      crf=34, preset="ultrafast")
    wet = build_final(clips, tmp_path / "wet.mp4", SIZES["9:16"],
                      music=music_for(ASSETS, beds[0]), crf=34, preset="ultrafast")
    assert wet["duration_s"] == pytest.approx(dry["duration_s"], abs=0.3)
    assert wet["music"] == music_for(ASSETS, beds[0]).name
    assert wet["has_audio"] is True


def test_music_lookup_accepts_a_stem_or_a_filename():
    from fjor_studio.assemble import music_for
    stem = a_bed()
    assert music_for(ASSETS, stem) is not None
    assert music_for(ASSETS, music_for(ASSETS, stem).name) is not None
    assert music_for(ASSETS, "not-a-bed") is None


def test_the_cut_is_4_2_0_and_therefore_actually_plays(tmp_path):
    """Overlaying an RGBA disclaimer negotiates the filter chain up to yuv444p,
    and libx264 encodes High 4:4:4 Predictive without complaint. ffprobe reports
    a healthy file, VLC plays it, and the browser -- and the ad platform -- show
    a blank frame with working audio and the right duration. Every draft and
    every final this pipeline shipped before 2026-08-21 was 4:4:4."""
    size = SIZES["9:16"]
    build_final([clip(tmp_path / "c0.mp4", 2)], tmp_path / "out.mp4", size,
                packshot=packshot_for(ASSETS, "formula", size),
                disclaimer=disclaimer_for(ASSETS, size),
                badge=disclaimer_for(ASSETS, size, badge=True),
                crf=34, preset="ultrafast")
    v = [s for s in probe(tmp_path / "out.mp4")["streams"]
         if s["codec_type"] == "video"][0]
    assert v["pix_fmt"] == "yuv420p", f"shipped as {v['pix_fmt']}: no browser decodes it"
    assert "4:4:4" not in v.get("profile", "")


# -- the bed library is filed, not heaped ------------------------------------

def beds(tmp_path, tree):
    """A music library on disk. `tree` maps a relative path to a filename."""
    import subprocess
    root = tmp_path / "music bed"
    for rel, names in tree.items():
        d = root / rel if rel else root
        d.mkdir(parents=True, exist_ok=True)
        for name in names:
            subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                            "-i", "sine=frequency=440:duration=1", str(d / name)],
                           check=True, capture_output=True)
    return tmp_path


def test_beds_are_found_in_their_folders_and_named_by_them(tmp_path):
    """109 beds in one flat list is not something a producer can choose from,
    so the library is filed by mood and the folder is part of the name."""
    from fjor_studio.assemble import list_music
    a = beds(tmp_path, {"Calm": ["Kyoto.mp3"], "Upbeat": ["Groove.mp3"],
                        "": ["Loose.mp3"]})
    assert list_music(a) == ["Calm/Kyoto", "Loose", "Upbeat/Groove"]


def test_a_bed_recorded_before_the_library_was_filed_still_resolves(tmp_path):
    """LME108 stored `Gridiron_Groove_...` with no folder. Re-cutting it after
    the library was reorganised must not silently lose its music."""
    from fjor_studio.assemble import music_for
    a = beds(tmp_path, {"House": ["Gridiron_Groove_2026-08-14T125212.mp3"]})
    found = music_for(a, "Gridiron_Groove_2026-08-14T125212")
    assert found and found.parent.name == "House"
    assert music_for(a, "House/Gridiron_Groove_2026-08-14T125212") == found
    assert music_for(a, "House/Gridiron_Groove_2026-08-14T125212.mp3") == found


def test_the_same_bed_filed_under_two_moods_is_reachable_as_both(tmp_path):
    from fjor_studio.assemble import list_music, music_for
    a = beds(tmp_path, {"Upbeat": ["Shinkansen.mp3"], "Japanese fun": ["Shinkansen.mp3"]})
    assert list_music(a) == ["Japanese fun/Shinkansen", "Upbeat/Shinkansen"]
    assert music_for(a, "Upbeat/Shinkansen").parent.name == "Upbeat"
    assert music_for(a, "Japanese fun/Shinkansen").parent.name == "Japanese fun"


def test_a_bed_in_the_trash_folder_cannot_be_chosen(tmp_path):
    """Licensed masters are moved out of circulation, not deleted. A bed the
    producer has retired must not come back through the picker."""
    from fjor_studio.assemble import list_music, music_for
    a = beds(tmp_path, {"Calm": ["Kyoto.mp3"],
                        "_to_delete": ["Call Me Maybe.mp3"]})
    assert list_music(a) == ["Calm/Kyoto"]
    assert music_for(a, "Call Me Maybe") is None
    assert music_for(a, "_to_delete/Call Me Maybe") is None


# -- text cards: our offer in the reference's typography ---------------------

def a_card(tmp_path, name="card.png", text="28 DAYS", y="300", size=1080, h=1350):
    """A generated card looks like this: flat key colour, our words on top."""
    from fjor_studio.assemble import ffmpeg_with_libass
    font = ASSETS / "fonts" / "Inter-Bold.ttf"
    out = tmp_path / name
    subprocess.run([ffmpeg_with_libass(), "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"color=c=0x00B140:size={size}x{h}",
                    "-vf", f"drawtext=fontfile={font}:text='{text}':fontcolor=white:"
                           f"fontsize=120:x=(w-tw)/2:y={y}:borderw=8:bordercolor=black",
                    "-frames:v", "1", str(out)], check=True, capture_output=True)
    return out


def test_a_card_keys_to_alpha_and_keeps_its_letters(tmp_path):
    """Keyed as an IMAGE, not as video: a flat digital colour is far cleaner to
    key than a filmed one, and despill takes the halo off the letters."""
    from fjor_studio.assemble import key_text_card, probe
    keyed = key_text_card(a_card(tmp_path), tmp_path / "keyed.png")
    stream = [s for s in probe(keyed)["streams"] if s.get("width")][0]
    assert "a" in stream["pix_fmt"], "the key produced no alpha channel"
    # the letters survived: something is still opaque
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(keyed), "-vf", "alphaextract",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True).stdout
    assert any(b > 200 for b in raw), "the card keyed away entirely"


def test_the_bottom_of_a_card_is_checked_not_assumed(tmp_path):
    """The disclaimer and the badge live in the bottom band. They are approved
    compliance assets and a card drawn over them cannot ship, so the rule is
    verified rather than trusted to the prompt."""
    from fjor_studio.assemble import card_bottom_is_clear, key_text_card
    clean = key_text_card(a_card(tmp_path, "ok.png", y="300"), tmp_path / "k1.png")
    over = key_text_card(a_card(tmp_path, "bad.png", "SMALL PRINT", y="h-120"),
                         tmp_path / "k2.png")
    assert card_bottom_is_clear(clean) is True
    assert card_bottom_is_clear(over) is False


def test_a_card_is_laid_over_the_cut_full_frame(tmp_path):
    """Not scaled to fit, not cropped to its ink: the card was generated at the
    frame's own shape, so every block is already where it belongs."""
    from fjor_studio.assemble import key_text_card, overlay_text_card, probe
    keyed = key_text_card(a_card(tmp_path), tmp_path / "keyed.png")
    base = clip(tmp_path / "base.mp4", 2, w=1080, h=1350)
    out = overlay_text_card(base, keyed, tmp_path / "carded.mp4",
                            crf=34, preset="ultrafast")
    v = [s for s in probe(out)["streams"] if s["codec_type"] == "video"][0]
    assert (v["width"], v["height"]) == (1080, 1350)
    assert v["pix_fmt"] == "yuv420p"          # rule 15 holds here too
    assert duration_of(out) == pytest.approx(duration_of(base), abs=0.15)


def test_an_unknown_key_colour_is_refused(tmp_path):
    from fjor_studio.assemble import AssembleError, key_text_card
    with pytest.raises(AssembleError):
        key_text_card(a_card(tmp_path), tmp_path / "x.png", key="chartreuse")
