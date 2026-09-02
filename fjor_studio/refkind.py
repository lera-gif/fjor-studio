"""What KIND of reference this is, and what that changes.

Their tool asks twice at intake, and the two questions are different:

    source      Видео-реф / Баннер / Универсальный   -- what the source IS
    тип рефа    UGC с людьми / Точная копия кадра    -- how to treat a video one

Ours infers the source from the file (a video is a reference, an image is a
banner -- `stages/banner_steps.is_banner`), and asks the second question here.
Their third source, `universal` (a written brief with an optional video AND an
optional banner), is a pipeline we do not have and is deliberately not offered:
a control that changes nothing is worse than no control.

WHY THIS EXISTS. AW024 (2026-09-01) was a 3D cartoon reference in the Pixar
manner, the analysis said so, and every image prompt began "3D cartoon animation
style" -- and the creative still came back photoreal and uncanny. The words were
right and the words were not enough. So `replica` does not merely say different
words: it cuts STILLS out of the reference and hands them to the image model,
which is the same reason a face is anchored with a portrait rather than a
description (BLUEPRINT 3.4c). A picture is the only thing that has ever pinned a
look here.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from .gen.base import GenError

# Their two values, with their meanings. `ugc` is the default and is what every
# job before this shipped as.
KINDS: Dict[str, str] = {
    "ugc": "people talking to camera; we re-create the idea, not the frame",
    "replica": "reproduce the reference's own look: material, composition, "
               "palette and finish, one to one",
}

# How many stills to cut. Two is the cap on identity anchors for the same reason
# -- beyond that the references compete and the result drifts to an average --
# and style frames share the model's attention with them.
STYLE_FRAMES = 3


def normalise(value: Any, default: str = "ugc") -> str:
    kind = str(value or default).strip().lower()
    if kind not in KINDS:
        raise GenError(
            f"reference kind '{kind}' is not one of {', '.join(sorted(KINDS))}")
    return kind


def is_replica(job) -> bool:
    return normalise((getattr(job, "intake", None) or {}).get("ref_kind")
                     or "ugc") == "replica"


def cut_style_frames(reference: Path, dest_dir: Path, duration_s: float,
                     count: int = STYLE_FRAMES) -> List[str]:
    """Stills from the reference, spread across it.

    Spread rather than sampled from the opening: an ad's first second is often a
    title card or a hard cut, and a style anchor taken from one would teach the
    model the wrong thing. Taken at even fractions, and never at 0."""
    reference, dest_dir = Path(reference), Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    if duration_s <= 0:
        raise GenError("cannot cut style frames from a reference of no length")
    out: List[str] = []
    for i in range(count):
        at = duration_s * (i + 1) / (count + 1)
        dest = dest_dir / f"style_{i:02d}.png"
        proc = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.3f}",
             "-i", str(reference), "-frames:v", "1", "-q:v", "2", str(dest)],
            capture_output=True, text=True)
        if proc.returncode != 0 or not dest.exists():
            raise GenError(
                f"could not cut a style frame at {at:.1f}s: {proc.stderr[-200:]}")
        out.append(str(dest))
    return out


# What the writer is told, and what the image model is told, when the producer
# asked for the reference's own look.
WRITER_RULES = """
MATCH THE REFERENCE'S OWN LOOK — the producer asked for a replica, not a UGC
re-creation.

The reference is not a source of ideas here; it is the thing being reproduced.
Every prompt you write describes the SAME KIND OF PICTURE the reference is:

1. NAME THE MATERIAL in every image prompt, first, before anything else: is this
   photographic footage, a 3D animated render, a hand-drawn illustration, a
   screen recording, a medical diagram? Say which, and say its FINISH -- a
   stylised 3D cartoon in the Pixar manner is not the same picture as a
   photoreal 3D render, and a model given only "3D" will produce the second.
2. GEOMETRY IS COPIED, not invented: the same shot sizes, the same camera
   heights, the same crops, the same framing of a subject within the frame.
3. WHAT IS NOT IN THE FRAME matters as much as what is. If the reference has no
   people, ours has no people; if it has no text, ours has no text. "There are
   no people in this reference" is a correct and complete answer, and inventing
   some is the commonest way a replica stops being one.
4. Stills cut from the reference are attached to every plate. They outrank your
   words about the look -- so do not fight them, and do not describe a different
   picture from the one they show.
"""

STYLE_ANCHOR = """STYLE ANCHOR — THIS OUTRANKS THE DESCRIPTION BELOW.

The attached reference frame{plural} {verb} cut from the reference itself. They
are what this creative must LOOK LIKE. Match them:

  - the MATERIAL: photograph, 3D render, illustration, screen capture
  - the FINISH: how stylised or photoreal, how soft or sharp, how much texture
  - the palette, the contrast, the light
  - the rendering of people: proportion, stylisation, skin, eyes, hair
  - shot size, camera height and crop

Where the description below disagrees with these frames about HOW THIS LOOKS,
THE FRAMES WIN. The description governs what happens and who is in it, never the
medium it is drawn in.

AW024 was a stylised 3D cartoon; its prompts said "3D cartoon animation style"
and it came back photoreal and uncanny anyway. Words did not carry the look.

"""


def anchor_block(count: int) -> str:
    if not count:
        return ""
    return STYLE_ANCHOR.format(plural="s" if count > 1 else "",
                               verb="were" if count > 1 else "was")
