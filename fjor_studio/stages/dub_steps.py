"""Dubbing a finished creative into another language.

The source is an UPLOAD: the owner's own video, but produced elsewhere and
dropped on the dashboard, not built by this tool. That matters, because it
means the old burnt-in subtitles are opaque pixels of unknown position -- the
same situation their tool is in, and the reason their producer drags a
rectangle over them by hand.

So: their method, kept whole.

    the uploaded video  ->  one dub  ->  a dubbed video
    a blurred band over the old burnt-in subtitles          (`dubband`)
    new subtitles burned from the word timings the dub returns

Where the band goes cannot be computed for an upload, so it is a parameter,
defaulted to theirs (78% down, 15% tall) and previewed as a still frame before
anything is bought -- the dashboard's substitute for the mouse. Sight is the
part that matters; the drag was only ever how they got it.

The one case where it CAN be computed is a cut this tool produced itself, whose
subtitle anchor we know: `band_for_our_own` covers it, and nothing else uses it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import dubband, dubbing, naming, subtitles
from ..gen.base import GenError

# What ElevenLabs will dub into. Their tool lists more; these are the ones this
# studio's verticals actually ship, and an unknown code is refused rather than
# sent -- a rejected submission still costs a round trip.
LANGUAGES: Dict[str, str] = {
    "es": "Spanish", "pt": "Portuguese", "fr": "French", "de": "German",
    "it": "Italian", "pl": "Polish", "nl": "Dutch", "sv": "Swedish",
    "en": "English", "ru": "Russian", "tr": "Turkish", "ja": "Japanese",
    "ko": "Korean", "hi": "Hindi", "ar": "Arabic", "id": "Indonesian",
    "fil": "Filipino", "uk": "Ukrainian", "cs": "Czech", "ro": "Romanian",
}


def language_name(code: str) -> str:
    code = str(code or "").strip().lower()
    if code not in LANGUAGES:
        raise GenError(
            f"'{code}' is not a language this studio dubs into. Known: "
            f"{', '.join(sorted(LANGUAGES))}")
    return LANGUAGES[code]


def forecast(final: Path) -> Dict[str, Any]:
    """What dubbing this cut would cost, before any of it is bought."""
    from ..assemble import duration_of
    seconds = float(duration_of(Path(final)))
    return {"seconds": round(seconds, 1), "usd": dubbing.cost_estimate(seconds),
            "note": "their published rate, not a measured charge"}


def band(width: int, height: int, y_pct: float = dubband.BAND_Y_PCT,
         h_pct: float = dubband.BAND_H_PCT,
         feather: float = dubband.FEATHER_DEFAULT,
         strength: float = dubband.STRENGTH_DEFAULT) -> Dict[str, Any]:
    """Where the band goes on an uploaded video: the producer's call.

    Their defaults, because they are the ones that have been shipping. Height
    stays generous on purpose -- too tight is the failure that ships, since a
    surviving sliver of the old word reads as a glitch, while a band a little
    larger than it needs to be reads as a blur, which is what it is."""
    return dubband.geometry(width, height, y_pct=y_pct, h_pct=h_pct,
                            feather=feather, strength=strength)


def band_for_our_own(width: int, height: int, size_tag: str) -> Dict[str, Any]:
    """The band for a cut THIS tool burned subtitles into, where the anchor is
    known rather than guessed. Uploads never take this path."""
    anchor = subtitles.POSITIONS.get(size_tag)
    if not anchor:
        return band(width, height)
    play_y = 1920 if size_tag == "9:16" else 1350
    return band(width, height, y_pct=100.0 * anchor[1] / play_y)


def preview(video: Path, dest: Path, geom: Dict[str, Any], ffmpeg: str,
            at_seconds: float = 0.0) -> Path:
    """One frame with the band applied, so the producer can SEE where it lands
    before a dub is bought. This is what replaces their drag: they position by
    mouse and watch it live, we position by number and look at the result.

    Cheap on purpose -- a still costs nothing and a dub does not."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-ss", f"{max(0.0, at_seconds):.2f}",
         "-i", str(Path(video).resolve()), "-filter_complex",
         dubband.filter_chain(geom), "-frames:v", "1", str(dest.resolve())],
        capture_output=True, text=True)
    if proc.returncode != 0 or not dest.exists():
        raise GenError(f"dub: could not preview the band: {proc.stderr[-400:]}")
    return dest


def dubbed_name(original: str, lang: str) -> str:
    """The dubbed file's name: the original's, plus the language token.

    An upload usually already carries the convention -- these are the owner's
    own creatives -- so the token slots into the name it came with. A file
    named some other way keeps its stem and gets the token appended, which is
    ugly but honest: renaming somebody's file into a convention it was never
    in would lose the only handle they have on it."""
    parsed = naming.parse(original)
    if parsed:
        if parsed.get("lang"):
            raise GenError(
                f"{original} is ALREADY a dub ({parsed['lang']}). Dub the "
                f"original cut -- dubbing a dub compounds both sets of errors.")
        return naming.build(
            parsed["id"], parsed["concept"], parsed["week"], parsed["w"],
            parsed["h"], producer=parsed["producer"], channel=parsed["channel"],
            type_=parsed["type"], source=parsed["source"], lang=lang,
            ext=parsed["ext"])
    stem, dot, ext = str(original).rpartition(".")
    return f"{stem or original}_l-{lang}{dot}{ext}"


def dub_video(source: Path, out_dir: Path, target_lang: str, api_key: str,
              geom: Optional[Dict[str, Any]] = None,
              style: Optional[subtitles.SubtitleStyle] = None,
              on_progress: Optional[Callable[[str], None]] = None,
              http: Optional[Callable] = None,
              ffmpeg: Optional[str] = None,
              record: Optional[Callable[..., None]] = None) -> Dict[str, Any]:
    """Dub one video. The whole of it, once -- their way.

    `record` is how the caller keeps the dubbing id: it is called the moment
    the dub is ACCEPTED, before the wait, because the dub is paid from that
    instant and an id nobody wrote down is money that cannot be collected."""
    from ..assemble import ffmpeg_with_libass, probe

    source, out_dir = Path(source), Path(out_dir)
    if not source.is_file():
        raise GenError(f"there is nothing to dub at {source}")
    lang = str(target_lang).strip().lower()
    language_name(lang)                     # refuse an unknown code up front
    out_dir.mkdir(parents=True, exist_ok=True)
    raw, id_file = out_dir / "dubbed.mp4", out_dir / "dubbing_id.txt"

    if raw.exists() and id_file.exists():
        # already bought on an earlier attempt. A dub is not cheap enough to
        # buy twice because something downstream crashed.
        if on_progress:
            on_progress(f"reusing the {language_name(lang)} dub already on disk")
    else:
        if on_progress:
            on_progress(f"dubbing the whole cut into {language_name(lang)}")
        dubbing_id = dubbing.submit(source, lang, api_key, http=http)
        id_file.write_text(dubbing_id + "\n")
        if record:
            record("dub_submitted", f"dub {dubbing_id} into {lang}",
                   dubbing_id=dubbing_id, lang=lang)
        dubbing.wait(dubbing_id, api_key, http=http, on_progress=on_progress)
        dubbing.fetch(dubbing_id, lang, raw, api_key, http=http)

    dubbing_id = id_file.read_text().strip()
    words_raw = dubbing.transcript_words(dubbing_id, lang, api_key, http=http)
    if on_progress:
        on_progress(f"{len(words_raw)} words of {language_name(lang)} subtitles")

    info = probe(raw)
    stream = next((s for s in info.get("streams", [])
                   if s.get("codec_type") == "video"), {})
    width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    if not width or not height:
        raise GenError(f"could not read the dubbed video's size from {raw}")
    if geom is None:
        geom = band(width, height)
    elif (geom.get("width"), geom.get("height")) != (width, height):
        # the band was measured on the SOURCE; the dub can come back at a
        # different size, and a band in the wrong place covers nothing
        geom = band(width, height, y_pct=100.0 * (geom["BY"] + geom["BH"] / 2)
                    / max(1, geom["height"]),
                    h_pct=100.0 * geom["BH"] / max(1, geom["height"]),
                    feather=geom.get("feather_pct", dubband.FEATHER_DEFAULT),
                    strength=geom.get("strength", dubband.STRENGTH_DEFAULT))

    size_tag = "4:5" if abs(width / max(1, height) - 0.8) < 0.02 else "9:16"
    ass_path = out_dir / "subs.ass"
    words = [subtitles.Word(w["word"], w["start"], w["end"]) for w in words_raw]
    ass_path.write_text(subtitles.build_ass(words, size_tag,
                                            style or subtitles.SubtitleStyle()))

    dest = out_dir / f"dubbed_{lang}.mp4"
    _render(raw, ass_path, dest, geom, ffmpeg or ffmpeg_with_libass())
    return {"video": dest, "raw": raw, "dubbing_id": dubbing_id, "lang": lang,
            "words": len(words), "band": geom, "subtitles": bool(words),
            "width": width, "height": height,
            "note": ("" if words else
                     "the dub returned no transcript, so this cut carries the "
                     "blur band but NO new subtitles -- the old ones are "
                     "covered and nothing replaces them")}


def _render(source: Path, ass_path: Path, dest: Path, geom: Dict[str, Any],
            ffmpeg: str) -> Path:
    """Band and subtitles in ONE pass.

    Two passes would mean two h264 re-encodes of a cut that has already been
    encoded twice -- once by whoever made it, once by the dub -- and the band's
    soft edge is exactly the kind of low-contrast gradient the next one sits on.
    Audio is copied: it is the dub, and re-encoding it buys nothing."""
    from ..assemble import PIX_FMT
    fonts = Path(__file__).resolve().parents[2] / "assets" / "fonts"
    chain = dubband.filter_chain(geom) + f",subtitles=filename={ass_path.name}"
    if fonts.is_dir():
        chain += f":fontsdir={fonts}"
    proc = subprocess.run(
        [ffmpeg, "-y", "-v", "error", "-i", str(Path(source).resolve()),
         "-filter_complex", chain, "-c:v", "libx264", "-preset", "veryfast",
         "-crf", "21", "-pix_fmt", PIX_FMT, "-c:a", "copy",
         "-movflags", "+faststart", str(Path(dest).resolve())],
        capture_output=True, text=True, cwd=str(ass_path.parent))
    if proc.returncode != 0 or not Path(dest).exists():
        raise GenError(f"dub: band and subtitles failed: {proc.stderr[-400:]}")
    return Path(dest)
