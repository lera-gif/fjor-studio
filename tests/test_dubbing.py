"""Dubbing our own finished creatives, their way.

One dub of the whole finished export, a blurred band over the old burnt-in
subtitles, and new subtitles burned from the word timings the dub returns.
The band's geometry is tested in test_dubband.py; this file covers the money,
the transcript and the name.
"""
import json

import pytest

from fjor_studio import dubbing
from fjor_studio.dubbing import DubError
from fjor_studio.stages import dub_steps


class FakeAPI:
    """The three calls a dub makes, in the shapes the real one uses."""

    def __init__(self, states=("dubbing", "dubbed"), media=b"\x00\x00dubbed"):
        self.states, self.media, self.calls = list(states), media, []
        self._tick = 0

    def __call__(self, method, url, headers, json=None, data=None, **kw):
        self.calls.append((method, url))
        if url.endswith("/v1/dubbing"):
            return 200, {"content-type": "application/json"}, b'{"dubbing_id":"d1"}'
        if "/audio/" in url:
            return 200, {"content-type": "video/mp4"}, self.media
        state = self.states[min(self._tick, len(self.states) - 1)]
        self._tick += 1
        return 200, {"content-type": "application/json"}, \
            ('{"status":"%s"}' % state).encode()


def test_a_dub_is_submitted_waited_on_and_collected(tmp_path, monkeypatch):
    monkeypatch.setattr(dubbing.time, "sleep", lambda _s: None)
    api = FakeAPI()
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"FAKE" * 100)
    assert dubbing.submit(src, "es", "k", http=api) == "d1"
    dubbing.wait("d1", "k", http=api, poll_seconds=0)
    out = dubbing.fetch("d1", "es", tmp_path / "es.mp4", "k", http=api)
    assert out.read_bytes() == b"\x00\x00dubbed"
    assert [m for m, _u in api.calls] == ["POST", "GET", "GET", "GET"]


def test_a_refusal_is_never_written_to_disk_as_media(tmp_path):
    """The same trap as the speech endpoint: an error is JSON, and writing it
    produces a file that plays as nothing."""
    def refuse(method, url, headers, **kw):
        return 200, {"content-type": "application/json"}, b'{"detail":"no credits"}'
    with pytest.raises(DubError, match="answered JSON, not media"):
        dubbing.fetch("d1", "es", tmp_path / "es.mp4", "k", http=refuse)
    assert not (tmp_path / "es.mp4").exists()


def test_a_dub_that_never_finishes_names_the_id_that_was_paid_for(monkeypatch):
    monkeypatch.setattr(dubbing.time, "sleep", lambda _s: None)
    api = FakeAPI(states=("dubbing",))
    with pytest.raises(DubError, match="d1"):
        dubbing.wait("d1", "k", http=api, poll_seconds=0, poll_max=3)


def test_a_failed_dub_says_so_rather_than_hanging(monkeypatch):
    monkeypatch.setattr(dubbing.time, "sleep", lambda _s: None)
    api = FakeAPI(states=("failed",))
    with pytest.raises(DubError, match="the dub failed"):
        dubbing.wait("d1", "k", http=api, poll_seconds=0)


# -- the transcript the new subtitles come from -------------------------------

def test_word_timings_are_preferred_and_punctuation_is_dropped():
    """Spacing and punctuation arrive as their own entries with a word_type
    that is not 'word'. Burned, they put stray commas on their own frames."""
    payload = {"utterances": [{"words": [
        {"text": "Hola", "word_type": "word", "start_s": 1.0, "end_s": 1.4},
        {"text": ",", "word_type": "spacing", "start_s": 1.4, "end_s": 1.4},
        {"text": "todos", "word_type": "word", "start_s": 1.5, "end_s": 2.0}]}]}
    got = dubbing._words_from_json(payload)
    assert [w["word"] for w in got] == ["Hola", "todos"]


def test_a_zero_length_word_is_given_a_floor():
    """A word that starts and ends on the same timestamp would render for no
    frames at all."""
    got = dubbing._words_from_json({"utterances": [{"words": [
        {"text": "ya", "word_type": "word", "start_s": 3.0, "end_s": 3.0}]}]})
    assert got[0]["end"] > got[0]["start"]


def test_srt_is_the_fallback_when_there_are_no_word_timings():
    """A phrase divided evenly across its words is a guess where the json is a
    measurement -- but subtitles that are slightly off beat a paid dub that
    ships with none."""
    def api(method, url, headers, **kw):
        if url.endswith("/json"):
            return 404, {}, b""
        return 200, {}, (b"1\n00:00:01,000 --> 00:00:03,000\n"
                         b"Hola a todos\n")
    got = dubbing.transcript_words("d1", "es", "k", http=api)
    assert [w["word"] for w in got] == ["Hola", "a", "todos"]
    assert got[0]["start"] == 1.0
    assert abs(got[-1]["end"] - 3.0) < 0.01          # spans the whole cue


def test_a_dub_with_no_transcript_at_all_is_not_an_exception():
    """An instrumental cut has nothing to say. The caller is told, and decides."""
    got = dubbing.transcript_words("d1", "es", "k",
                                   http=lambda *a, **k: (404, {}, b""))
    assert got == []


def test_srt_survives_webvtt_stamps_and_a_missing_cue_number():
    """Both shapes have come back from this endpoint."""
    cues = dubbing.parse_srt("00:01.000 --> 00:02.000\nhey there\n")
    assert cues == [{"start": 1.0, "end": 2.0, "text": "hey there"}]


# -- what it would cost, and where the band goes -----------------------------

def test_the_forecast_is_a_floor_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr("fjor_studio.assemble.duration_of", lambda _p: 30.0)
    out = dub_steps.forecast(tmp_path / "final.mp4")
    assert out["seconds"] == 30.0
    assert out["usd"] == dubbing.cost_estimate(30.0) == 0.25
    assert "not a measured charge" in out["note"]


def test_an_uploaded_video_gets_their_default_band_position():
    """The source is produced elsewhere, so where the old subtitles sit is
    unknown. Their default is the starting point, and the producer moves it."""
    for w, h in ((1080, 1920), (1080, 1350), (1920, 1080)):
        g = dub_steps.band(w, h)
        assert abs(100 * (g["BY"] + g["BH"] / 2) / h - 78) < 2


def test_the_band_is_placed_where_the_producer_puts_it():
    g = dub_steps.band(1080, 1920, y_pct=50, h_pct=10)
    assert abs(100 * (g["BY"] + g["BH"] / 2) / 1920 - 50) < 1
    assert abs(100 * g["BH"] / 1920 - 10) < 1


def test_our_own_cuts_can_skip_the_guessing():
    """The one case where the anchor IS known: a cut this tool burned."""
    from fjor_studio import subtitles
    for tag, (w, h) in (("9:16", (1080, 1920)), ("4:5", (1080, 1350))):
        g = dub_steps.band_for_our_own(w, h, tag)
        assert abs((g["BY"] + g["BH"] / 2) - subtitles.POSITIONS[tag][1]) <= 2


# -- the name a dub ships under ----------------------------------------------

def test_an_uploaded_name_keeps_its_convention_and_gains_the_token():
    got = dub_steps.dubbed_name(
        "n-COR286_ch-fb_t-video_c-easy_pr-pl_ds-tool_w-34_s-1080x1350.mp4", "es")
    assert got == ("n-COR286_ch-fb_t-video_c-easy_pr-pl_ds-tool_w-34_l-es"
                   "_s-1080x1350.mp4")


def test_a_file_named_some_other_way_keeps_its_own_name():
    """Renaming somebody's file into a convention it was never in would lose
    the only handle they have on it."""
    assert dub_steps.dubbed_name("client cut v3.mp4", "pt") == \
        "client cut v3_l-pt.mp4"


def test_dubbing_a_dub_is_refused():
    """It compounds both sets of errors, and the band would cover subtitles
    that are already a translation."""
    with pytest.raises(Exception, match="ALREADY a dub"):
        dub_steps.dubbed_name(
            "n-COR286_ch-fb_t-video_c-easy_pr-pl_ds-tool_w-34_l-es"
            "_s-1080x1350.mp4", "pt")


def test_an_unknown_language_is_refused_before_a_round_trip():
    with pytest.raises(Exception, match="not a language this studio dubs"):
        dub_steps.language_name("xx")
    assert dub_steps.language_name("pt") == "Portuguese"


def test_a_dub_already_collected_is_not_bought_again(tmp_path, monkeypatch):
    """A dub is minutes long and paid; a crash after it lands must not re-buy
    it. The id is written to disk for exactly this."""
    monkeypatch.setattr(dubbing.time, "sleep", lambda _s: None)
    api = FakeAPI()

    class Job:
        job_id = "AW030"
        meta, intake, events = {}, {}, []

        def add_event(self, *a, **k):
            self.events.append(a)

    final = tmp_path / "final.mp4"
    final.write_bytes(b"x" * 50)
    out = tmp_path / "dub" / "es"
    out.mkdir(parents=True)
    (out / "dubbed.mp4").write_bytes(b"already here")
    (out / "dubbing_id.txt").write_text("d1\n")

    monkeypatch.setattr(dub_steps, "_render", lambda *a, **k: out / "x.mp4")
    monkeypatch.setattr("fjor_studio.assemble.probe", lambda _p: {
        "streams": [{"codec_type": "video", "width": 1080, "height": 1920}]})
    dub_steps.dub_video(final, out, "es", "k", http=api)
    assert not [m for m, _u in api.calls if m == "POST"]   # nothing re-bought


def test_a_dub_id_is_recorded_before_the_wait_not_after():
    """The dub is paid the moment it is accepted. An id we never wrote down is
    money we cannot collect if the wait crashes."""
    import inspect
    body = inspect.getsource(dub_steps.dub_video)
    assert body.index("record(") < body.index("dubbing.wait")
    assert body.index("id_file.write_text") < body.index("dubbing.wait")


# -- the name a dubbed cut ships under ---------------------------------------

def test_an_undubbed_name_is_unchanged_byte_for_byte():
    """Hundreds of files already carry this shape and a spreadsheet somewhere
    reads them. Adding a language must not touch a single one."""
    from fjor_studio import naming
    assert naming.build("AW023", "cartoon", 36, 1080, 1920) == (
        "n-AW023_ch-fb_t-video_c-cartoon_pr-lp_ds-nano_w-36_s-1080x1920.mp4")


def test_a_dubbed_name_carries_the_language_and_keeps_the_size_last():
    from fjor_studio import naming
    name = naming.build("AW023", "cartoon", 36, 1080, 1920, lang="es")
    assert name == (
        "n-AW023_ch-fb_t-video_c-cartoon_pr-lp_ds-nano_w-36_l-es_s-1080x1920.mp4")
    assert name.index("_l-es") < name.index("_s-1080")


def test_both_shapes_parse_and_report_the_language():
    from fjor_studio import naming
    plain = naming.parse(naming.build("AW023", "cartoon", 36, 1080, 1920))
    dubbed = naming.parse(naming.build("AW023", "cartoon", 36, 1080, 1920,
                                       lang="pt"))
    assert plain["lang"] is None and dubbed["lang"] == "pt"
    assert plain["id"] == dubbed["id"] == "AW023"       # the same creative
    # and a name that already shipped, read off the live delivery tree
    assert naming.parse(
        "n-AW025_ch-fb_t-video_c-convo_pr-lp_ds-nano_w-36_s-1080x1350.mp4"
    )["id"] == "AW025"


def test_a_real_dubbed_name_from_the_live_tree_round_trips():
    """The owner's own example, 2026-09-02. It is the authority on where the
    token sits and what it looks like -- this convention is not ours to design,
    and a file that already exists settles it."""
    from fjor_studio import naming
    real = "n-COR286_ch-fb_t-video_c-easy_pr-pl_ds-tool_w-34_l-es_s-1080x1350.mp4"
    got = naming.parse(real)
    assert got is not None
    assert got["id"] == "COR286" and got["lang"] == "es"
    assert got["source"] == "tool" and got["producer"] == "pl"
    assert naming.build(
        got["id"], got["concept"], got["week"], got["w"], got["h"],
        producer=got["producer"], channel=got["channel"], type_=got["type"],
        source=got["source"], lang=got["lang"], ext=got["ext"]) == real


def test_a_language_that_is_not_a_code_is_refused():
    from fjor_studio import naming
    with pytest.raises(ValueError, match="not a language code"):
        naming.build("AW023", "cartoon", 36, 1080, 1920, lang="spanish")
