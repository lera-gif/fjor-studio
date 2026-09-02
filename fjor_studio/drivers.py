"""Motion drivers: someone else's movement, on our photograph.

A driver is a piece of video cut from a reference. The video model is given our
plate and the driver, and transfers the movement, timing and camera work onto
it. One driver can serve several shots.

Two things are decided ON THE DRIVER rather than per shot, and both for the same
reason -- they change what the clip IS, so deciding them later means rewriting
work that has already been done:

  * **The engine.** Kling Motion Control runs for exactly as long as the driver
    does and takes no duration at all; Seedance's video reference is clamped to
    4-15s like any other Seedance shot. Choosing at prompt-writing time is how a
    23-second driver quietly became a 15-second clip in their tool.
  * **The length.** For Motion Control the driver's own duration IS the shot's,
    so the plan's clamp does not apply and the forecast has to price the real
    number.

The driver's own soundtrack never reaches the final. It carries a stranger's
voice, and a stranger's voice under our script is not a defect anyone catches
in a QA verdict -- it is simply the wrong ad.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .gen.base import GenError

# Which model each engine routes to. Motion Control is Kling; the video
# reference is whatever Seedance model the project already uses, so `seedance`
# resolves at generation time rather than pinning a version here.
ENGINES: Dict[str, Optional[str]] = {
    "kling-mc-3.0": "kling-3.0/motion-control",
    "kling-mc-2.6": "kling-2.6/motion-control",
    "seedance": None,
}

VIDEO_SUFFIXES = {".mp4", ".mov"}


class DriverError(GenError):
    pass


def engine_model(engine: str, project_video_model: str) -> str:
    """The model a shot on this driver is generated with."""
    if engine not in ENGINES:
        raise DriverError(
            f"'{engine}' is not a motion engine (have: {', '.join(sorted(ENGINES))})")
    return ENGINES[engine] or project_video_model


def is_motion_control(engine: str) -> bool:
    return str(engine or "").startswith("kling-mc")


def measure(path: Path) -> float:
    from .assemble import duration_of
    try:
        return round(float(duration_of(Path(path))), 3)
    except Exception as exc:  # noqa: BLE001
        raise DriverError(f"could not measure the driver {Path(path).name}: {exc}")


def add(job, job_dir: Path, source: Path, engine: str = "seedance",
        note: str = "") -> Dict[str, Any]:
    """Copy a driver into the job and register it.

    Copied rather than referenced: a job has to stay re-runnable after whatever
    it was cut from has moved, and a driver on someone's Desktop is not part of
    the job the way `ref/` is."""
    source = Path(source)
    if not source.is_file():
        raise DriverError(f"no driver video at {source}")
    if source.suffix.lower() not in VIDEO_SUFFIXES:
        raise DriverError(
            f"a driver must be mp4 or mov, not '{source.suffix}' -- Motion "
            f"Control refuses anything else")
    if engine not in ENGINES:
        raise DriverError(
            f"'{engine}' is not a motion engine (have: {', '.join(sorted(ENGINES))})")

    dest_dir = Path(job_dir) / "drivers"
    dest_dir.mkdir(parents=True, exist_ok=True)
    driver_id = f"d{len(job.meta.get('drivers') or []) + 1}"
    dest = dest_dir / f"{driver_id}{source.suffix.lower()}"
    shutil.copy2(source, dest)

    entry = {"id": driver_id, "file": f"drivers/{dest.name}", "engine": engine,
             "duration_s": measure(dest), "note": note.strip(),
             "source": source.name}
    job.meta.setdefault("drivers", []).append(entry)
    return entry


def all_of(job) -> List[Dict[str, Any]]:
    return list(job.meta.get("drivers") or [])


def find(job, driver_id: str) -> Dict[str, Any]:
    for d in all_of(job):
        if d["id"] == driver_id:
            return d
    known = ", ".join(d["id"] for d in all_of(job)) or "none"
    raise DriverError(f"no driver '{driver_id}' on this job (have: {known})")


def for_scene(job, scene) -> Optional[Dict[str, Any]]:
    """The driver a shot is animated from, or None for an ordinary shot."""
    driver_id = getattr(scene, "driver", None) or (
        scene.get("driver") if isinstance(scene, dict) else None)
    return find(job, driver_id) if driver_id else None


def first_frame(job_dir: Path, driver: Dict[str, Any], dest: Path) -> Path:
    """The driver's opening frame, which is what the plate has to match.

    Not a nicety: the body has to start from the same pose, angle, crop and
    SUPPORTING SURFACE. A person who starts from a different surface -- a mat
    where the driver had a bed, a floor where it had a chair -- animates wrongly,
    and the shot is bought before anyone sees it."""
    import subprocess
    from .assemble import _bin
    src = Path(job_dir) / driver["file"]
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [_bin("ffmpeg"), "-y", "-v", "error", "-i", str(src),
         "-frames:v", "1", "-q:v", "2", str(dest)],
        capture_output=True, text=True)
    if proc.returncode != 0 or not dest.exists():
        raise DriverError(
            f"could not read the first frame of {driver['file']}: "
            f"{proc.stderr[-200:]}")
    return dest


# ---------------------------------------------------------------------------
# What the writer is told when a shot rides a driver.
#
# Ported from their r190-r234 rules, which are the distilled result of getting
# it wrong: the two assets already carry almost everything a prompt normally
# spells out, so spelling it out again does not reinforce it -- it COMPETES with
# it, and when a word disagrees with a pixel the shot comes out wrong.

WRITER_RULES = """
MOTION DRIVERS — some shots in this plan are animated from a reference video.

A driver is a slice of someone else's creative. Its MOTION, TIMING and CAMERA
are transferred onto our still photo by the video model. The shots that ride one
are named above; treat every other shot exactly as you always would.

1. NEVER DESCRIBE THE MOTION of a driven shot. The movement, the beat pattern,
   the camera move and the lip movement all come from the reference video. No
   action choreography, no timing beats, no camera line, no shot-size sentence.
2. A DRIVEN SHOT'S `video_prompt` IS SHORT — 300-600 characters is CORRECT AND
   COMPLETE, not thin. Never expand it to hit a length. It contains only:
     - ONE short identity line that POINTS AT THE PHOTO: who is in frame, and
       that the look and the location are the photo's. For example, "A woman
       55+, the person of the reference photo, in the room of the reference
       photo." No face description, no wardrobe, no hair, no location, no
       lighting, no lens.
     - THE DIALOGUE IN FULL, exactly as the format requires. Speech is the one
       thing neither asset carries, so it is never shortened or paraphrased.
     - ONE short ambient-audio line.
     - The negative prompt, where the TEXT block is mandatory: a driver very
       often carries burnt-in captions, and this is what keeps them out.
3. THE `image_prompt` OF A DRIVEN SHOT IS NOT SHORTENED. It keeps its full
   length and its full identity: that block is where our person and our room are
   actually created, and the video model then reads them off the photo.
4. THIS IS PER-SHOT. A shot without a driver is written exactly as always, at
   full length. Mixed plans are normal and expected.
5. ZERO TEXT IN FRAME for a driven shot: no headlines, captions, subtitles,
   labels, numbers, counters, prices, timers or logos.
"""

# Kling Motion Control refuses to be given a duration and gives us no say over
# its soundtrack, so the writer must not spend either.
KLING_RULES = """
6. Shots on a Kling Motion Control driver: write NO speech for them at all, and
   do not choose a duration — the clip runs exactly as long as the driver, and
   the length is already set for you. A shot on a Seedance driver may speak, and
   is 4-15s like any other.
"""


def start_frame_rule(driver: Dict[str, Any]) -> str:
    """What the PLATE of a driven shot has to be.

    Their hardest-won rule, and the one that decides whether the shot works: the
    video model re-poses our photograph into the driver's motion, so a
    mismatched crop or pose is the commonest way a driven shot comes out wrong.
    Kling states it outright -- never drive a half-body character with full-body
    motion."""
    return f"""
THIS PHOTO IS A STARTING FRAME, NOT A MODEL SHOT.

It is the opening frame of a shot that will be animated from a reference video
({driver['duration_s']}s). The first frame of that video is supplied alongside
this prompt as a GEOMETRY TEMPLATE. Do not fight it — describe the same opening
geometry it shows:

  - our person ALREADY IN THE OPENING POSE of that video
  - the same camera angle, the same shot size (full body / half body /
    close-up), the same position and scale of the person within the frame
  - arms and hands where the template has them, the same body orientation
  - the same KIND of contact surface under the body (mat / rug / towel / bed /
    chair / floor / ground) that the template opens on. A body that starts from
    a different surface animates wrongly.

Everything else is OURS and comes from the brief, never from the template:
face, age, body type, hair, wardrobe, location, lighting. THE ROOM IS REBUILT,
NEVER COPIED — different walls, different furniture and layout, different decor.
THE PERSON IS A DIFFERENT INDIVIDUAL of the same type: same role, different
actor. This holds even when nobody asked for a casting change.

Never write "the same room as in the reference" or "the same mat": there is no
reference room in our shot. No text of any kind in the frame.
"""


def writer_block(job) -> str:
    """The rules to append to the prompt brief, or nothing when no driver."""
    attached = [d for d in all_of(job)]
    if not attached:
        return ""
    lines = [f"  - shot(s) on driver {d['id']}: {d['duration_s']}s, engine "
             f"{d['engine']}" + (f" — {d['note']}" if d.get("note") else "")
             for d in attached]
    block = WRITER_RULES + "\n" + "\n".join(lines) + "\n"
    if any(is_motion_control(d["engine"]) for d in attached):
        block += KLING_RULES
    return block

