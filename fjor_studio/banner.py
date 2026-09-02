"""Banner mode: a finished client banner, brought to life.

A different creative altogether from the UGC pipeline, and their v4 treats it as
one -- the mode has its own compact brain, with the video instruction, the
niche, the voice and the reference analysis all deliberately kept out of it.

    a client banner (1:1, 4:5 or already 9:16)
      -> expanded to vertical 9:16, WITHOUT touching the banner itself
      -> animated with micro-motion, everything printed on it pixel-locked
      -> assembled into finals in both sizes, with the usual overlays

The expansion is the whole difficulty. Everything printed on a banner -- the
offer, the button, the logo, the legal line -- is a thing a client approved, and
an expansion that redraws a letter, shifts a button or shades a colour has
destroyed the asset it was given. So the expansion never invents inside the
banner: it only fills what was never there.

Three engines exist in their tool. This is the CANVAS one, which is the most
deterministic of the three and the one we can verify: the canvas is built HERE,
in ffmpeg, with the banner composited at its true size and the margins filled
with a flat marker colour. The model is then asked to replace the marker and
nothing else, and afterwards we can check pixel-for-pixel that the banner
survived -- which is not possible when the model is handed a bare image and
asked to be careful.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .assemble import AssembleError, _bin, probe

# The colour the margins are filled with. Chosen the way a key colour is chosen:
# far from anything a fitness banner contains, and flat.
MARKER = "0xFF00B1"

# What the finished frame is. Their expansion always lands on 9:16 and the 4:5
# is cropped from it, so this is the one shape the expansion has to produce.
CANVAS = (1080, 1920)


class BannerError(AssembleError):
    pass


def measure(banner: Path) -> Tuple[int, int]:
    banner = Path(banner)
    if not banner.is_file():
        raise BannerError(f"no banner at {banner}")
    try:
        stream = [s for s in probe(banner)["streams"] if s.get("width")][0]
        return int(stream["width"]), int(stream["height"])
    except Exception as exc:  # noqa: BLE001
        raise BannerError(f"could not read {banner.name} as an image: {exc}")


def placement(banner_w: int, banner_h: int,
              canvas: Tuple[int, int] = CANVAS) -> Dict[str, int]:
    """Where the banner sits on the canvas, and how much margin is left.

    Scaled to the canvas WIDTH and never cropped: the banner is the asset, and
    cutting it to fit would lose the thing we were given. A banner already
    taller than 9:16 is scaled to fit the height instead, and then there is
    nothing to expand."""
    cw, ch = canvas
    scale = cw / banner_w
    if banner_h * scale > ch:
        scale = ch / banner_h
    w, h = int(round(banner_w * scale)), int(round(banner_h * scale))
    return {"w": w, "h": h, "x": (cw - w) // 2, "y": (ch - h) // 2,
            "top": (ch - h) // 2, "bottom": ch - h - (ch - h) // 2,
            "canvas_w": cw, "canvas_h": ch}


def build_canvas(banner: Path, dest: Path,
                 canvas: Tuple[int, int] = CANVAS) -> Dict[str, Any]:
    """The banner at its true size on a marker-filled 9:16 frame.

    This is what the model is asked to complete. Building it ourselves rather
    than describing it means the banner's own pixels are still the banner's own
    pixels when the model gets there, and that the margins are unmistakable."""
    banner, dest = Path(banner), Path(dest)
    bw, bh = measure(banner)
    p = placement(bw, bh, canvas)
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [_bin("ffmpeg"), "-y", "-v", "error",
         "-f", "lavfi", "-i",
         f"color=c={MARKER}:size={p['canvas_w']}x{p['canvas_h']}",
         "-i", str(banner),
         "-filter_complex",
         # flags=lanczos: the banner is text and edges, and a soft rescale of
         # type is the first thing the letter-for-letter check would catch
         f"[1:v]scale={p['w']}:{p['h']}:flags=lanczos[b];"
         f"[0:v][b]overlay={p['x']}:{p['y']}",
         "-frames:v", "1", str(dest)],
        capture_output=True, text=True)
    if proc.returncode != 0 or not dest.exists():
        raise BannerError(f"could not build the canvas: {proc.stderr[-200:]}")
    return dict(p, file=str(dest), banner=str(banner),
                marker=MARKER, needs_expansion=bool(p["top"] or p["bottom"]))


# What counts as a changed pixel, and how many of them mean the banner was
# edited. Measured on a real 1080x1080 banner against three edits their QA calls
# critical: recolouring the headline, nudging the button 6px, deleting the legal
# line. An honest expansion differed by at most 8 anywhere; every edit put
# thousands of pixels past 24.
BANNER_PIXEL_TOLERANCE = 24
BANNER_CHANGED_FRACTION = 0.0002        # 0.02%, ~233px on a 1080x1080 banner

# --- and the DIFFERENT question asked of the model's raw return -------------
#
# An image model answers with its own resolution bucket, not ours: AW025 asked
# for 1080x1920 and got 768x1376 twice, identically, whatever the prompt said.
# Nothing pixel-exact can be asked of a frame that has been rescaled -- and
# nothing needs to be, because `recomposite` puts our own banner back. What is
# left to ask is coarser and more important: IS THIS THE SAME PICTURE, or did
# the model redraw the scene?
#
# That is a low-frequency question, so it is asked at low frequency. Rescaling
# damage lives in the high frequencies (type edges); a re-rendered sky does not.
# MEASURED on AW025 and on a hard-edged synthetic banner, at 32x32:
#
#     honest expansion, photographic     mean 1.76
#     honest expansion, hard type        mean 1.08
#     real attempt 2 (re-rendered)       mean 15.66
#     real attempt 1 (re-rendered)       mean 42.42
#     a different picture entirely       mean 65.88
#
# 8 sits in that gap with room on both sides.
SAME_PICTURE_GRID = 32
SAME_PICTURE_MEAN = 8.0
ASPECT_TOLERANCE = 0.03


def same_picture(original: Path, expanded: Path, place: Dict[str, int],
                 limit: float = SAME_PICTURE_MEAN,
                 grid: int = SAME_PICTURE_GRID) -> Dict[str, Any]:
    """Did the model EDIT our canvas, or draw its own picture?

    Asked of the raw return, before anything is re-composited, because a model
    that redrew the scene also painted MARGINS belonging to that other scene --
    and those margins are the only thing we keep. A re-render is not repaired by
    putting our banner back over it; it is a seam waiting to happen.

    The mean is the right statistic HERE, and it was the wrong one for
    `banner_survived`, which is not a contradiction: there the question was
    "did any local thing change", which a mean dilutes; here it is "is this the
    same picture", which is exactly what a mean answers. `worst` is reported but
    not gated on -- a model that painted inside the banner is worth knowing
    about, and is also about to be overwritten."""
    original, expanded = Path(original), Path(expanded)
    cw = int(place.get("canvas_w", CANVAS[0]))
    ch = int(place.get("canvas_h", CANVAS[1]))
    got = measure(expanded)
    if abs(got[0] / got[1] - cw / ch) > ASPECT_TOLERANCE:
        raise BannerError(
            f"the expansion came back {got[0]}x{got[1]}, which is not the shape "
            f"of a {cw}x{ch} canvas -- the banner's rectangle is not anywhere in "
            f"particular, so nothing about it can be answered")
    out = subprocess.run(
        [_bin("ffmpeg"), "-v", "error",
         "-i", str(expanded), "-i", str(original),
         "-filter_complex",
         f"[0:v]scale={cw}:{ch}:flags=lanczos,"
         f"crop={place['w']}:{place['h']}:{place['x']}:{place['y']},"
         f"scale={grid}:{grid}:flags=area,format=rgb24[a];"
         f"[1:v]scale={grid}:{grid}:flags=area,format=rgb24[b];"
         f"[a][b]blend=all_mode=difference,format=gray",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True)
    if out.returncode != 0 or not out.stdout:
        raise BannerError(
            f"could not compare the pictures: {out.stderr.decode()[-200:]}")
    px = out.stdout
    mean = round(sum(px) / len(px), 2)
    return {"mean_difference": mean, "worst_cell": max(px), "limit": limit,
            "returned": list(got), "same": mean <= limit}


def banner_survived(original: Path, expanded: Path, place: Dict[str, int],
                    threshold: int = BANNER_PIXEL_TOLERANCE,
                    fraction: float = BANNER_CHANGED_FRACTION,
                    licensed: Optional[Tuple[float, float]] = None) -> Dict[str, Any]:
    """Did the expansion leave the banner alone?

    The question this whole mode turns on. Everything printed on a banner was
    approved by a client, so a redrawn letter, a shifted button or a shaded
    colour is not a blemish -- it is the asset destroyed. We can ask precisely,
    because we put the banner there ourselves: crop its own rectangle out of the
    result and compare with what went in.

    COUNTED, not averaged. The mean was the first thing tried and it is the
    wrong statistic: a local edit is diluted across a million pixels, and all
    three of the edits above sailed under a mean tolerance that codec noise
    already reached. A check that looks at the wrong number is as blind as one
    that cannot look at all."""
    original, expanded = Path(original), Path(expanded)
    place = dict(place)
    # A frame that is not the canvas cannot be compared at all: the banner is at
    # a known rectangle of a known canvas, and cropping that rectangle out of
    # something else answers a different question. Say so rather than guess.
    got = measure(expanded)
    want = (int(place.get("canvas_w", CANVAS[0])),
            int(place.get("canvas_h", CANVAS[1])))
    if got != want:
        raise BannerError(
            f"the frame is {got[0]}x{got[1]}, not {want[0]}x{want[1]} -- this "
            f"check reads the banner's own rectangle of a finished canvas, so "
            f"it is asked AFTER `recomposite`, never of a model's raw return")
    out = subprocess.run(
        [_bin("ffmpeg"), "-v", "error",
         "-i", str(expanded), "-i", str(original),
         "-filter_complex",
         f"[0:v]crop={place['w']}:{place['h']}:{place['x']}:{place['y']},"
         f"format=rgb24[a];"
         f"[1:v]scale={place['w']}:{place['h']}:flags=lanczos,format=rgb24[b];"
         f"[a][b]blend=all_mode=difference,format=gray",
         "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True)
    if out.returncode != 0 or not out.stdout:
        raise BannerError(
            f"could not compare the banner: {out.stderr.decode()[-200:]}")
    pixels = out.stdout
    w, h = int(place["w"]), int(place["h"])
    guarded, band = pixels, b""
    if licensed:
        # A LICENSED BAND: one horizontal strip of the banner the producer has
        # allowed to change -- in practice the legal fine print, which always
        # goes. Everything outside it is still held to zero, so licensing the
        # small print does not quietly license the headline above it.
        y0, y1 = sorted(float(v) for v in licensed)
        lo = max(0, min(h, int(round(y0 * h))))
        hi = max(0, min(h, int(round(y1 * h))))
        if hi > lo:
            band = pixels[lo * w:hi * w]
            guarded = pixels[:lo * w] + pixels[hi * w:]
    changed = sum(1 for p in guarded if p > threshold)
    allowed = max(16, int(len(guarded) * fraction))
    verdict = {"changed_pixels": changed, "allowed": allowed,
               "share": round(changed / max(1, len(guarded)) * 100, 4),
               "worst_pixel": max(pixels),
               "mean_difference": round(sum(pixels) / len(pixels), 3),
               "intact": changed <= allowed}
    if band:
        # A pass that was allowed to edit and edited nothing did not run. That
        # reads as a clean result to every other check here, which is exactly
        # how a silently skipped step survives to delivery.
        in_band = sum(1 for p in band if p > threshold)
        verdict.update({"licensed_band": [round(y0, 4), round(y1, 4)],
                        "changed_in_band": in_band,
                        "edit_applied": in_band > max(16, int(len(band) * fraction))})
    return verdict


# ---------------------------------------------------------------------------
# The expansion prompt playbook (their r174, adapted to the canvas engine).
#
# Their playbook was written for the OTHER engine -- the one that hands a model
# the bare banner and asks it to uncrop. Half of it exists to stop that model
# re-laying-out the design: PRESERVE, LAYOUT LOCK, "the original sits exactly in
# the vertical centre, both new areas ~420px". We do not need to ask for any of
# that, because we did it ourselves in ffmpeg -- the geometry is settled before
# the model is called, and `banner_survived` checks it afterwards.
#
# What does NOT come free with the canvas is everything the analysis carries:
# what the background actually IS above and below (they differ nearly always),
# what is cut by an edge and has to be finished, what must be left cropped. No
# amount of compositing knows that. So the division of labour here is:
#
#     the writer ANSWERS THE FOUR QUESTIONS
#     this module BUILDS THE PROMPT
#
# which is a change from their tool, where the writer wrote the prompt in prose
# and the tool then searched it for unfilled [brackets] and shouted. A prompt
# assembled from answers cannot have an unfilled bracket.

# The instruction the canvas is sent with. SHORT, FIXED, and describing no
# content at all -- and that is the whole point, learned the expensive way on
# AW025 (2026-09-01). The four analysis questions below belong to the OTHER
# engine, the one handed a bare image with no marker to aim at. Sent with a
# canvas they became 2,361 characters of scene description, and an editing model
# handed a description of a scene draws the scene: both attempts came back with
# the banner's dusk photograph replaced, one by an orange sunset and one by an
# afternoon sky. The canvas already SHOWS the model everything the description
# was trying to say.
CANVAS_FILL_PROMPT = (
    "This image is a {cw}x{ch} vertical canvas. A finished advertising banner "
    "is placed in the middle, and the areas above and below it are filled with "
    "a solid magenta placeholder. Replace ONLY the solid magenta areas with a "
    "seamless natural continuation of the banner's own background and scenery, "
    "matching its exact colours, texture, lighting and sharpness, and finishing "
    "any person or object cut off at the banner's top or bottom edge. The join "
    "must be invisible: no seam, no band, no blur. Do NOT change a single pixel "
    "outside the magenta areas -- same photograph, same text, same fonts, same "
    "logo, same colours, same layout. No new text anywhere. Output one single "
    "vertical image.")


def fill_prompt(canvas: Tuple[int, int] = CANVAS) -> str:
    return CANVAS_FILL_PROMPT.format(cw=canvas[0], ch=canvas[1])


ANALYSIS_QUESTIONS = """
BANNER EXPANSION — study the attached banner and answer FOUR questions. You are
not writing the prompt; you are answering these, and the prompt is built from
your answers. Answer in English, concretely, about THIS banner.

Q1. WHAT CONTINUES PAST THE TOP EDGE, AND PAST THE BOTTOM EDGE? Answer the two
    SEPARATELY -- they are almost always different content. Say what the
    MATERIAL or the SCENE is, never what colour it is (see the iron rule below):
      plain backdrop  -> "the plain studio backdrop simply keeps going"
      photo texture   -> "the tabletop surface continues: same texture detail,
                          same grain, same depth of field, same light direction"
      photo scene     -> "more of the sky above / more of the floor below, in
                          the same perspective and the same light"
      illustration    -> "the same hand-drawn style continues: same line weight,
                          same limited palette, same paper texture"
      a frame or card -> extend the OUTER margin ONLY, so the content card stays
                          its original size
      a collage       -> "do not stretch or extend the photo panels themselves;
                          only the editorial background above and below extends,
                          the panels stay their original size"

Q2. WHAT IS CUT OFF BY THE TOP OR BOTTOM EDGE? Name each one and say what
    happens to it:
      a person        -> FINISH them: "her shoulders are cut by the bottom edge
                          -- continue the body naturally downward, same clothing,
                          same skin tone, same photographic treatment, plausible
                          and modest"
      a central object-> complete its whole silhouette, then continue behind it
      a small decorative thing that stylishly exits the frame (a spoon handle, a
      branch, a ribbon end) -> DO NOT finish it. Say so, by name.
      nothing cut     -> say "nothing is cut off" -- it becomes a safety line.

Q3. WHAT IS PRINTED ON THE BANNER? List the headline, any subline, the button
    label and the brand by name, IN QUOTES, exactly as printed. This is not
    decoration: a model redraws a thing less when it has been named.

Q4. DECOR IN THE NEW AREAS. A dense banner (much text, many objects) -> keep the
    new areas clean and empty. A minimal one whose style has small details
    (crumbs, drips, doodles) -> at most 1-2 more of the same, sparse, near the
    edges, never over the text. Say which, and name the details if any.

IRON RULE, ABOVE ALL OTHERS: NEVER NAME A COLOUR. Not "white", not "warm beige",
not "light grey" -- no colour word anywhere in your answers. This is not style
advice. A named colour makes the model paint that shade instead of continuing
the real edge pixels, and the result is a band across the frame where the
extension begins. Name the MATERIAL ("studio backdrop", "tabletop"), and let the
pixels supply their own colour. The one exception is quoted printed text in Q3:
a headline reading "Black Friday" is quoted, and quotes are exempt.
"""

# Every block of the assembled prompt, in the order the model reads them.
_FILL = ("This image is a {cw}x{ch} vertical canvas. The finished ad banner is "
         "already placed in the middle at its true size; the areas above and "
         "below it are filled with a solid magenta marker ({marker}). Replace "
         "ONLY the marker areas with a seamless natural continuation of the "
         "banner's own background and scenery.")

_PRESERVE = ("PRESERVE: do not change a single pixel outside the marker areas. "
             "{names} stay exactly as they are, at the same size, in the same "
             "place, in the same typeface, perfectly legible. Do not redraw, "
             "restyle, re-typeset, re-space or move anything inside the banner.")

_EXTEND = ("EXTEND, above and below separately:\n"
           "  above -- {above}\n"
           "  below -- {below}")

_SEAMLESS = ("SEAMLESS CONTINUATION: the new areas are a direct physical "
             "continuation of the banner, as if the photograph had always been "
             "taller. Every new pixel row begins exactly where the adjacent "
             "original pixels end. No shift of colour, brightness or "
             "temperature, no tint, no seam, no border of any kind. It must be "
             "impossible to tell where the banner ends and the extension begins.")

_DO_NOT = ("DO NOT: no new text, numbers, logos or watermarks anywhere. Do not "
           "duplicate {names}. No blurred, stretched, mirrored or letterbox "
           "bands -- a blurred band instead of real painted continuation is the "
           "single commonest way this goes wrong. No borders, frames, vignettes "
           "or heavy edge shadows. No magenta left anywhere in the output.")

_OUTPUT = "Output: one single vertical {cw}x{ch} image."

# The tiers. Their finding, and it survives the change of engine: a simple
# banner gets a WORSE result from the long prompt, because every extra sentence
# is another thing for the model to act on. The short tier is not a shortcut --
# it is the correct prompt for a flat background with nothing cut.
TIERS = ("short", "full")


def _quoted(names) -> str:
    """The printed things, listed by name in quotes, as English."""
    items = [f'"{str(n).strip()}"' for n in (names or []) if str(n).strip()]
    if not items:
        return "all text, buttons and logos"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def expansion_prompt(analysis: Dict[str, Any],
                     canvas: Tuple[int, int] = CANVAS,
                     marker: str = MARKER) -> str:
    """The fill instruction, assembled from the four answers.

    `analysis` carries `above`, `below` (Q1), `cut_off` and `leave_cropped`
    (Q2), `preserve` (Q3), `decor` (Q4), an optional `tier`, and the producer's
    `edits` where the brief asked for one.

    Tier defaults to FULL, which is their rule for an unsure writer and the
    right default here too: the extra blocks cost nothing but tokens, and the
    banner they protect cost a client's approval."""
    a = dict(analysis or {})
    tier = str(a.get("tier") or "full").lower()
    if tier not in TIERS:
        raise BannerError(f"tier must be one of {TIERS}, not '{tier}'")
    above, below = str(a.get("above") or "").strip(), str(a.get("below") or "").strip()
    if not above or not below:
        raise BannerError(
            "Q1 is unanswered: the top and the bottom must be described "
            "SEPARATELY -- they are almost always different content")
    cw, ch = canvas
    names = _quoted(a.get("preserve"))

    parts = [_FILL.format(cw=cw, ch=ch, marker=marker)]
    if tier == "full":
        parts.append(_PRESERVE.format(names=names))
    parts.append(_EXTEND.format(above=above, below=below))

    cut = str(a.get("cut_off") or "").strip()
    if cut and not _says_nothing_is_cut(cut):
        parts.append(
            f"FINISH WHAT THE EDGE CUT: {cut} Paint its real, sharp, complete "
            f"continuation in the same style, lighting and treatment.")
    else:
        # Their safety line. Without it a model invents a reason to extend an
        # object that was never cut, and duplicates it into the margin.
        parts.append(
            "Every object is fully inside the banner -- do not extend, complete "
            "or duplicate any of them; only the background continues.")

    leave = str(a.get("leave_cropped") or "").strip()
    if leave:
        parts.append(f"LEAVE CROPPED: {leave} It exits the frame on purpose; "
                     f"do not complete it.")

    decor = str(a.get("decor") or "").strip()
    if decor:
        parts.append(f"IN THE NEW AREAS: {decor}")

    parts.append(_SEAMLESS)
    if tier == "full":
        parts.append(_DO_NOT.format(names=names))
    else:
        parts.append("No new text or logos, no duplicates, no blurred or "
                     "mirrored bands, no frames. No magenta left anywhere.")

    edits = str(a.get("edits") or "").strip()
    if edits:
        # One sentence, and ONLY these: a brief edit is the one licensed change
        # inside the banner, and an open-ended invitation to edit is how the
        # rest of it gets rewritten too.
        parts.append(f"Also apply ONLY these edits, changing nothing else: {edits}")

    parts.append(_OUTPUT.format(cw=cw, ch=ch))
    return "\n\n".join(parts)


def _says_nothing_is_cut(answer: str) -> bool:
    low = answer.lower()
    return any(p in low for p in ("nothing is cut", "nothing cut", "none",
                                  "nothing is cropped"))


# ---------------------------------------------------------------------------
# Checking the prompt before it is paid for.
#
# Their tool watched for two things and shouted a toast: unfilled {slots} and a
# prompt longer than the full tier. Both are worth keeping. But their own FIRST
# iron rule -- never name a colour -- was left to the writer's discipline, and it
# is the one that actually costs money: a named shade produces a seam band, the
# QA calls it critical, and the banner is regenerated. It is also perfectly
# mechanical to check. So we check it.
#
# Quoted text is exempt, and that exemption is the whole reason this is safe to
# enforce: a headline reading "Black Friday" or a button reading "Go Green" is
# printed on the banner, is quoted in Q3, and must be named exactly.

COLOUR_WORDS = frozenset("""
white off-white black grey gray charcoal silver beige cream ivory tan taupe
brown chocolate red crimson scarlet burgundy maroon pink rose fuchsia purple
violet lavender lilac indigo blue navy teal turquoise cyan aqua green olive
mint lime yellow amber gold golden orange peach coral apricot bronze copper
khaki sand pastel monochrome sepia
""".split())

# The one colour we DO name. It is the thing being removed, not the thing being
# continued -- the seam comes from naming the colour the model should have read
# off the edge pixels, and the marker is never read off anything.
ALLOWED_COLOUR_WORDS = frozenset({"magenta"})

# Measured against the full tier assembled from a real analysis. Longer than
# this and the writer has started explaining rather than answering.
MAX_PROMPT_CHARS = 2600

_QUOTED = re.compile(r'"[^"]*"|«[^»]*»|“[^”]*”')
_PLACEHOLDER = re.compile(r"\[[^\]\n]{2,60}\]|\{[^}\n]{2,60}\}")


def colour_words_in(text: str) -> List[str]:
    """Colour words outside quotes, in the order they appear, deduplicated."""
    bare = _QUOTED.sub(" ", str(text or "")).lower()
    seen, found = set(), []
    for word in re.findall(r"[a-z][a-z-]*", bare):
        for part in word.split("-"):
            if (part in COLOUR_WORDS and part not in ALLOWED_COLOUR_WORDS
                    and part not in seen):
                seen.add(part)
                found.append(part)
    return found


def check_prompt(text: str, expects_marker: bool = True) -> Dict[str, Any]:
    """Is this prompt safe to send? Complaints in the order they matter.

    `expects_marker` is on for the expansion, which is a fill instruction and
    is meaningless without naming what to fill. The later passes over an already
    expanded frame have no marker left to name."""
    text = str(text or "")
    problems = []
    colours = colour_words_in(text)
    if colours:
        problems.append(
            f"names a colour outside quotes ({', '.join(colours)}) -- a named "
            f"shade is painted instead of the real edge pixels, and the result "
            f"is a seam band. Name the material instead.")
    left = _PLACEHOLDER.findall(text)
    if left:
        problems.append(
            f"has unfilled placeholders ({', '.join(left[:3])}) -- they reach "
            f"the model as literal text")
    if len(text) > MAX_PROMPT_CHARS:
        problems.append(
            f"is {len(text)} characters, past the {MAX_PROMPT_CHARS} the full "
            f"tier needs -- the writer has started explaining")
    if expects_marker and "magenta" not in text.lower() \
            and MARKER.lower() not in text.lower():
        problems.append(
            "never mentions the marker -- on a canvas the model has to be told "
            "what to replace, or it redraws the whole frame")
    return {"ok": not problems, "problems": problems,
            "colours": colours, "length": len(text)}


def recomposite(banner: Path, expanded: Path, dest: Path,
                place: Dict[str, int],
                canvas: Tuple[int, int] = CANVAS,
                keep: Optional[Tuple[float, float]] = None) -> Path:
    """Put the original banner back over its own rectangle.

    The model contributes MARGINS. Everything else it returns is a re-encoded,
    re-scaled approximation of pixels we already have, so we put ours back and
    the banner is untouched by construction rather than by hope. It also frees
    the whole mode from the provider's resolution bucket: nano-banana-pro
    answers a 1080x1920 canvas with 768x1376 whatever the prompt asks for, and
    with the banner re-composited that no longer decides anything.

    This is why a brief's edit cannot be applied during the expansion: it would
    be painted and then immediately overwritten. An edit inside the banner has
    to be its own licensed pass -- and `keep` is how such a pass survives this
    function: the band it names comes from the model's frame, and every other
    row of the banner is restored from ours. So a licensed edit keeps exactly
    the ground it was licensed for and not one row more."""
    # rgb24 is forced at every step and `overlay=format=rgb` with it. Left to
    # negotiate, the chain picks a YUV format and CHROMA-SUBSAMPLES the banner
    # on its way through -- 29,658 pixels of a real client's artwork quietly
    # altered by the very operation meant to restore it (AW025, measured: 29658
    # unforced, 0 forced). Rule 15, somewhere that has nothing to do with
    # encoding a video.
    banner, expanded, dest = Path(banner), Path(expanded), Path(dest)
    cw, ch = canvas
    dest.parent.mkdir(parents=True, exist_ok=True)
    bw, bh = int(place["w"]), int(place["h"])
    strips = [(0, bh)]
    if keep:
        y0, y1 = sorted(float(v) for v in keep)
        lo = max(0, min(bh, int(round(y0 * bh))))
        hi = max(0, min(bh, int(round(y1 * bh))))
        strips = [t for t in ((0, lo), (hi, bh)) if t[1] > t[0]]
    chain = [f"[0:v]scale={cw}:{ch}:flags=lanczos,format=rgb24[bg];",
             f"[1:v]scale={bw}:{bh}:flags=lanczos,format=rgb24,split={len(strips)}"
             + "".join(f"[s{i}]" for i in range(len(strips))) + ";"]
    last = "bg"
    for i, (top, bottom) in enumerate(strips):
        chain.append(f"[s{i}]crop={bw}:{bottom - top}:0:{top}[c{i}];")
        nxt = f"o{i}" if i < len(strips) - 1 else ""
        chain.append(
            f"[{last}][c{i}]overlay={place['x']}:{place['y'] + top}:format=rgb"
            + (f"[{nxt}];" if nxt else ""))
        last = nxt
    proc = subprocess.run(
        [_bin("ffmpeg"), "-y", "-v", "error",
         "-i", str(expanded), "-i", str(banner),
         "-filter_complex", "".join(chain),
         "-frames:v", "1", str(dest)],
        capture_output=True, text=True)
    if proc.returncode != 0 or not dest.exists():
        raise BannerError(f"could not re-composite the banner: {proc.stderr[-200:]}")
    return dest


# ---------------------------------------------------------------------------
# The legal small print.
#
# Their playbook folds this into the expansion: erase the fine print, fill with
# background, all in the one call. On the canvas engine it cannot be folded in,
# and the reason is worth stating -- erasing the small print is an edit INSIDE
# the banner, and the expansion pass is the one pass we hold to zero changes
# there. Asking for both at once means the survival check can no longer tell a
# removed disclaimer from a redrawn headline.
#
# So it is a second pass, over the expanded frame, with the band it may touch
# named in advance and everything else still held to zero.

# Where the fine print sits when nobody says otherwise. Deliberately mean: a
# generous band would licence the CTA button just above it, and the button is
# the one thing on a banner a client will certainly notice moving.
SMALL_PRINT_BAND = (0.90, 1.0)

SMALL_PRINT_PROMPT = (
    "Erase the small legal fine print in the bottom strip of this image and "
    "fill that strip with a seamless continuation of the background behind it. "
    "That is the ONLY change: every other pixel stays exactly as it is. Do not "
    "touch, move, redraw or re-typeset the headline, any subline, the call-to-"
    "action button or its label, the brand logo, or any photograph. Do not add "
    "text of any kind. Output: one single vertical {cw}x{ch} image.")


def small_print_prompt(canvas: Tuple[int, int] = CANVAS) -> str:
    cw, ch = canvas
    return SMALL_PRINT_PROMPT.format(cw=cw, ch=ch)


# ---------------------------------------------------------------------------
# Animating the expanded frame.
#
# Same division of labour as the expansion: the writer decides WHAT moves, and
# this module writes the prompt. It matters more here than there, because two of
# their nine rules are marked "include this line verbatim" -- and a rule that
# depends on a language model reproducing a sentence word for word is a rule
# that holds until the day it does not. Ours are inserted, not requested.
#
# What moves is genuinely a judgement, though, and no amount of assembling
# replaces it: on a photographic banner one or two honest movers, and on a flat
# drawn one, several tiny staggered events, because a single mover on a drawing
# leaves the clip looking broken rather than calm.

# Verbatim, and inserted rather than asked for. Everything printed on the frame
# was approved by a client; a video model that re-renders type produces letters
# that shimmer, and there is no repair for it afterwards.
TEXT_LOCK = (
    "All on-screen text, letters, logos and buttons baked into the first frame "
    "stay PERFECTLY STATIC, pixel-locked, sharp and legible for the entire "
    "clip -- never animate, warp, ripple, translate, redraw or re-render them.")

TEXT_LOCK_NEGATIVE = (
    "NEGATIVE: text flicker, warping letters, melting text, text drifting, "
    "changing words, new text appearing, captions, subtitles, watermark, new "
    "objects entering frame, camera cuts, scene change.")

# The camera. Their default moved to a slight push-in after live tests; ours
# stays locked off, because our frame has an expansion in it -- a push-in
# magnifies the newest, least trustworthy pixels at the top and bottom edges.
CAMERAS: Dict[str, str] = {
    "locked": (
        "THE CAMERA DOES NOT MOVE. This is a locked-off tripod shot: no "
        "push-in, no zoom, no pan, no tilt, no dolly, no drift, no parallax, no "
        "handheld shake, no reframing. The framing of the first frame stays "
        "IDENTICAL until the last frame."),
    "push": ("Very slow subtle push-in, barely perceptible, about 2% over the "
             "clip. No other camera motion: no pan, no tilt, no shake."),
}
CAMERA_NEGATIVE = (" Also add to the NEGATIVE list: camera movement, camera "
                   "push-in, zoom, dolly, pan, tilt, camera drift, parallax, "
                   "handheld shake, reframing.")

# Their range, and the reason for the floor: under five seconds a "breath" of
# motion has no room to happen once, and the clip reads as a still that
# glitched.
BANNER_SECONDS = (5, 10)

# The 4:5 crop is taken from the middle of the 9:16 frame, so a clip whose only
# movement lives in the expanded margins delivers a FROZEN 4:5. Both sizes ship.
CENTRAL_ZONE = (1080, 1350)

ANIMATION_QUESTIONS = """
BANNER ANIMATION -- decide what moves in the expanded frame, and answer these.
You are not writing the prompt; the prompt is built from your answers.

WHAT KIND OF BANNER IS IT?
  photographic (a real photo of a person, food, a product) -> choose ONE or TWO
    heroes, each with one simple, physically plausible motion. No carnival.
  flat / drawn / illustrated (paint daubs, doodles, drawn icons, no photographic
    hero) -> ONE hero is not enough and the clip looks DEAD. Choose 2-4 TINY
    events instead, staggered across the clip, one at a time: a paint daub
    slowly spreads, a brush stroke re-inks itself, a doodle line draws itself
    in, a bow flutters once, a drawn mat unrolls a few degrees.

THE MOVERS. Name each one and its motion, in one clause. Physics first: an
object moves together with its shadow, liquid flows slowly, fabric and leaves
sway, a 3D turn is 10-20 degrees. Amplitudes are a breath, not a jump.

AT LEAST ONE MOVER INSIDE THE CENTRAL 4:5 ZONE (the middle {cz[0]}x{cz[1]} of
the frame). The 4:5 final is cropped from there and ships alongside the 9:16, so a
clip that moves only in the expanded top and bottom areas delivers one live
video and one frozen one. Say which mover is the central one.

ANYTHING CARRYING TEXT DOES NOT MOVE. If lettering is printed on an object --
on the packet, on the jar, on the shirt -- that object stays still entirely.
Animate its shadow, the light on it, or the background instead. Name any such
object.

BACKGROUND: at most one micro-motion (light shifting, steam, leaves, grain), or
none.

NOTHING NEW ENTERS THE FRAME: no hands, no new objects, no angle change, no
cuts. One frame, one scene -- only what is already there comes alive. The single
exception is a drawn banner, where one more motif ALREADY native to its visual
language may gently draw itself in, far from any text.

LOOP-FRIENDLY: the last frame lands close to the first -- a sway, a breath, a
there-and-back. These clips are silent and they repeat.

DURATION: {lo} to {hi} seconds, long enough for the chosen motion to breathe
once or twice.
""".format(cz=CENTRAL_ZONE, lo=BANNER_SECONDS[0], hi=BANNER_SECONDS[1])


def _ended(part: str) -> str:
    """A writer's answer is a clause, not a sentence; the prompt is sentences."""
    part = part.strip()
    part = part[:1].upper() + part[1:]
    return part if part.endswith((".", "!", "?", ":")) else part + "."


def animation_prompt(answers: Dict[str, Any],
                     camera: str = "locked") -> Dict[str, Any]:
    """The GEN prompt for the expanded frame, and how long it runs.

    `answers` carries `movers` (a list of clauses), `central` (which mover is
    inside the 4:5 zone), optional `frozen` (objects carrying text), optional
    `background`, `seconds`, and `graphic` for a flat drawn banner."""
    a = dict(answers or {})
    if camera not in CAMERAS:
        raise BannerError(
            f"camera must be one of {sorted(CAMERAS)}, not '{camera}'")
    movers = [str(m).strip() for m in (a.get("movers") or []) if str(m).strip()]
    graphic = bool(a.get("graphic"))
    lo, hi = (2, 4) if graphic else (1, 2)
    if not lo <= len(movers) <= hi:
        raise BannerError(
            f"a {'drawn' if graphic else 'photographic'} banner takes {lo}-{hi} "
            f"movers, not {len(movers)} -- "
            + ("one mover on a drawing leaves the clip looking dead"
               if graphic else "more than two at once is a carnival"))
    central = str(a.get("central") or "").strip()
    if not central:
        raise BannerError(
            "no movement was placed inside the central 4:5 zone -- the 4:5 "
            "final is cropped from there and would ship frozen")

    seconds = int(a.get("seconds") or 0) or 7
    if not BANNER_SECONDS[0] <= seconds <= BANNER_SECONDS[1]:
        raise BannerError(
            f"{seconds}s is outside {BANNER_SECONDS[0]}-{BANNER_SECONDS[1]}s")

    parts = [TEXT_LOCK]
    if graphic:
        parts.append(
            "The banner is a flat illustration. Stage these small events "
            "across the clip, one at a time, never all at once, each slow and "
            "small in amplitude and in the banner's own visual language: "
            + "; ".join(movers) + ".")
    else:
        parts.append("Animate only this: " + "; ".join(movers) + ".")
    parts.append(f"Inside the central 4:5 area of the frame: {central}")
    frozen = str(a.get("frozen") or "").strip()
    if frozen:
        parts.append(
            f"{frozen} carries printed lettering and therefore does not move at "
            f"all -- animate only its shadow, the light on it, or the "
            f"background behind it.")
    background = str(a.get("background") or "").strip()
    if background:
        parts.append(f"Background micro-motion, subtle: {background}")
    parts.append(
        "Objects move together with their shadows; liquids flow slowly; fabric "
        "and leaves sway gently; any turn is 10-20 degrees. Amplitudes are a "
        "breath, not a jump. Nothing new enters the frame: no hands, no new "
        "objects, no angle change, no cuts. The last frame lands close to the "
        "first, so the clip loops.")
    parts.append(CAMERAS[camera])
    parts.append("No speech, no voice-over, no lip movement; subtle ambient "
                 "sound only.")
    parts.append(TEXT_LOCK_NEGATIVE
                 + (CAMERA_NEGATIVE if camera == "locked" else ""))
    return {"prompt": " ".join(_ended(p) for p in parts),
            "seconds": seconds, "camera": camera,
            "graphic": graphic}
