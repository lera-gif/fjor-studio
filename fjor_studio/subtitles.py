"""Subtitles: transcribe the cut, then burn word-by-word ASS over it.

The mechanics are the colleague's, whose subtitle path is the most-iterated part
of their tool. What carried over, and why each detail is there:

- **`\\an5\\pos(x,y)` on every single line.** Anchoring by absolute centre on all
  dialogues is what stops libass drifting the text between frames and lines.
- **Chain-link end times.** A word's end is the NEXT word's start, not its own
  end. Without the overlap libass stacks lines on top of each other.
- **A hard right clamp.** Subtitles must stop before the packshot: without it the
  last line's tail draws over the end card.
- **No lead shift.** Whisper does put word starts slightly late, and compensating
  for it is a one-line change here -- but the colleague tried 0.20s and reverted
  it because it looked worse. `lead_s` defaults to 0 for that reason, not
  because nobody thought about it.
- **A lexicon pass.** Whisper reliably mangles the words these ads are about --
  "Pilates" especially -- and prints "pounds" where house style is "lbs".

Note this is the OPPOSITE direction to the phonetic dictionary the owner dropped:
that one changed what the model SAYS, this one fixes what the transcriber HEARS.
"""
from __future__ import annotations

import json
import mimetypes
import re
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .gen import http as http_mod
from .gen.base import GenError

WHISPER_URL = "https://api.openai.com/v1/audio/transcriptions"

# House style, applied to whole alphabetic tokens only: "Pounds," -> "lbs,"
# while "compound" is untouched.
LEXICON: Dict[str, str] = {"pounds": "lbs", "pound": "lb"}

# Terms Whisper mishears in these verticals. Key is what it writes, value what
# it meant. Extend per vertical rather than guessing with fuzzy matching.
VOCABULARY: Dict[str, str] = {
    "pilates": "Pilates", "potties": "Pilates", "pilate": "Pilates",
    "palates": "Pilates", "pilaties": "Pilates",
    "lymphatic": "Lymphatic", "limfatic": "Lymphatic",
    "cortisol": "Cortisol", "cortisole": "Cortisol",
}

COLOURS = {"white": "FFFFFF", "yellow": "FFE948", "red": "EF4444",
           "green": "10B981"}
SIZES = {"small": 56, "medium": 72, "large": 90}

# Where the text sits, per frame shape: 78% down a 9:16 frame, 81% down a 4:5
# one -- both inside the safe zone, both above the disclaimer band.
POSITIONS = {"9:16": (540, 1500), "4:5": (540, 1100)}

# How long a word may stay up after it has been spoken. The chain-link below
# holds every word until the NEXT one starts, which is what stops libass
# stacking two lines -- but across a silence it holds forever. LME108: "up" was
# the last word of scene 0 and the next word was 25s away, so "UP" sat over
# three silent scenes. Normal inter-word gaps are well under this, so the
# chain-link is untouched where there is speech; only a real pause breaks it.
MAX_HOLD_S = 0.8


@dataclass
class Word:
    word: str
    start: float
    end: float


@dataclass
class SubtitleStyle:
    style: str = "bold-pop"
    colour: str = "yellow"
    size: str = "medium"
    lead_s: float = 0.0
    font: str = "Inter"


# -- transcription -----------------------------------------------------------

def extract_audio(video: Path, dest: Path, ffmpeg: str = "ffmpeg") -> Path:
    proc = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(video), "-vn",
         "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-q:a", "4", str(dest)],
        capture_output=True, text=True)
    if proc.returncode != 0 or not dest.exists():
        raise GenError(f"subtitles: could not extract audio: {proc.stderr[-300:]}")
    return dest


def _multipart(fields: Sequence[Tuple[str, str]],
               file_field: str, path: Path) -> Tuple[bytes, str]:
    boundary = f"----fjorstudio{uuid.uuid4().hex}"
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts: List[bytes] = []
    for name, value in fields:
        parts.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n"
            f"\r\n{value}\r\n".encode("utf-8"))
    parts.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
        f"filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode("utf-8"))
    parts.append(path.read_bytes())
    parts.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def transcribe(audio: Path, api_key: str, model: str = "whisper-1",
               prompt: str = "", http=None) -> List[Word]:
    """Word-level timings. `prompt` is a vocabulary hint -- naming the terms up
    front makes Whisper spell them right rather than needing repair afterwards."""
    if not api_key:
        raise GenError("subtitles need auth.yaml openai.api_key for transcription")
    fields = [("model", model), ("response_format", "verbose_json"),
              ("timestamp_granularities[]", "word")]
    if prompt:
        fields.append(("prompt", prompt))
    body, content_type = _multipart(fields, "file", audio)
    fn = http or http_mod.request
    _status, _hdrs, raw = fn("POST", WHISPER_URL,
                             {"Authorization": f"Bearer {api_key}",
                              "Content-Type": content_type},
                             None, body, 600.0)
    data = json.loads(raw.decode("utf-8"))
    words = data.get("words")
    if not words:
        # a cut with no speech at all is legitimate -- say so rather than failing
        return []
    return [Word(str(w.get("word", "")).strip(),
                 float(w.get("start", 0.0)), float(w.get("end", 0.0)))
            for w in words if str(w.get("word", "")).strip()]


# -- word list repair --------------------------------------------------------

_ALPHA = re.compile(r"[A-Za-z]+")


def lexicon_fix(words: Sequence[Word],
                extra: Optional[Dict[str, str]] = None) -> List[Word]:
    table = dict(LEXICON)
    table.update(VOCABULARY)
    table.update({k.lower(): v for k, v in (extra or {}).items()})

    def fix(token: str) -> str:
        return _ALPHA.sub(lambda m: table.get(m.group(0).lower(), m.group(0)), token)

    return [Word(fix(w.word), w.start, w.end) for w in words]


def apply_lead(words: Sequence[Word], lead_s: float) -> List[Word]:
    """Shift every word earlier by `lead_s`. Monotonic order is preserved
    because the shift is uniform and clamped at zero."""
    if not lead_s:
        return list(words)
    out = []
    for w in words:
        start = max(0.0, w.start - lead_s)
        out.append(Word(w.word, start, max(start + 0.01, w.end - lead_s)))
    return out


def clamp(words: Sequence[Word], end_s: float) -> List[Word]:
    """Drop and trim words past a hard right boundary -- the packshot start.
    Without this the last line's tail draws over the end card."""
    if not end_s:
        return list(words)
    out = []
    for w in words:
        if w.start >= end_s - 0.06:
            continue
        out.append(Word(w.word, w.start, min(w.end, end_s)))
    return out


# -- ASS ---------------------------------------------------------------------

def ass_time(sec: float) -> str:
    if sec != sec or sec < 0:          # NaN or negative -> libass drops the line
        sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec - h * 3600 - m * 60
    return f"{h}:{m:02d}:{s:05.2f}"


def bgr(hex_rgb: str) -> str:
    return f"&H00{hex_rgb[4:6]}{hex_rgb[2:4]}{hex_rgb[0:2]}"


def build_ass(words: Sequence[Word], size_tag: str,
              style: Optional[SubtitleStyle] = None,
              clamp_end_s: float = 0.0) -> str:
    style = style or SubtitleStyle()
    if size_tag not in POSITIONS:
        raise GenError(f"subtitles: no text position for size '{size_tag}'")
    play_x, play_y = (1080, 1920) if size_tag == "9:16" else (1080, 1350)
    pos_x, pos_y = POSITIONS[size_tag]
    font_size = SIZES.get(style.size, SIZES["medium"])
    accent = bgr(COLOURS.get(style.colour, COLOURS["yellow"]))
    white, black = bgr("FFFFFF"), bgr("000000")

    words = clamp(apply_lead(words, style.lead_s), clamp_end_s)
    # every dialogue carries the same absolute anchor: zero drift between lines
    prefix = rf"\an5\pos({pos_x},{pos_y})"
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {play_x}\n"
        f"PlayResY: {play_y}\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
        "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
        "MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{style.font},{font_size},{white},{accent},{black},"
        "&H80000000,1,0,0,0,100,100,0,0,1,4,2,5,90,90,40,1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
        "Effect, Text\n")
    if not words:
        return header

    lines = []
    for i, w in enumerate(words):
        # chain-link: this word holds until the next one starts, so libass never
        # stacks two lines at once
        nxt = words[i + 1].start if i + 1 < len(words) else w.end + 0.5
        nxt = min(nxt, w.end + MAX_HOLD_S)      # a pause drops the word, see above
        if clamp_end_s and nxt > clamp_end_s:
            nxt = clamp_end_s
        end = max(w.start + 0.05, nxt)
        text = re.sub(r"[\\{}]", "", w.word).replace("\n", " ").upper()
        lines.append(f"Dialogue: 0,{ass_time(w.start)},{ass_time(end)},Default,,"
                     f"0,0,0,,{{{prefix}\\fad(40,30)}}{text}")
    return header + "\n".join(lines) + "\n"


def burn(video: Path, ass_path: Path, dest: Path, ffmpeg: str,
         fonts_dir: Optional[Path] = None, crf: int = 21,
         preset: str = "veryfast") -> Path:
    """Render the ASS onto the video with libass.

    `fontsdir` is not optional in practice: Inter is not installed on this
    machine, and without it libass silently renders in Verdana."""
    from .assemble import PIX_FMT   # the same 4:2:0 pin as every other encode

    # ffmpeg runs with cwd = the ass file's directory so the filter argument
    # needs no path escaping, which is otherwise a reliable source of pain
    filt = f"subtitles=filename={ass_path.name}"
    if fonts_dir:
        filt += f":fontsdir={Path(fonts_dir).resolve()}"
    proc = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(Path(video).resolve()),
         "-vf", filt, "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
         "-pix_fmt", PIX_FMT, "-c:a", "copy", "-movflags", "+faststart",
         str(Path(dest).resolve())],
        capture_output=True, text=True, cwd=str(ass_path.parent))
    if proc.returncode != 0 or not Path(dest).exists():
        raise GenError(f"subtitles: burning failed: {proc.stderr[-400:]}")
    return Path(dest)
