"""The blur band that covers a dubbed video's old burnt-in subtitles.

Ported from their tool, geometry and constants unchanged, because every line of
it is a fix somebody paid for. The comments below are theirs, translated:

  * boxblur needs "radius < side / 2" and applies it TO EACH PLANE. In yuv420p
    the chroma planes are half size and take the same radius as luma, so on a
    landscape 1920x1080 (a 334-row band, chroma 167) radius 85 fitted luma and
    overran chroma: the run died with "memory access out of bounds" and the
    whole dub was lost. So the radius is clamped against the SMALLER plane, and
    the chroma radius is set explicitly to half -- geometrically the same blur.
  * The feathered zone is blurred with a +/-r MARGIN, because boxblur extends
    the edge of its region by repeating pixels; without the margin a strip of
    under-blurred video survives at the seam. The margin also lifts the
    "radius < height / 2" limit off THIN bands, where strength otherwise
    collapsed to almost nothing.
  * yuv420p requires even dimensions, hence the `& ~1` everywhere.

The one thing we supply differently: their producer DRAGS the band into place
with the mouse. There is no mouse here, so the band comes from their own
defaults -- 78% down the frame, 15% tall -- and is a parameter. For our own
finals we know where we burned the subtitles, so this can be computed later; it
is not guessed now.
"""
from __future__ import annotations

from typing import Any, Dict

# Their constants, unchanged.
FEATHER_DEFAULT = 35
FEATHER_MAX = 50
STRENGTH_DEFAULT = 80
STRENGTH_MIN = 10
BLUR_R_PER_PCT = 0.6
BLUR_KNEE = 80
BLUR_R_TOP = 120

# Where the band sits when nobody says otherwise: their own default position.
BAND_Y_PCT = 78.0            # centre of the band, per cent of frame height
BAND_H_PCT = 15.0            # its height


def _clamp(value: float, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def blur_radius_1080(strength: float) -> float:
    """Their strength curve, for a 1080-wide frame. Linear to the knee, then
    quadratic -- so the top of the range is usably strong without the low end
    being coarse."""
    s = _clamp(strength, STRENGTH_MIN, 100, STRENGTH_DEFAULT)
    r = BLUR_R_PER_PCT * s
    if s > BLUR_KNEE:
        t = (s - BLUR_KNEE) / (100 - BLUR_KNEE)
        r += (BLUR_R_TOP - BLUR_R_PER_PCT * 100) * t * t
    return r


def _radius_cap(rad: int, w: int, h: int) -> int:
    """Clamped against the SMALLER (chroma) plane. This is the line that stops
    ffmpeg dying half way through a paid dub."""
    return max(2, min(int(rad), max(2, int(min(w, h) / 4) - 1)))


def geometry(width: int, height: int, y_pct: float = BAND_Y_PCT,
             h_pct: float = BAND_H_PCT, feather: float = FEATHER_DEFAULT,
             strength: float = STRENGTH_DEFAULT) -> Dict[str, Any]:
    """The band in PIXELS: one source of truth, as in their tool."""
    W, H = int(width), int(height)
    BH = max(2, min(H, int(round(H * _clamp(h_pct, 0, 100, BAND_H_PCT) / 100)) & ~1))
    BY = max(0, min(H - BH, int(round(H * _clamp(y_pct, 0, 100, BAND_Y_PCT) / 100
                                      - BH / 2)))) & ~1
    fpct = _clamp(feather, 0, FEATHER_MAX, FEATHER_DEFAULT)
    F = max(0, int(round(BH * fpct / 100)))
    soft_top, soft_bot = max(0, BY - F), min(H, BY + BH + F)
    sp = _clamp(strength, STRENGTH_MIN, 100, STRENGTH_DEFAULT)
    r = max(2, int(round(W / 1080 * blur_radius_1080(sp))))

    RY = max(0, soft_top - r) & ~1
    RB = min(H, soft_bot + r)
    if (RB - RY) & 1:
        RB = min(H, RB + 1)
    RH = RB - RY
    if RH & 1:
        RH -= 1
    RH = max(2, RH)
    if RY + RH > H:
        RH = max(2, (H - RY) & ~1)
    r = _radius_cap(r, W, RH)
    # the fallback path blurs EXACTLY the band with no margin, and there the
    # radius is limited by the band itself
    r_hard = min(r, _radius_cap(r, W, BH))
    return {"BH": BH, "BY": BY, "F": F, "feather_pct": fpct,
            "soft_top": soft_top, "soft_bot": soft_bot,
            "RY": RY, "RH": RH, "r": r, "r_hard": r_hard, "strength": sp,
            "width": W, "height": H}


def boxblur(radius: int) -> str:
    """Their filter string. The chroma radius is HALF the luma one, explicitly:
    same blur geometrically, and it fits the half-size plane."""
    r = max(2, int(radius))
    return f"boxblur={r}:2:{max(1, r // 2)}:2"


def filter_chain(g: Dict[str, Any]) -> str:
    """Crop the region, blur it, feather it, lay it back.

    The feather is a vertical alpha gradient -- black outside the band, rising
    across the feather, white in its core -- which their tool draws as a PNG in
    a canvas and merges with `alphamerge`. `geq` builds the same ramp here
    without a temporary file."""
    RY, RH, BY, BH = g["RY"], g["RH"], g["BY"], g["BH"]
    top, bot, F = g["soft_top"], g["soft_bot"], g["F"]
    # Y within the cropped region, in the region's own coordinates.
    a_top, a_core0 = top - RY, BY - RY
    a_core1, a_bot = BY + BH - RY, bot - RY
    if F <= 0:
        ramp = f"if(between(Y,{a_core0},{a_core1}),255,0)"
    else:
        ramp = (f"if(lt(Y,{a_top}),0,"
                f"if(lt(Y,{a_core0}),255*(Y-{a_top})/{max(1, a_core0 - a_top)},"
                f"if(lt(Y,{a_core1}),255,"
                f"if(lt(Y,{a_bot}),255*({a_bot}-Y)/{max(1, a_bot - a_core1)},0))))")
    return (
        f"[0:v]split=2[base][band];"
        f"[band]crop={g['width']}:{RH}:0:{RY},{boxblur(g['r'])},"
        f"format=yuva420p,geq=lum='p(X,Y)':cb='p(X,Y)':cr='p(X,Y)':"
        f"a='{ramp}'[blurred];"
        f"[base][blurred]overlay=0:{RY}")
