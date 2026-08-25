"""Subtitles: the ASS mechanics as pure logic, then a real libass render."""
import json
import subprocess
from pathlib import Path

import pytest

from fjor_studio.assemble import SIZES, build_final, ffmpeg_with_libass, normalise
from fjor_studio.gen.base import GenError
from fjor_studio.subtitles import (COLOURS, POSITIONS, SubtitleStyle, Word,
                                   apply_lead, ass_time, bgr, build_ass, burn,
                                   clamp, lexicon_fix, transcribe)

ASSETS = Path(__file__).resolve().parents[1] / "assets"


def words(*triples):
    return [Word(w, s, e) for w, s, e in triples]


def dialogues(ass):
    return [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]


# -- ASS structure -----------------------------------------------------------

def test_every_line_carries_the_same_absolute_anchor():
    """Anchoring each dialogue by absolute centre is what stops libass drifting
    the text between frames and lines."""
    ass = build_ass(words(("a", 0, 1), ("b", 1, 2), ("c", 2, 3)), "9:16")
    lines = dialogues(ass)
    assert len(lines) == 3
    assert all(r"\an5\pos(540,1500)" in ln for ln in lines)


def test_the_4_5_cut_places_text_higher():
    assert POSITIONS["4:5"] == (540, 1100)
    ass = build_ass(words(("a", 0, 1)), "4:5")
    assert r"\pos(540,1100)" in ass
    assert "PlayResY: 1350" in ass


def test_words_chain_link_so_libass_never_stacks_two_lines():
    """A word holds until the NEXT one starts, not until its own end."""
    ass = build_ass(words(("a", 0.0, 0.3), ("b", 1.0, 1.4)), "9:16")
    first = dialogues(ass)[0]
    assert first.split(",")[2] == "0:00:01.00"      # ends where 'b' begins


def test_a_word_does_not_hold_across_a_silence(tmp_path=None):
    """LME108: 'up' ended scene 0's voiceover and the next word was 25 seconds
    away, so the chain-link held UP on screen over three silent scenes. The
    producer saw it in the draft player. Chain-linking is right where there is
    speech and wrong across a pause."""
    ass = build_ass(words(("up", 8.58, 8.92), ("and", 34.0, 34.4)), "9:16")
    first = dialogues(ass)[0]
    assert first.split(",")[2] == "0:00:09.72"      # 8.92 + MAX_HOLD_S, not 34.00


def test_a_normal_inter_word_gap_still_chain_links():
    """The cap must not break the mechanic it is protecting: real speech gaps
    are far shorter than the cap, so those words still hand over with no hole."""
    ass = build_ass(words(("a", 0.0, 0.30), ("b", 0.55, 0.90)), "9:16")
    assert dialogues(ass)[0].split(",")[2] == "0:00:00.55"   # ends where 'b' begins


def test_the_last_word_gets_a_tail():
    ass = build_ass(words(("only", 0.0, 0.4)), "9:16")
    assert dialogues(ass)[0].split(",")[2] == "0:00:00.90"   # 0.4 + 0.5


def test_text_is_uppercased_and_braces_stripped():
    ass = build_ass(words((r"pi{la}tes", 0, 1)), "9:16")
    assert "PILATES" in ass
    assert "{la}" not in ass.split("}")[-1]


def test_a_hard_clamp_keeps_subtitles_off_the_packshot():
    """Without it the last line's tail draws over the end card."""
    ass = build_ass(words(("early", 1.0, 1.4), ("edge", 3.8, 4.4),
                          ("after", 5.0, 5.4)), "9:16", clamp_end_s=4.0)
    lines = dialogues(ass)
    assert len(lines) == 2                      # 'after' dropped entirely
    assert lines[-1].split(",")[2] == "0:00:04.00"   # 'edge' trimmed to the edge


def test_clamp_drops_a_word_that_starts_on_the_boundary():
    assert [w.word for w in clamp(words(("x", 3.99, 4.5)), 4.0)] == []


def test_no_words_still_produces_a_valid_ass_header():
    """A cut with no speech is legitimate, not an error."""
    ass = build_ass([], "9:16")
    assert "[Events]" in ass and dialogues(ass) == []


def test_time_formatting_survives_nonsense():
    assert ass_time(0) == "0:00:00.00"
    assert ass_time(65.5) == "0:01:05.50"
    assert ass_time(-3) == "0:00:00.00"
    assert ass_time(float("nan")) == "0:00:00.00"


def test_colours_are_converted_to_ass_bgr():
    assert bgr("FFE948") == "&H0048E9FF"
    ass = build_ass(words(("a", 0, 1)), "9:16", SubtitleStyle(colour="red"))
    assert bgr(COLOURS["red"]) in ass


def test_size_names_map_to_point_sizes():
    for name, pt in (("small", 56), ("medium", 72), ("large", 90)):
        assert f",Inter,{pt}," in build_ass(words(("a", 0, 1)), "9:16",
                                            SubtitleStyle(size=name))


def test_an_unknown_frame_shape_is_refused():
    with pytest.raises(GenError, match="no text position"):
        build_ass(words(("a", 0, 1)), "1:1")


# -- word repair -------------------------------------------------------------

def test_the_lexicon_fixes_what_whisper_reliably_mangles():
    fixed = lexicon_fix(words(("potties", 0, 1), ("Pounds", 1, 2),
                              ("compound", 2, 3)))
    assert [w.word for w in fixed] == ["Pilates", "lbs", "compound"]


def test_the_lexicon_only_replaces_whole_alphabetic_tokens():
    assert lexicon_fix(words(("pounds,", 0, 1)))[0].word == "lbs,"


def test_lead_is_zero_by_default_and_shifts_when_asked():
    w = words(("a", 1.0, 1.4))
    assert apply_lead(w, 0.0)[0].start == 1.0
    shifted = apply_lead(w, 0.2)[0]
    assert round(shifted.start, 2) == 0.8 and round(shifted.end, 2) == 1.2


def test_lead_cannot_push_a_word_before_zero():
    assert apply_lead(words(("a", 0.1, 0.3)), 0.5)[0].start == 0.0


def test_transcription_without_a_key_is_refused(tmp_path):
    with pytest.raises(GenError, match="openai.api_key"):
        transcribe(tmp_path / "a.mp3", "")


# -- a real render -----------------------------------------------------------

def _clip(path, seconds=4):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=c=#20304a:size=360x640:rate=30:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=300:duration={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
         str(path)], check=True, capture_output=True)
    return path


def _band(video, at_s, y=1390, h=220):
    return subprocess.run(
        [ffmpeg_with_libass(), "-v", "error", "-ss", str(at_s), "-i", str(video),
         "-vf", f"crop=1080:{h}:0:{y}", "-frames:v", "1", "-f", "rawvideo",
         "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout


def _band_diff(a, b):
    """Mean absolute pixel difference.

    Byte equality is the wrong test here: burning subtitles adds an encode pass,
    so even an unchanged region differs slightly."""
    return sum(abs(x - y) for x, y in zip(a, b)) / max(1, len(a))


def _near_white(band, threshold=200):
    """Count near-white pixels. The subtitle face is white on a black outline,
    so on a flat dark background it is unmistakable -- and unlike comparing two
    separately-encoded files, this does not confuse a re-encoded gradient for
    burnt-in text."""
    return sum(1 for px in band if px > threshold)


def test_subtitles_actually_render_and_stop_at_the_packshot(tmp_path):
    """A flat, dark synthetic packshot on purpose: the real one is a pink
    gradient with white app badges in it, which is the worst possible surface
    to test 'is there white text here'."""
    size = SIZES["9:16"]
    clip = _clip(tmp_path / "c0.mp4", 4)
    tail = _clip(tmp_path / "tail.mp4", 4)
    subbed = build_final([clip], tmp_path / "subbed.mp4", size, packshot=tail,
                         words=words(("PILATES", 0.5, 3.5)),
                         subtitle_style=SubtitleStyle(),
                         fonts_dir=ASSETS / "fonts", crf=30, preset="ultrafast")
    assert subbed["subtitle_lines"] == 1
    assert subbed["speech_end_s"] == pytest.approx(4.0, abs=0.2)

    during = _near_white(_band(tmp_path / "subbed.mp4", 1.5))
    after = _near_white(_band(tmp_path / "subbed.mp4",
                              subbed["duration_s"] - 1.5))
    assert during > 500, f"no subtitle visible during speech ({during} px)"
    assert after < 50, f"subtitle is drawing over the packshot ({after} px)"


def test_subtitles_are_off_when_no_words_are_given(tmp_path):
    size = SIZES["9:16"]
    clip = _clip(tmp_path / "c0.mp4", 3)
    r = build_final([clip], tmp_path / "out.mp4", size, crf=30, preset="ultrafast")
    assert r["subtitle_lines"] == 0
    assert _near_white(_band(tmp_path / "out.mp4", 1.5)) < 50


def test_the_shipped_font_is_used_rather_than_a_silent_fallback(tmp_path):
    """Inter is not installed on this machine: without fontsdir libass renders
    in Verdana and reports no error at all."""
    ff = ffmpeg_with_libass()
    big = normalise(_clip(tmp_path / "c.mp4", 3), tmp_path / "big.mp4",
                    SIZES["9:16"])
    ass = tmp_path / "t.ass"
    ass.write_text(build_ass(words(("PILATES", 0.2, 2.5)), "9:16"))
    burn(big, ass, tmp_path / "inter.mp4", ff,
         fonts_dir=ASSETS / "fonts", crf=30, preset="ultrafast")
    burn(big, ass, tmp_path / "fallback.mp4", ff, fonts_dir=None,
         crf=30, preset="ultrafast")
    a, b = _band(tmp_path / "inter.mp4", 1.0), _band(tmp_path / "fallback.mp4", 1.0)
    assert _band_diff(a, b) > 1.0, \
        "fontsdir made no difference -- the shipped font is not being used"


def test_an_ffmpeg_with_libass_is_found():
    exe = ffmpeg_with_libass()
    conf = subprocess.run([exe, "-hide_banner", "-buildconf"],
                          capture_output=True, text=True)
    assert "--enable-libass" in conf.stdout + conf.stderr


# -- the transcript cache is keyed on the EDIT -------------------------------

def _fake_ctx(scenes, packshot="formula"):
    class J:
        def __init__(self):
            # real scenes always carry their index, and the signature reads it:
            # a reorder has to change the signature even when the same clips
            # are in the cut
            self.scenes = [dict(s, idx=s.get("idx", i))
                           for i, s in enumerate(scenes)]
            self.intake = {"packshot": packshot}
            self.meta = {}
            self.events = []

        def add_event(self, kind, msg="", **kw):
            self.events.append((kind, msg))

    class C:
        job = J()
    return C()


def test_the_edit_signature_changes_with_the_crossfade():
    """Word timings are positions on a TIMELINE. A 0.5s crossfade over five
    joins pulls the last shot 2.5s earlier, so a cache that ignores the edit
    replays old timings over a new cut and drifts further every transition."""
    from fjor_studio.stages.steps import _edit_signature
    ctx = _fake_ctx([{"clip": "clips/a.mp4"}, {"clip": "clips/b.mp4"}])
    hard = _edit_signature(ctx, {"crossfade_s": 0.0})
    soft = _edit_signature(ctx, {"crossfade_s": 0.5})
    assert hard != soft
    assert _edit_signature(ctx, {"crossfade_s": 0.5}) == soft   # stable


def test_the_edit_signature_changes_with_the_clips_and_the_packshot():
    from fjor_studio.stages.steps import _edit_signature
    base = _fake_ctx([{"clip": "clips/a.mp4"}])
    sig = _edit_signature(base, {"crossfade_s": 0.5})
    assert _edit_signature(_fake_ctx([{"clip": "clips/z.mp4"}]),
                           {"crossfade_s": 0.5}) != sig
    assert _edit_signature(_fake_ctx([{"clip": "clips/a.mp4"}], packshot="other"),
                           {"crossfade_s": 0.5}) != sig
    assert _edit_signature(base, {"crossfade_s": 0.5, "demo": "x"}) != sig


def test_a_stale_transcript_is_rebuilt_rather_than_replayed(monkeypatch, tmp_path):
    from fjor_studio.stages import steps
    ctx = _fake_ctx([{"clip": "clips/a.mp4"}])
    ctx.job.meta["subtitle_words"] = [{"word": "OLD", "start": 0.0, "end": 1.0}]
    ctx.job.meta["subtitle_sig"] = "signature-from-a-different-edit"
    ctx.config = type("Cfg", (), {"auth": {"openai": {"api_key": "k"}},
                                  "pipeline": {}})()
    ctx.dir = lambda sub: tmp_path
    import fjor_studio.subtitles as subs
    monkeypatch.setattr(subs, "extract_audio", lambda v, d: d)
    monkeypatch.setattr(subs, "transcribe",
                        lambda a, k, prompt="", http=None: [Word("NEW", 0.0, 1.0)])
    out = steps._transcribe_once(ctx, tmp_path / "v.mp4", 10.0, "the-new-signature")
    assert [w.word for w in out] == ["NEW"]
    assert ctx.job.meta["subtitle_sig"] == "the-new-signature"
    assert any(k == "transcript_stale" for k, _ in ctx.job.events)


def test_a_matching_transcript_is_reused_without_paying_again(monkeypatch, tmp_path):
    from fjor_studio.stages import steps
    import fjor_studio.subtitles as subs
    ctx = _fake_ctx([{"clip": "clips/a.mp4"}])
    ctx.job.meta["subtitle_words"] = [{"word": "KEPT", "start": 0.0, "end": 1.0}]
    ctx.job.meta["subtitle_sig"] = "same"
    ctx.config = type("Cfg", (), {"auth": {}, "pipeline": {}})()
    ctx.dir = lambda sub: tmp_path

    def boom(*a, **k):
        raise AssertionError("re-transcribed when the edit had not changed")

    monkeypatch.setattr(subs, "transcribe", boom)
    out = steps._transcribe_once(ctx, tmp_path / "v.mp4", 10.0, "same")
    assert [w.word for w in out] == ["KEPT"]
