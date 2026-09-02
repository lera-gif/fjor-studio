"""Banner mode: a client's finished banner, expanded and brought to life.

Everything printed on a banner was approved by somebody. The tests here are
almost all about the one question that follows from that: did the expansion
leave it alone?
"""
import subprocess

import pytest

from fjor_studio.assemble import ffmpeg_with_libass
from fjor_studio.banner import (BannerError, banner_survived, build_canvas,
                                measure, placement)

from conftest import a_banner

FONT = pytest.importorskip("pathlib").Path(__file__).resolve().parents[1] \
    / "assets" / "fonts" / "Inter-Bold.ttf"


def expand_honestly(canvas, place, dest):
    """What a good expansion does: fill the margins, touch nothing else."""
    subprocess.run(
        [ffmpeg_with_libass(), "-y", "-v", "error", "-i", str(canvas), "-vf",
         f"drawbox=x=0:y=0:w=1080:h={place['top']}:color=0x1B4F3A:t=fill,"
         f"drawbox=x=0:y={place['y'] + place['h']}:w=1080:h={place['bottom']}:"
         f"color=0x1B4F3A:t=fill",
         "-frames:v", "1", str(dest)], check=True, capture_output=True)
    return dest


# -- the canvas --------------------------------------------------------------

def test_a_square_banner_lands_centred_with_margins_to_fill(tmp_path):
    info = build_canvas(a_banner(tmp_path / "b.png"), tmp_path / "c.png")
    assert (info["w"], info["h"]) == (1080, 1080)     # full width, not cropped
    assert info["x"] == 0 and info["y"] == 420
    assert info["top"] == info["bottom"] == 420
    assert info["needs_expansion"] is True


def test_a_banner_already_vertical_needs_no_expansion(tmp_path):
    info = build_canvas(a_banner(tmp_path / "b.png", 1080, 1920), tmp_path / "c.png")
    assert info["needs_expansion"] is False
    assert (info["top"], info["bottom"]) == (0, 0)


def test_a_tall_banner_is_fitted_rather_than_cropped(tmp_path):
    """The banner is the asset. Cutting it to fit would lose what we were given."""
    info = build_canvas(a_banner(tmp_path / "b.png", 1080, 2400), tmp_path / "c.png")
    assert info["h"] <= 1920 and info["w"] <= 1080


def test_the_canvas_is_the_banner_on_a_marker(tmp_path):
    from fjor_studio.banner import MARKER
    info = build_canvas(a_banner(tmp_path / "b.png"), tmp_path / "c.png")
    assert measure(tmp_path / "c.png") == (1080, 1920)
    # the margin really is the marker colour, or the model cannot see what to fill
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(tmp_path / "c.png"),
         "-vf", "crop=1080:100:0:0", "-frames:v", "1", "-f", "rawvideo",
         "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
    # near, not exact: ffmpeg's colour source generates in YUV and converts
    # back, so 0xFF00B1 arrives as (253, 0, 176). Anything that later asks "is
    # this still the marker?" has to allow for that.
    assert abs(raw[0] - 0xFF) <= 6 and raw[1] <= 6 and abs(raw[2] - 0xB1) <= 6
    assert info["marker"] == MARKER


def test_a_file_that_is_not_an_image_is_refused(tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("this is not a banner")
    with pytest.raises(BannerError):
        build_canvas(bad, tmp_path / "c.png")


# -- did the banner survive? -------------------------------------------------

def test_an_honest_expansion_leaves_the_banner_untouched(tmp_path):
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    good = expand_honestly(tmp_path / "c.png", info, tmp_path / "ok.png")
    verdict = banner_survived(b, good, info)
    assert verdict["intact"] is True
    assert verdict["changed_pixels"] == 0


@pytest.mark.parametrize("what,vf", [
    ("the headline recoloured",
     "drawtext=fontfile={font}:text='LOSE THE SWELLING':fontcolor=0xFFE0E0:"
     "fontsize=86:x=(w-tw)/2:y={y0}"),
    ("the button nudged six pixels",
     "drawbox=x=346:y={y1}:w=400:h=110:color=0xFFC93C:t=fill"),
    ("the legal line painted out",
     "drawbox=x=200:y={y2}:w=680:h=40:color=0x1B4F3A:t=fill"),
])
def test_an_edited_banner_is_caught(tmp_path, what, vf):
    """Their QA calls each of these critical, and it is right to: the client
    approved what was printed, so changing it destroys the asset."""
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    good = expand_honestly(tmp_path / "c.png", info, tmp_path / "ok.png")
    bad = tmp_path / "bad.png"
    subprocess.run(
        [ffmpeg_with_libass(), "-y", "-v", "error", "-i", str(good), "-vf",
         vf.format(font=FONT, y0=info["y"] + 302, y1=info["y"] + 561,
                   y2=info["y"] + 1000),
         "-frames:v", "1", str(bad)], check=True, capture_output=True)
    verdict = banner_survived(b, bad, info)
    assert verdict["intact"] is False, f"{what} went unnoticed"


def test_the_verdict_counts_changed_pixels_rather_than_averaging(tmp_path):
    """The mean was tried first and is the wrong statistic: a local edit is
    diluted across a million pixels. All three edits above passed a mean
    tolerance that codec noise already reached."""
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    good = expand_honestly(tmp_path / "c.png", info, tmp_path / "ok.png")
    bad = tmp_path / "bad.png"
    subprocess.run(
        [ffmpeg_with_libass(), "-y", "-v", "error", "-i", str(good), "-vf",
         f"drawbox=x=346:y={info['y'] + 561}:w=400:h=110:color=0xFFC93C:t=fill",
         "-frames:v", "1", str(bad)], check=True, capture_output=True)
    verdict = banner_survived(b, bad, info)
    assert verdict["intact"] is False
    # the mean alone would have called this clean
    assert verdict["mean_difference"] < 2.0
    assert verdict["changed_pixels"] > verdict["allowed"]


# -- the licensed band -------------------------------------------------------

def _paint_over(src, dest, vf):
    subprocess.run([ffmpeg_with_libass(), "-y", "-v", "error", "-i", str(src),
                    "-vf", vf, "-frames:v", "1", str(dest)],
                   check=True, capture_output=True)
    return dest


def test_the_legal_line_may_be_removed_when_it_is_licensed(tmp_path):
    """The one edit inside the banner the producer actually wants: the fine
    print always goes. It is a second pass precisely so that licensing it does
    not licence everything else."""
    from fjor_studio.banner import SMALL_PRINT_BAND
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    good = expand_honestly(tmp_path / "c.png", info, tmp_path / "ok.png")
    cleaned = _paint_over(
        good, tmp_path / "clean.png",
        f"drawbox=x=200:y={info['y'] + 1000}:w=680:h=40:color=0x1B4F3A:t=fill")
    verdict = banner_survived(b, cleaned, info, licensed=SMALL_PRINT_BAND)
    assert verdict["intact"] is True
    assert verdict["edit_applied"] is True


def test_licensing_the_small_print_does_not_licence_the_headline(tmp_path):
    from fjor_studio.banner import SMALL_PRINT_BAND
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    good = expand_honestly(tmp_path / "c.png", info, tmp_path / "ok.png")
    bad = _paint_over(
        good, tmp_path / "bad.png",
        f"drawtext=fontfile={FONT}:text='LOSE THE SWELLING':fontcolor=0xFFE0E0:"
        f"fontsize=86:x=(w-tw)/2:y={info['y'] + 302}")
    verdict = banner_survived(b, bad, info, licensed=SMALL_PRINT_BAND)
    assert verdict["intact"] is False


def test_a_licensed_pass_that_changed_nothing_did_not_run(tmp_path):
    """A skipped pass reads as a clean result to every other check here, which
    is how a silently skipped step reaches delivery."""
    from fjor_studio.banner import SMALL_PRINT_BAND
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    good = expand_honestly(tmp_path / "c.png", info, tmp_path / "ok.png")
    verdict = banner_survived(b, good, info, licensed=SMALL_PRINT_BAND)
    assert verdict["intact"] is True
    assert verdict["edit_applied"] is False


# -- the expansion prompt playbook -------------------------------------------

from fjor_studio.banner import (ANALYSIS_QUESTIONS, MARKER, check_prompt,
                                colour_words_in, expansion_prompt,
                                small_print_prompt)

ANALYSIS = {
    "above": "the plain studio backdrop simply keeps going",
    "below": "the tabletop surface continues: same texture detail, same grain, "
             "same depth of field and the same light direction",
    "cut_off": "the woman's shoulders are cut by the bottom edge -- continue "
               "the body naturally downward, same clothing, same photographic "
               "treatment, plausible and modest.",
    "preserve": ["LOSE THE SWELLING", "GET THE PLAN", "the brand mark"],
    "decor": "keep the new areas clean and empty",
}


def test_the_top_and_the_bottom_are_asked_about_separately():
    """They are almost always different content, and one answer for both is how
    a tabletop ends up above the horizon."""
    assert "SEPARATELY" in ANALYSIS_QUESTIONS
    for missing in ("above", "below"):
        with pytest.raises(BannerError):
            expansion_prompt({**ANALYSIS, missing: ""})


def test_the_printed_things_are_named_in_quotes():
    """A model redraws a thing less when it has been named."""
    prompt = expansion_prompt(ANALYSIS)
    assert '"LOSE THE SWELLING"' in prompt and '"GET THE PLAN"' in prompt


def test_our_own_prompt_obeys_our_own_iron_rule():
    """The rule that costs money: a named shade is painted instead of the real
    edge pixels, and the seam band is a critical QA fail."""
    for tier in ("short", "full"):
        verdict = check_prompt(expansion_prompt({**ANALYSIS, "tier": tier}))
        assert verdict["ok"] is True, verdict["problems"]
    assert check_prompt(small_print_prompt(), expects_marker=False)["ok"] is True


def test_a_colour_word_is_caught_but_a_quoted_headline_is_not():
    assert colour_words_in("continue the warm beige backdrop") == ["beige"]
    assert colour_words_in('keep "Black Friday" and "Go Green" as printed') == []


def test_the_checks_catch_what_their_tool_shouted_about():
    assert "unfilled placeholders" in " ".join(
        check_prompt("replace the magenta with [what continues up]")["problems"])
    assert "started explaining" in " ".join(
        check_prompt("magenta. " + "a sentence about the extension. " * 200)["problems"])
    # a fill instruction that never says what to fill
    assert "never mentions the marker" in " ".join(
        check_prompt("extend this image upward and downward")["problems"])


def test_a_banner_with_nothing_cut_gets_the_safety_line():
    """Without it the model finds a reason to extend an object that was never
    cut, and duplicates it into the margin."""
    prompt = expansion_prompt({**ANALYSIS, "cut_off": "nothing is cut off"})
    assert "do not extend, complete or duplicate" in prompt


def test_a_decorative_object_leaving_the_frame_is_left_alone():
    prompt = expansion_prompt({**ANALYSIS,
                               "leave_cropped": "the spoon handle at the left edge."})
    assert "LEAVE CROPPED" in prompt and "do not complete it" in prompt


def test_a_brief_edit_is_the_only_licensed_change():
    prompt = expansion_prompt({**ANALYSIS, "edits": 'replace "24 July" with "24 August".'})
    assert "ONLY these edits" in prompt


def test_the_short_tier_is_shorter_and_still_says_the_load_bearing_things():
    """The short tier is not a shortcut: on a flat background every extra
    sentence is one more thing for the model to act on."""
    short = expansion_prompt({**ANALYSIS, "tier": "short"})
    full = expansion_prompt({**ANALYSIS, "tier": "full"})
    assert len(short) < len(full)
    for prompt in (short, full):
        assert MARKER in prompt
        assert "seamless" in prompt.lower()
        assert "magenta left anywhere" in prompt


def test_an_unknown_tier_is_refused():
    with pytest.raises(BannerError):
        expansion_prompt({**ANALYSIS, "tier": "medium"})


# -- the animation -----------------------------------------------------------

from fjor_studio.banner import (BANNER_SECONDS, TEXT_LOCK, TEXT_LOCK_NEGATIVE,
                                animation_prompt)

MOTION = {"movers": ["the steam above the mug drifts upward and thins"],
          "central": "the steam rises through the middle of the frame",
          "seconds": 8}


def test_the_text_lock_is_inserted_rather_than_asked_for():
    """Their rule says 'include this line verbatim'. A rule that depends on a
    language model reproducing a sentence word for word holds until it does
    not, and a video model that re-renders type cannot be repaired afterwards."""
    out = animation_prompt(MOTION)
    assert TEXT_LOCK in out["prompt"]
    assert TEXT_LOCK_NEGATIVE in out["prompt"]


def test_a_clip_that_moves_only_in_the_margins_is_refused():
    """The 4:5 final is cropped from the middle and ships alongside the 9:16.
    Without a central mover one of the two deliverables is a still."""
    with pytest.raises(BannerError):
        animation_prompt({**MOTION, "central": ""})


def test_a_drawn_banner_needs_several_tiny_events_and_a_photo_needs_one_or_two():
    """One mover on a flat illustration leaves the clip looking dead; three on a
    photograph is a carnival."""
    with pytest.raises(BannerError):
        animation_prompt({**MOTION, "graphic": True})          # only one event
    with pytest.raises(BannerError):
        animation_prompt({**MOTION, "movers": ["a", "b", "c"]})  # not drawn
    drawn = animation_prompt({**MOTION, "graphic": True,
                              "movers": ["a paint daub slowly spreads",
                                         "a doodle line draws itself in",
                                         "the drawn bow flutters once"]})
    assert "one at a time" in drawn["prompt"]


def test_an_object_carrying_text_is_told_not_to_move():
    out = animation_prompt({**MOTION, "frozen": "the jar"})
    assert "The jar carries printed lettering and therefore does not move" \
        in out["prompt"]


def test_the_camera_is_locked_by_default_and_says_so_twice():
    """Once in the positive, once in the negative: our frame has an expansion in
    it, and a push-in magnifies the newest, least trustworthy pixels."""
    out = animation_prompt(MOTION)
    assert out["camera"] == "locked"
    assert "THE CAMERA DOES NOT MOVE" in out["prompt"]
    assert "camera push-in" in out["prompt"].rsplit("NEGATIVE", 1)[-1]
    push = animation_prompt(MOTION, camera="push")
    assert "camera push-in" not in push["prompt"].rsplit("NEGATIVE", 1)[-1]
    with pytest.raises(BannerError):
        animation_prompt(MOTION, camera="handheld")


def test_the_clip_is_silent_and_loops():
    prompt = animation_prompt(MOTION)["prompt"]
    assert "No speech, no voice-over, no lip movement" in prompt
    assert "loops" in prompt


def test_a_duration_outside_the_range_is_refused():
    lo, hi = BANNER_SECONDS
    assert animation_prompt({**MOTION, "seconds": lo})["seconds"] == lo
    assert animation_prompt({**MOTION, "seconds": hi})["seconds"] == hi
    for bad in (lo - 1, hi + 1):
        with pytest.raises(BannerError):
            animation_prompt({**MOTION, "seconds": bad})


def test_a_frame_that_is_not_the_canvas_cannot_be_compared_at_all(tmp_path):
    """The banner sits at a known rectangle of a known canvas. Cropping that
    rectangle out of something else answers a different question, so the check
    says it cannot look rather than reporting an all-clear."""
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    wrong = a_banner(tmp_path / "other.png", 640, 640)
    with pytest.raises(BannerError, match="640x640"):
        banner_survived(b, wrong, info)


# -- is it the same picture, and is the banner put back? ---------------------

def test_a_rescaled_return_is_still_recognised_as_the_same_picture(tmp_path):
    """An image model answers with ITS resolution bucket, not ours: AW025 asked
    for 1080x1920 and got 768x1376 twice, identically, whatever the prompt said.
    Demanding exact pixels of a raw return made the mode unusable."""
    from fjor_studio.banner import same_picture
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    good = expand_honestly(tmp_path / "c.png", info, tmp_path / "ok.png")
    bucketed = _paint_over(good, tmp_path / "768.png", "scale=768:1376:flags=lanczos")
    verdict = same_picture(b, bucketed, info)
    assert verdict["same"] is True
    assert verdict["returned"] == [768, 1376]


def test_a_redrawn_scene_is_caught_however_it_is_scaled(tmp_path):
    """The failure AW025 actually hit: the model drew its own picture. Not
    repairable by putting our banner back, because the MARGINS it painted
    belong to that other scene, and the margins are all we keep."""
    from fjor_studio.banner import same_picture
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    other = a_banner(tmp_path / "other.png")
    redrawn = _paint_over(other, tmp_path / "red.png",
                          "hue=h=140:s=1.4,scale=768:1376:flags=lanczos")
    assert same_picture(b, redrawn, info)["same"] is False


def test_a_frame_of_the_wrong_shape_cannot_be_judged_at_all(tmp_path):
    from fjor_studio.banner import BannerError as BE, same_picture
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    with pytest.raises(BE, match="not the shape"):
        same_picture(b, a_banner(tmp_path / "wide.png", 1600, 900), info)


def test_recompositing_puts_the_banner_back_exactly(tmp_path):
    """The model contributes MARGINS. Everything else it returns is a rescaled
    approximation of pixels we already have, so ours go back and the banner is
    exact by construction rather than by hope."""
    from fjor_studio.banner import recomposite
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    good = expand_honestly(tmp_path / "c.png", info, tmp_path / "ok.png")
    # what the provider really does: its own bucket, and a nudged button too
    mangled = _paint_over(good, tmp_path / "mangled.png",
                          f"drawbox=x=346:y={info['y'] + 561}:w=400:h=110:"
                          f"color=0xFFC93C:t=fill,scale=768:1376:flags=lanczos")
    back = recomposite(b, mangled, tmp_path / "back.png", info)
    assert measure(back) == (1080, 1920)
    verdict = banner_survived(b, back, info)
    assert verdict["intact"] is True and verdict["changed_pixels"] == 0


def test_the_strict_check_refuses_a_frame_that_is_not_a_finished_canvas(tmp_path):
    """It reads the banner's own rectangle of a 1080x1920 canvas, so it is asked
    AFTER recompositing, never of a model's raw return."""
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    good = expand_honestly(tmp_path / "c.png", info, tmp_path / "ok.png")
    small = _paint_over(good, tmp_path / "small.png", "scale=768:1376:flags=lanczos")
    with pytest.raises(BannerError, match="768x1376"):
        banner_survived(b, small, info)


def test_recompositing_does_not_quietly_subsample_the_banner(tmp_path):
    """Left to negotiate, the overlay chain picks a YUV format and chroma-
    subsamples the artwork on its way through: 29,658 pixels of a real client's
    banner altered by the very operation meant to restore it (AW025). Rule 15,
    in a place that has nothing to do with encoding a video."""
    from fjor_studio.banner import recomposite
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    good = expand_honestly(tmp_path / "c.png", info, tmp_path / "ok.png")
    bucketed = _paint_over(good, tmp_path / "2k.png", "scale=1536:2752:flags=lanczos")
    back = recomposite(b, bucketed, tmp_path / "back.png", info)
    assert banner_survived(b, back, info)["changed_pixels"] == 0


def test_a_licensed_band_keeps_its_ground_and_not_one_row_more(tmp_path):
    """The small-print pass edits INSIDE the banner, so its frame cannot simply
    be overwritten with ours. The band it was licensed for comes from the model;
    every other row is restored — including a headline it touched on the way."""
    from fjor_studio.banner import SMALL_PRINT_BAND, recomposite
    b = a_banner(tmp_path / "b.png")
    info = build_canvas(b, tmp_path / "c.png")
    good = expand_honestly(tmp_path / "c.png", info, tmp_path / "ok.png")
    # a model that erased the small print AND meddled with the headline, and
    # answered in its own resolution while it was at it
    meddled = _paint_over(
        good, tmp_path / "meddled.png",
        f"drawbox=x=200:y={info['y'] + 1000}:w=680:h=40:color=0x1B4F3A:t=fill,"
        f"drawtext=fontfile={FONT}:text='LOSE THE SWELLING':fontcolor=0xFFE0E0:"
        f"fontsize=86:x=(w-tw)/2:y={info['y'] + 302},scale=1536:2752:flags=lanczos")
    back = recomposite(b, meddled, tmp_path / "back.png", info,
                       keep=SMALL_PRINT_BAND)
    verdict = banner_survived(b, back, info, licensed=SMALL_PRINT_BAND)
    assert verdict["intact"] is True          # the headline is ours again
    assert verdict["edit_applied"] is True    # and the small print really went


def test_quoted_client_copy_does_not_count_as_the_writer_explaining(tmp_path):
    """AW027 (2026-09-02) was refused at 3,196 characters -- most of it the eight
    lines printed on the client's own artwork, quoted twice because the PRESERVE
    and DO-NOT blocks both require it. Naming every printed line is the point;
    a copy-heavy banner is not a rambling writer."""
    from fjor_studio.banner import MAX_PROMPT_PROSE, check_prompt, expansion_prompt
    copy = [f"line number {i} of a wordy client banner" for i in range(30)]
    prompt = expansion_prompt(
        {"above": "the border continues", "below": "the ground continues",
         "cut_off": "nothing is cut off", "preserve": copy, "decor": "keep clean"},
        engine="redraw", size=(1080, 1080))
    assert len(prompt) > MAX_PROMPT_PROSE          # long, because of the copy
    assert check_prompt(prompt, expects_marker=False)["ok"] is True

    rambling = "Replace the magenta. " + "The writer explains at length. " * 100
    problems = check_prompt(rambling)["problems"]
    assert any("started explaining" in p for p in problems)
    assert any("does not count" in p for p in problems)
