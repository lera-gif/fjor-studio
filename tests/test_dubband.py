"""The blur band that covers a dubbed video's old burnt-in subtitles.

Ported from their tool with the geometry unchanged, because every constant in
it is a fix somebody paid for. These tests hold the two that cost them a run.
"""
import subprocess

import pytest

from fjor_studio import dubband
from fjor_studio.assemble import _bin, ffmpeg_with_libass


def test_the_radius_is_clamped_against_the_chroma_plane():
    """Their scar: boxblur applies the radius TO EACH PLANE, and in yuv420p the
    chroma planes are half size. On 1920x1080 a radius that fitted luma overran
    chroma and ffmpeg died with 'memory access out of bounds', losing the whole
    paid dub."""
    for w, h in ((1080, 1920), (1920, 1080), (1080, 1350), (640, 360)):
        g = dubband.geometry(w, h, strength=100)
        assert g["r"] <= max(2, min(w, g["RH"]) // 4 - 1) + 1
        assert g["r_hard"] <= g["r"]


def test_every_dimension_is_even_because_yuv420p_demands_it():
    for w, h in ((1080, 1920), (1080, 1350), (1920, 1080), (721, 1281)):
        g = dubband.geometry(w, h)
        assert g["RY"] % 2 == 0 and g["RH"] % 2 == 0
        assert g["BY"] % 2 == 0 and g["BH"] % 2 == 0


def test_the_blurred_region_carries_a_margin_around_the_feather():
    """boxblur repeats pixels at the edge of its region, so without a margin a
    strip of under-blurred video survives at the seam -- and on a THIN band the
    radius limit collapsed the strength to almost nothing."""
    g = dubband.geometry(1080, 1920)
    assert g["RY"] < g["soft_top"] and g["RY"] + g["RH"] > g["soft_bot"]


def test_the_strength_curve_is_linear_then_steeper():
    """Linear to the knee so the low end is controllable, quadratic after it so
    the top is actually strong."""
    r = [dubband.blur_radius_1080(s) for s in (10, 40, 80, 100)]
    assert r == sorted(r)
    assert r[2] - r[1] < r[3] - r[2]        # the knee bites


def test_their_defaults_are_their_defaults():
    """Not ours to tune: 78% down the frame, 15% tall, feather 35, strength 80."""
    assert (dubband.BAND_Y_PCT, dubband.BAND_H_PCT) == (78.0, 15.0)
    assert dubband.FEATHER_DEFAULT == 35 and dubband.STRENGTH_DEFAULT == 80


def test_the_chroma_radius_is_half_the_luma_one():
    assert dubband.boxblur(48) == "boxblur=48:2:24:2"


# -- and it has to actually run ----------------------------------------------

def test_the_band_really_covers_a_burnt_in_subtitle(tmp_path):
    """Run rather than asserted: the alpha ramp is built with `geq` where their
    tool drew a PNG in a canvas, so it is the one part that is not a port."""
    src, out = tmp_path / "src.mp4", tmp_path / "out.mp4"
    font = pytest.importorskip("pathlib").Path(__file__).resolve().parents[1] \
        / "assets" / "fonts" / "Inter-Bold.ttf"
    subprocess.run(
        [ffmpeg_with_libass(), "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=white:size=540x960:rate=25:duration=1", "-vf",
         f"drawtext=fontfile={font}:text='SUBTITLE':fontcolor=black:"
         f"fontsize=40:x=(w-tw)/2:y=h*0.78",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
        check=True, capture_output=True)
    g = dubband.geometry(540, 960)
    proc = subprocess.run(
        [_bin("ffmpeg"), "-y", "-v", "error", "-i", str(src),
         "-filter_complex", dubband.filter_chain(g),
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr[-400:]
    assert out.exists()

    # the band region should have lost its hard black-on-white edges
    def edge_energy(path):
        raw = subprocess.run(
            [_bin("ffmpeg"), "-v", "error", "-i", str(path), "-vf",
             f"crop=540:{g['BH']}:0:{g['BY']},format=gray",
             "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True, check=True).stdout
        return sum(abs(raw[i] - raw[i - 1]) for i in range(1, len(raw)))

    assert edge_energy(out) < edge_energy(src) * 0.5, "the subtitle survived"
