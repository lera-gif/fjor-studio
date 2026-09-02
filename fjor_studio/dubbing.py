"""Dubbing a finished creative into another language.

Their way, deliberately. They have shipped dubs like this for a long time and
the shape of it is not ours to improve:

    the whole exported video  ->  ElevenLabs dubbing  ->  a dubbed video
    a blurred band covers the old burnt-in subtitles
    new subtitles are burned from the word timings the dub returns

An earlier draft here dubbed the CLIPS instead and re-assembled, which avoids
the band entirely because our clips never carried subtitles. It was rejected,
and the reason is worth writing down: a whole-file dub is what they have
proven, the band is a solved problem in their hands, and a cut re-assembled
from separately dubbed clips is not the same cut -- the mix, the music bed and
every transition would be rebuilt, and any of them could differ from the
English original that was approved. Dubbing the finished file changes the
speech and nothing else.

Their band geometry lives in `dubband`; the transcript path is below.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .gen import http as http_mod
from .gen.base import GenError

BASE = "https://api.elevenlabs.io"

# Their measured numbers, kept because they were paid for: the API bills by
# duration and a long file is both slow and expensive.
PRICE_PER_MINUTE_USD = 0.50
POLL_SECONDS = 5.0
POLL_MAX = 720                      # 720 x 5s = one hour, their ceiling

# What their tool sends. `dubbing_studio: false` is the automatic pipeline --
# the editable Studio mode is deprecated and its API is in maintenance.
FORM_DEFAULTS = (("dubbing_studio", "false"),
                 ("disable_voice_cloning", "false"),
                 ("drop_background_audio", "false"),
                 ("num_speakers", "0"),
                 ("highest_resolution", "true"))


class DubError(GenError):
    pass


def cost_estimate(seconds: float) -> float:
    """What a dub of this length costs, in dollars. A FLOOR, like every other
    forecast here: their published rate, not a measured charge."""
    return round(max(0.0, seconds) / 60.0 * PRICE_PER_MINUTE_USD, 2)


def submit(path: Path, target_lang: str, api_key: str,
           source_lang: str = "auto", base: str = BASE,
           http: Optional[Callable] = None) -> str:
    """Start a dub. Returns the id to poll."""
    from .subtitles import _multipart
    path = Path(path)
    if not path.is_file():
        raise DubError(f"nothing to dub at {path}")
    fields = list(FORM_DEFAULTS) + [("target_lang", target_lang),
                                    ("source_lang", source_lang),
                                    ("name", path.stem[:60])]
    body, content_type = _multipart(fields, "file", path)
    status, _headers, raw = (http or http_mod.request)(
        "POST", f"{base}/v1/dubbing",
        {"xi-api-key": api_key, "Content-Type": content_type},
        data=body, timeout=600.0)
    payload = _json_or_raise(status, raw, "starting the dub")
    dubbing_id = str(payload.get("dubbing_id") or "").strip()
    if not dubbing_id:
        raise DubError(f"no dubbing_id came back: {json.dumps(payload)[:200]}")
    return dubbing_id


def wait(dubbing_id: str, api_key: str, base: str = BASE,
         http: Optional[Callable] = None,
         on_progress: Optional[Callable[[str], None]] = None,
         poll_seconds: float = POLL_SECONDS, poll_max: int = POLL_MAX) -> None:
    """Block until the dub is done, or say why it never will be."""
    call = http or http_mod.request
    for tick in range(poll_max):
        status, _h, raw = call("GET", f"{base}/v1/dubbing/{dubbing_id}",
                               {"xi-api-key": api_key}, timeout=60.0)
        payload = _json_or_raise(status, raw, "checking the dub")
        state = str(payload.get("status") or "").lower()
        if state == "dubbed":
            return
        if state in ("failed", "error"):
            raise DubError(
                f"the dub failed: {payload.get('error') or json.dumps(payload)[:200]}")
        if on_progress and tick % 6 == 0:
            on_progress(f"dubbing… ({state or 'queued'}, {int(tick * poll_seconds)}s)")
        time.sleep(poll_seconds)
    raise DubError(
        f"the dub is still not finished after {int(poll_max * poll_seconds / 60)} "
        f"minutes. It is PAID and it may still complete -- the id is "
        f"{dubbing_id}, and collecting it later costs nothing.")


def fetch(dubbing_id: str, target_lang: str, dest: Path, api_key: str,
          base: str = BASE, http: Optional[Callable] = None) -> Path:
    """Collect the dubbed media. Kept as it arrives; ffmpeg reads it."""
    status, headers, raw = (http or http_mod.request)(
        "GET", f"{base}/v1/dubbing/{dubbing_id}/audio/{target_lang}",
        {"xi-api-key": api_key}, timeout=600.0)
    if status >= 400 or not raw:
        raise DubError(
            f"could not collect dub {dubbing_id} ({status}): "
            f"{raw[:200].decode('utf-8', 'replace')}")
    kind = str(headers.get("content-type", ""))
    if kind.startswith("application/json"):
        # the same trap as the speech endpoint: a refusal is JSON, and writing
        # it to disk produces a "track" that plays as nothing
        raise DubError(f"the dub endpoint answered JSON, not media: "
                       f"{raw[:200].decode('utf-8', 'replace')}")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    return dest


def _json_or_raise(status: int, raw: bytes, what: str) -> Dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        raise DubError(f"{what}: {status}, unreadable answer "
                       f"{raw[:200].decode('utf-8', 'replace')}")
    if status >= 400:
        detail = payload.get("detail") or payload
        raise DubError(f"{what}: {status}, {json.dumps(detail)[:300]}")
    return payload


# -- the new subtitles -------------------------------------------------------
#
# Their order, and their fallback: ask for `json`, which carries a time per
# WORD, and fall back to `srt`, which carries a time per PHRASE that then has
# to be divided across its words. The fallback is worth having -- a phrase
# split evenly reads acceptably, and no subtitles at all on a paid dub does
# not -- but it is a guess where the json is a measurement, so it says so.

TRANSCRIPT_FORMATS = ("json", "srt")
MIN_WORD_S = 0.05                   # their floor for a zero-length word


def transcript_words(dubbing_id: str, target_lang: str, api_key: str,
                     base: str = BASE,
                     http: Optional[Callable] = None) -> List[Dict[str, Any]]:
    """Word timings for the dubbed speech: [{word, start, end}], time-ordered.

    Empty is a legitimate answer -- an instrumental cut has nothing to say --
    and the caller decides whether that is a surprise."""
    call = http or http_mod.request
    stem = f"{base}/v1/dubbing/{dubbing_id}/transcripts/{target_lang}/format/"

    def grab(fmt: str):
        try:
            status, _h, raw = call("GET", stem + fmt,
                                   {"xi-api-key": api_key}, timeout=120.0)
        except Exception:  # noqa: BLE001
            return None
        if status >= 400 or not raw:
            return None
        text = raw.decode("utf-8", "replace")
        try:
            return text, json.loads(text)
        except Exception:  # noqa: BLE001
            return text, None

    got = grab("json")
    if got and got[1] is not None:
        payload = got[1]
        if isinstance(payload, dict) and payload.get("json") is not None:
            payload = payload["json"]
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:  # noqa: BLE001
                payload = None
        words = _words_from_json(payload)
        if words:
            return words

    got = grab("srt")
    if got:
        text, wrapped = got
        if isinstance(wrapped, dict):
            text = wrapped.get("srt") or wrapped.get("webvtt") or ""
        words: List[Dict[str, Any]] = []
        for cue in parse_srt(text):
            words.extend(split_sentence(cue["start"], cue["end"], cue["text"]))
        if words:
            return words
    return []


def _words_from_json(payload: Any) -> List[Dict[str, Any]]:
    """Their filter, and the reason for it: spacing and punctuation arrive as
    their own entries with `word_type` set to something other than 'word', and
    burning them puts stray commas on their own frames."""
    utterances = []
    if isinstance(payload, dict):
        utterances = payload.get("utterances") or payload.get("segments") or []
    if not isinstance(utterances, list):
        return []
    words: List[Dict[str, Any]] = []
    for utt in utterances:
        for w in (utt.get("words") or []) if isinstance(utt, dict) else []:
            if not isinstance(w, dict):
                continue
            text = str(w.get("text") or "").strip()
            if not text:
                continue
            kind = str(w.get("word_type") or "").lower()
            if kind and kind != "word":
                continue
            try:
                start, end = float(w["start_s"]), float(w["end_s"])
            except (KeyError, TypeError, ValueError):
                continue
            words.append({"word": text, "start": start,
                          "end": max(start + MIN_WORD_S, end)})
    if not words:                   # no per-word timings at all: split phrases
        for utt in utterances:
            if not isinstance(utt, dict):
                continue
            text = str(utt.get("text") or "").strip()
            try:
                start, end = float(utt["start_s"]), float(utt["end_s"])
            except (KeyError, TypeError, ValueError):
                continue
            if text and end > start:
                words.extend(split_sentence(start, end, text))
    return sorted(words, key=lambda w: w["start"])


_SRT_TIME = re.compile(
    r"((?:\d+:)?\d{1,2}:\d{2}[,.]\d{1,3})\s*-->\s*((?:\d+:)?\d{1,2}:\d{2}[,.]\d{1,3})")


def parse_srt(text: str) -> List[Dict[str, Any]]:
    """SRT or WebVTT into cues. Tolerant of both, and of a missing cue number,
    because the endpoint has been seen to return each."""
    cues: List[Dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", str(text or "").replace("\r\n", "\n")):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        i = 0 if "-->" in lines[0] else 1
        if i >= len(lines):
            continue
        m = _SRT_TIME.search(lines[i])
        if not m:
            continue
        start, end = _srt_seconds(m.group(1)), _srt_seconds(m.group(2))
        if start is None or end is None or end <= start:
            continue
        body = " ".join(lines[i + 1:])
        body = re.sub(r"<[^>]*>", "", body)
        body = re.sub(r"\{[^}]*\}", "", body)
        body = re.sub(r"\s+", " ", body).strip()
        if body:
            cues.append({"start": start, "end": end, "text": body})
    return cues


def _srt_seconds(stamp: str) -> Optional[float]:
    parts = str(stamp).replace(",", ".").split(":")
    try:
        parts = [float(p) for p in parts]
    except ValueError:
        return None
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def split_sentence(start: float, end: float, text: str) -> List[Dict[str, Any]]:
    """A phrase divided evenly across its words -- a guess, not a measurement."""
    tokens = [t for t in str(text or "").split() if t]
    if not tokens:
        return []
    per = max(MIN_WORD_S, (end - start)) / len(tokens)
    return [{"word": tok, "start": start + i * per, "end": start + (i + 1) * per}
            for i, tok in enumerate(tokens)]
