"""Assembly: pure ffmpeg, no model calls, and therefore free to re-run.

Everything the producer usually wants to change late -- where the packshot
sits, which one, how long it holds -- lives here, which is why `reassemble`
can rewind to it without re-buying a single clip.

Two constraints shaped this file:

- **This ffmpeg has neither `drawtext` nor libass.** Text cannot be rendered at
  assembly time, so the disclaimer and the "Created with AI" badge are overlaid
  as pre-rendered transparent PNGs from `assets/disclaimers/`. Those are approved
  compliance assets carrying the exact `standards.yaml` wording; they are
  overlaid, never re-typeset.
- **Clips do not all carry audio.** Seedance renders speech into the picture,
  but a packshot or a still may be silent, and concatenating a mixture drops the
  audio track entirely. Every segment is normalised to the same video AND audio
  shape first, with silence synthesised where there is none.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

FPS = 30
SAMPLE_RATE = 48000

# Every encode is pinned to 4:2:0. An overlay of an RGBA PNG, or the `ass`
# filter, negotiates the chain up to yuv444p, and libx264 will happily
# encode High 4:4:4 Predictive -- which no browser decodes and no ad
# platform accepts. The file looks fine to ffprobe and plays in VLC, so
# nothing catches it until a producer sees a blank player.
PIX_FMT = "yuv420p"


class AssembleError(Exception):
    pass


def _bin(name: str) -> str:
    found = shutil.which(name)
    if not found:
        raise AssembleError(f"{name} is not on PATH -- assembly needs ffmpeg")
    return found


def _has_libass(exe: str) -> bool:
    try:
        out = subprocess.run([exe, "-hide_banner", "-buildconf"],
                             capture_output=True, text=True, timeout=30)
        return "--enable-libass" in (out.stdout + out.stderr)
    except Exception:  # noqa: BLE001
        return False


# Where an ffmpeg that can render ASS subtitles might live. The one on PATH is
# tried first and is usually the answer; the rest are for the case that bit us
# on macOS, where Homebrew's `ffmpeg` formula ships WITHOUT libass and the build
# that has it is installed alongside, keg-only, off PATH. Nothing here is
# required to exist -- a machine where the PATH ffmpeg is complete never looks
# past the first candidate.
LIBASS_HINTS = (
    "ffmpeg-full", "ffmpeg7", "ffmpeg6",          # alternative names on PATH
    "/opt/homebrew/Cellar/ffmpeg*/*/bin/ffmpeg",  # macOS, Apple silicon
    "/usr/local/Cellar/ffmpeg*/*/bin/ffmpeg",     # macOS, Intel
    "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg",
    "/usr/bin/ffmpeg", "/snap/bin/ffmpeg",        # Linux
)


def ffmpeg_candidates() -> List[str]:
    """Every ffmpeg worth asking, PATH first, in order."""
    out: List[str] = []
    override = os.environ.get("FJOR_STUDIO_FFMPEG")
    if override:
        out.append(override)                      # the operator's answer wins
    found = shutil.which("ffmpeg")
    if found:
        out.append(found)
    for hint in LIBASS_HINTS:
        if hint.startswith("/"):
            out.extend(sorted(str(p) for p in Path("/").glob(hint.lstrip("/"))))
        else:
            named = shutil.which(hint)
            if named:
                out.append(named)
    seen, uniq = set(), []
    for exe in out:
        if exe not in seen:
            seen.add(exe)
            uniq.append(exe)
    return uniq


def ffmpeg_with_libass() -> str:
    """An ffmpeg that can render ASS subtitles.

    Searched rather than hard-coded, because the answer differs per machine:
    a Linux ffmpeg is normally built with libass, while Homebrew's `ffmpeg`
    formula is not and keeps the complete build keg-only under Cellar. If none
    of them has it we say so, rather than running a filter that does not exist.

    $FJOR_STUDIO_FFMPEG overrides the search for a deployment that ships its
    own binary."""
    for exe in ffmpeg_candidates():
        if _has_libass(exe):
            return exe
    raise AssembleError(
        "no ffmpeg with libass was found, so subtitles cannot be burned. "
        "Install one (macOS: `brew install ffmpeg-full`; Debian/Ubuntu: "
        "`apt install ffmpeg`), point $FJOR_STUDIO_FFMPEG at it, or turn "
        "subtitles off in pipeline.yaml.")


def run(args: Sequence[str], what: str) -> None:
    proc = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise AssembleError(f"{what} failed:\n  " + "\n  ".join(tail))


def probe(path: Path) -> Dict[str, Any]:
    out = subprocess.run(
        [_bin("ffprobe"), "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True)
    if out.returncode != 0:
        raise AssembleError(f"ffprobe failed on {path}: {out.stderr[:200]}")
    return json.loads(out.stdout or "{}")


def duration_of(path: Path) -> float:
    info = probe(path)
    return float((info.get("format") or {}).get("duration") or 0.0)


def has_audio(path: Path) -> bool:
    return any(s.get("codec_type") == "audio"
               for s in (probe(path).get("streams") or []))


@dataclass
class Size:
    w: int
    h: int
    tag: str

    @property
    def slug(self) -> str:
        return self.tag.replace(":", "_")


SIZES = {"9:16": Size(1080, 1920, "9:16"), "4:5": Size(1080, 1350, "4:5")}


def normalise(src: Path, dest: Path, size: Size, mute: bool = False,
              trim_s: Optional[float] = None,
              audio: Optional[Path] = None) -> Path:
    """One segment, in the exact shape concat requires.

    scale-to-cover then centre-crop -- never pad. A padded 9:16 source in a 4:5
    frame reads as a mistake, and the reference material is always shot full
    bleed."""
    vf = (f"scale={size.w}:{size.h}:force_original_aspect_ratio=increase,"
          f"crop={size.w}:{size.h},setsar=1,fps={FPS},format=yuv420p")
    cmd: List[str] = [_bin("ffmpeg"), "-y", "-v", "error"]
    if trim_s:
        cmd += ["-t", f"{trim_s:.3f}"]
    cmd += ["-i", str(src)]
    # A shot generated silent gets its spoken line here. Padded with silence so
    # a voiceover shorter than its shot does not truncate the picture, and cut
    # to the shot's length so a longer one does not stretch it.
    if audio:
        # apad, not amix: mixing against a silence source made the shortest
        # input win, so a 2.5s voiceover cut a 4s shot down to 2.5s. Padding
        # runs the voice then silence forever, and -shortest trims to the video.
        cmd += ["-i", str(audio), "-filter_complex",
                f"[1:a]aresample={SAMPLE_RATE},apad[aout]"]
        silent = False
    else:
        silent = mute or not has_audio(src)
        if silent:
            # a segment with no audio track would drop the whole concat's audio
            cmd += ["-f", "lavfi", "-i",
                    f"anullsrc=channel_layout=stereo:sample_rate={SAMPLE_RATE}"]
    cmd += ["-vf", vf, "-map", "0:v:0",
            "-map", ("[aout]" if audio else ("1:a:0" if silent else "0:a:0")),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", PIX_FMT, "-c:a", "aac", "-b:a", "160k",
            "-ar", str(SAMPLE_RATE), "-ac", "2",
            "-shortest", "-movflags", "+faststart", str(dest)]
    run(cmd, f"normalising {src.name} to {size.tag}")
    return dest


def has_filter(name: str, exe: Optional[str] = None) -> bool:
    try:
        out = subprocess.run([exe or _bin("ffmpeg"), "-hide_banner", "-filters"],
                             capture_output=True, text=True, timeout=30)
        return any(line.split()[1:2] == [name]
                   for line in (out.stdout + out.stderr).splitlines()
                   if len(line.split()) > 1)
    except Exception:  # noqa: BLE001
        return False


def crossfade(segments: Sequence[Path], dest: Path, duration: float,
              crf: int = 21, preset: str = "veryfast") -> Path:
    """Dissolve between shots instead of cutting.

    Every transition EATS its own duration: joining n segments with a d-second
    fade gives sum(lengths) - (n-1)*d, not the sum. Callers must never assume
    the total is the sum of the parts -- `build_final` measures the result
    instead, which is also what keeps subtitle timings honest."""
    segs = [Path(s) for s in segments]
    if len(segs) < 2:
        return concat(segs, dest)
    lengths = [duration_of(s) for s in segs]
    if any(l <= duration for l in lengths):
        raise AssembleError(
            f"crossfade of {duration}s is longer than a segment "
            f"({min(lengths):.2f}s) -- shorten the fade or lengthen the shot")
    cmd: List[str] = [_bin("ffmpeg"), "-y", "-v", "error"]
    for s in segs:
        cmd += ["-i", str(s)]
    steps: List[str] = []
    vlast, alast, acc = "0:v", "0:a", lengths[0]
    for i in range(1, len(segs)):
        offset = acc - duration
        vout, aout = f"v{i}", f"a{i}"
        steps.append(f"[{vlast}][{i}:v]xfade=transition=fade:"
                     f"duration={duration}:offset={offset:.4f}[{vout}]")
        steps.append(f"[{alast}][{i}:a]acrossfade=d={duration}[{aout}]")
        vlast, alast = vout, aout
        acc += lengths[i] - duration
    cmd += ["-filter_complex", ";".join(steps), "-map", f"[{vlast}]",
            "-map", f"[{alast}]", "-c:v", "libx264", "-preset", preset,
            "-crf", str(crf), "-pix_fmt", PIX_FMT, "-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart", str(dest)]
    run(cmd, f"crossfading {len(segs)} segments at {duration}s")
    return dest


def mix_music(video: Path, music: Path, dest: Path, volume: float = 0.25,
              duck: bool = True, crf: int = 21) -> Path:
    """Lay a music bed under the existing audio.

    `duration=first` keeps the result exactly as long as the video -- a bed
    longer than the cut must not extend it. Ducking uses sidechaincompress so
    the bed drops under speech; builds without that filter fall back to a flat
    mix rather than losing the music entirely."""
    exe = _bin("ffmpeg")
    can_duck = duck and has_filter("sidechaincompress", exe)
    if can_duck:
        chain = (f"[1:a]volume={volume},aloop=loop=-1:size=2e9[bed];"
                 f"[0:a]asplit=2[sc][mainmix];"
                 f"[bed][sc]sidechaincompress=threshold=0.05:ratio=8:"
                 f"attack=5:release=250[ducked];"
                 f"[mainmix][ducked]amix=inputs=2:normalize=0:duration=first"
                 f":dropout_transition=0[aout]")
    else:
        chain = (f"[1:a]volume={volume},aloop=loop=-1:size=2e9[bed];"
                 f"[0:a][bed]amix=inputs=2:normalize=0:duration=first"
                 f":dropout_transition=0[aout]")
    run([exe, "-y", "-v", "error", "-i", str(video), "-i", str(music),
         "-filter_complex", chain, "-map", "0:v", "-map", "[aout]",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest",
         "-movflags", "+faststart", str(dest)],
        f"mixing the music bed{'' if can_duck else ' (no ducking on this build)'}")
    return dest


def concat(segments: Sequence[Path], dest: Path) -> Path:
    if not segments:
        raise AssembleError("concat: nothing to join")
    listing = dest.parent / f"{dest.stem}_concat.txt"
    listing.write_text("".join(f"file '{p.as_posix()}'\n" for p in segments),
                       encoding="utf-8")
    run([_bin("ffmpeg"), "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(dest)],
        "concatenating segments")
    return dest


def burn_overlays(src: Path, dest: Path, disclaimer: Optional[Path],
                  badge: Optional[Path], badge_s: float = 3.0,
                  crf: int = 21, preset: str = "veryfast") -> Path:
    """Overlay the approved PNGs. The badge covers only the opening seconds;
    the disclaimer runs the whole length.

    Each PNG is read with `-loop 1`, which matters more than it looks. A single
    still frame overlaid onto a concatenated video tracked correctly for the
    first 34 seconds of LIPIL025 and then silently stopped at the packshot
    boundary -- so the compliance disclaimer was absent from the end card, on a
    file that had otherwise passed. Looping makes the overlay a continuous
    stream, and `shortest=1` ends the result with the video rather than never.
    """
    inputs: List[str] = ["-i", str(src)]
    steps, last, idx = [], "0:v", 1
    if disclaimer:
        inputs += ["-loop", "1", "-i", str(disclaimer)]
        steps.append(f"[{last}][{idx}:v]overlay=0:0:format=auto:shortest=1[d]")
        last, idx = "d", idx + 1
    if badge:
        inputs += ["-loop", "1", "-i", str(badge)]
        steps.append(f"[{last}][{idx}:v]overlay=0:0:format=auto:shortest=1:"
                     f"enable='lt(t,{badge_s})'[b]")
        last, idx = "b", idx + 1
    if not steps:
        shutil.copy2(src, dest)
        return dest
    run([_bin("ffmpeg"), "-y", "-v", "error"] + inputs
        + ["-filter_complex", ";".join(steps), "-map", f"[{last}]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
           "-pix_fmt", PIX_FMT, "-c:a", "copy", "-movflags", "+faststart", str(dest)],
        "burning the disclaimer overlays")
    return dest


def build_final(clips: Sequence[Path], dest: Path, size: Size,
                packshot: Optional[Path] = None,
                demo: Optional[Path] = None, demo_trim_s: Optional[float] = None,
                disclaimer: Optional[Path] = None, badge: Optional[Path] = None,
                badge_s: float = 3.0, crf: int = 21,
                preset: str = "veryfast",
                words: Optional[Sequence[Any]] = None,
                subtitle_style: Optional[Any] = None,
                fonts_dir: Optional[Path] = None,
                crossfade_s: float = 0.0,
                crossfade_into_packshot: bool = True,
                music: Optional[Path] = None,
                music_volume: float = 0.25,
                music_duck: bool = True,
                clip_audio: Optional[Sequence[Optional[str]]] = None
                ) -> Dict[str, Any]:
    """clips -> [demo] -> [packshot], subtitles, then the compliance overlays.

    The packshot goes LAST because it is what replaces the reference's own
    product shots -- the ad ends on our product, not theirs. Subtitles are burned
    BEFORE the overlays and clamped to end where the packshot begins, so the last
    line cannot draw over the end card."""
    missing = [str(c) for c in clips if not Path(c).exists()]
    if missing:
        raise AssembleError(f"assembly: missing clips: {missing}")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="fjor-assemble-"))
    try:
        segments, manifest = [], []
        for i, clip in enumerate(clips):
            track = (clip_audio or [None] * len(clips))[i] if clip_audio else None
            p = normalise(Path(clip), work / f"seg_{i:02d}.mp4", size,
                          audio=Path(track) if track else None)
            segments.append(p)
            manifest.append({"role": "clip", "source": str(clip),
                             "voiceover": Path(track).name if track else None,
                             "duration_s": round(duration_of(p), 3)})
        if demo:
            p = normalise(Path(demo), work / "seg_demo.mp4", size, mute=True,
                          trim_s=demo_trim_s)
            segments.append(p)
            manifest.append({"role": "demo", "source": str(demo),
                             "duration_s": round(duration_of(p), 3)})
        if packshot:
            p = normalise(Path(packshot), work / "seg_packshot.mp4", size)
            segments.append(p)
            manifest.append({"role": "packshot", "source": str(packshot),
                             "duration_s": round(duration_of(p), 3)})
        # Where the packshot starts: the hard right edge for subtitles. It is
        # MEASURED, never summed -- with a crossfade every transition eats its
        # own duration, so the sum of the parts is not the length of the whole.
        speech_count = sum(1 for m in manifest if m["role"] == "clip")
        speech_segments = segments[:speech_count]
        if crossfade_s and len(speech_segments) > 1:
            speech_only = crossfade(speech_segments, work / "speech.mp4",
                                    crossfade_s, crf, preset)
        else:
            speech_only = concat(speech_segments, work / "speech.mp4")
        speech_end = round(duration_of(speech_only), 3)

        if crossfade_s:
            tail = segments[speech_count:]
            if tail and crossfade_into_packshot:
                joined = crossfade([speech_only] + list(tail),
                                   work / "joined.mp4", crossfade_s, crf, preset)
            elif tail:
                joined = concat([speech_only] + list(tail), work / "joined.mp4")
            else:
                joined = speech_only
        else:
            joined = concat(segments, work / "joined.mp4")
        subtitle_count = 0
        if words is not None and subtitle_style is not None:
            from .subtitles import build_ass, burn as burn_subs
            ass_text = build_ass(words, size.tag, subtitle_style,
                                 clamp_end_s=speech_end)
            subtitle_count = ass_text.count("\nDialogue:")
            ass_path = work / "subs.ass"
            ass_path.write_text(ass_text, encoding="utf-8")
            joined = burn_subs(joined, ass_path, work / "subbed.mp4",
                               ffmpeg_with_libass(), fonts_dir, crf, preset)
        if music:
            joined = mix_music(joined, Path(music), work / "mixed.mp4",
                               music_volume, music_duck, crf)
        burn_overlays(joined, dest, disclaimer, badge, badge_s, crf, preset)
        info = probe(dest)
        vs = next((s for s in info.get("streams") or []
                   if s.get("codec_type") == "video"), {})
        return {
            "file": str(dest),
            "size": size.tag,
            "width": int(vs.get("width") or 0),
            "height": int(vs.get("height") or 0),
            "duration_s": round(float((info.get("format") or {}).get("duration") or 0), 3),
            "has_audio": any(s.get("codec_type") == "audio"
                             for s in info.get("streams") or []),
            "segments": manifest,
            "speech_end_s": speech_end,
            "subtitle_lines": subtitle_count,
            "crossfade_s": crossfade_s,
            "music": Path(music).name if music else None,
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


# -- the asset library -------------------------------------------------------

def packshot_for(assets_dir: Path, name: str, size: Size) -> Optional[Path]:
    """`<name>_916.mp4`, with an optional `<name>_45.mp4` twin. Without the twin
    the 9:16 is used and centre-cropped by `normalise`."""
    d = Path(assets_dir) / "packshots"
    suffix = "45" if size.tag == "4:5" else "916"
    for cand in (d / f"{name}_{suffix}.mp4", d / f"{name}_916.mp4"):
        if cand.exists():
            return cand
    return None


def list_packshots(assets_dir: Path) -> List[str]:
    d = Path(assets_dir) / "packshots"
    if not d.is_dir():
        return []
    names = set()
    for p in d.glob("*_916.*"):
        names.add(p.stem[:-4])
    for p in d.glob("*_45.*"):
        names.add(p.stem[:-3])
    return sorted(names)


MUSIC_EXT = (".mp3", ".m4a", ".wav", ".aac", ".ogg")


def list_music(assets_dir: Path) -> List[str]:
    d = Path(assets_dir) / "music bed"
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.iterdir()
                  if p.suffix.lower() in MUSIC_EXT and not p.name.startswith("."))


def music_for(assets_dir: Path, name: str) -> Optional[Path]:
    """By file stem. `name` may also be the full filename."""
    d = Path(assets_dir) / "music bed"
    if not d.is_dir() or not name:
        return None
    for p in sorted(d.iterdir()):
        if p.suffix.lower() in MUSIC_EXT and name in (p.stem, p.name):
            return p
    return None


def disclaimer_for(assets_dir: Path, size: Size, badge: bool = False) -> Optional[Path]:
    stem = "cwaDisclaimer" if badge else "disclaimer"
    p = Path(assets_dir) / "disclaimers" / f"{stem}{'45' if size.tag == '4:5' else '916'}.png"
    return p if p.exists() else None
