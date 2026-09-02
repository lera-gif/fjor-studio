import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fjor_studio.app import new_job, open_studio  # noqa: E402


def write_config(home: Path, pipeline=None, models=None, delivery=None):
    cfg = home / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    base_pipeline = {
        "analysis": {"depth": "default", "ref_kind": "ugc"},
        "qa": {"enabled": True,
               "plates": {"enabled": True, "auto_regen": True, "max_attempts": 2},
               "clips": {"enabled": True, "auto_regen": False, "max_attempts": 1}},
        # GATE_CLIPS is skipped here so the tests written before it existed keep
        # walking the path they were written for. The gate itself, and the
        # editor that lives on it, are exercised in test_edit.py -- including a
        # full walk that does NOT skip it, and a check that the shipped
        # config/pipeline.yaml stops there.
        "gates": {"skip": ["GATE_CLIPS"]},
        "voice": {"source": "seedance"},
        # off by default: transcription needs a live key. The subtitle path is
        # exercised directly in test_subtitles.py with explicit word timings.
        "subtitles": {"enabled": False},
        "delivery": {"formats": ["9:16"]},
    }
    base_verticals = {"verticals": {
        "lipedema_pilates": {"prefix": "LIPIL", "folder": "LIPEDEMA PILATES"},
        "menopause_yoga": {"prefix": "MENY", "folder": "MENOPAUSE YOGA"},
        "yoga": {"prefix": "Y", "folder": "YOGA"},
    }}
    base_models = {
        "providers": {k: "mock" for k in
                      ("analysis", "text", "image", "video", "speech")},
        "models": {"analysis": "gemini-3.1-pro-preview", "text": "claude-opus-4-8",
                   "qa": "gemini-3-flash-preview", "image": "banana-pro",
                   "video": "bytedance/seedance-2-fast",
                   "speech": "eleven_multilingual_v2"},
    }
    def merge(a, b):
        out = dict(a)
        for k, v in (b or {}).items():
            out[k] = merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
        return out
    (cfg / "pipeline.yaml").write_text(yaml.safe_dump(merge(base_pipeline, pipeline)))
    (cfg / "models.yaml").write_text(yaml.safe_dump(merge(base_models, models)))
    (cfg / "verticals.yaml").write_text(yaml.safe_dump(base_verticals))
    # deliver into the sandbox, never the real VIDEO tree
    base_delivery = {
        "root": str(home / "VIDEO"), "week_folder": "{week} week",
        # the real library: packshots and the approved disclaimer overlays
        "assets_dir": str(Path(__file__).resolve().parents[1] / "assets"),
        "trash_subfolder": "_to_delete",
        "naming": {"channel": "fb", "type": "video", "source": "nano",
                   "default_producer": "lp"},
        "sizes": {"9:16": [1080, 1920], "4:5": [1080, 1350]},
        # real dimensions (the filenames carry them) but a throwaway encode:
        # the suite assembles dozens of videos and none is ever watched
        "export": {"crf": 34, "preset": "ultrafast"}}
    # `delivery` was accepted and then dropped on the floor here: a caller that
    # passed one got the defaults and a green test that proved nothing.
    (cfg / "delivery.yaml").write_text(
        yaml.safe_dump(merge(base_delivery, delivery)))


def write_replies(home: Path, echo_images: bool = False, echo_size=None,
                  **replies):
    """Script the mock backend's text replies. Keys: analysis, text,
    'qa:plate', 'qa:clip'. A list is consumed in order, last entry repeats.

    `echo_images` makes an image call hand back the media it was given, which is
    what an edit-in-place model does and the only way to exercise a check that
    compares the result with its input. `echo_size` hands it back at that size
    instead of the one it was given, which is what a real image model does."""
    cfg = home / "config"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "auth.yaml").write_text(yaml.safe_dump(
        {"mock": {"replies": replies, "echo_images": echo_images,
                  "echo_size": list(echo_size) if echo_size else None}}))


@pytest.fixture
def home(tmp_path):
    write_config(tmp_path)
    return tmp_path


@pytest.fixture
def reference(tmp_path):
    ref = tmp_path / "reference.mp4"
    ref.write_bytes(b"REFERENCE VIDEO BYTES")
    return ref


@pytest.fixture
def studio(home):
    return open_studio(home)


def make_job(store, reference, scenes=2, vertical="lipedema_pilates",
             config=None, **intake):
    payload = {"reference": str(reference), "scene_count": scenes,
               "week": 34, "concept": "ugc", "producer": "lp"}
    payload.update(intake)
    return new_job(store, config, vertical, payload)


def scene_plan(n=2, duration=5.0):
    """The JSON the text backend is expected to answer with."""
    return json.dumps({"scenes": [
        {"idx": i, "image_prompt": f"plate {i}", "video_prompt": f"motion {i}",
         "duration_s": duration} for i in range(n)]})


def a_banner(path, w=1080, h=1080):
    """A client banner: an offer, a button, and a line of legal small print.

    Real drawn text rather than a coloured rectangle, because every check in
    banner mode is about whether type survived, and type is the thing that
    rescales badly."""
    import subprocess
    from fjor_studio.assemble import ffmpeg_with_libass
    font = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "Inter-Bold.ttf"
    subprocess.run(
        [ffmpeg_with_libass(), "-y", "-v", "error", "-f", "lavfi",
         "-i", f"color=c=0x1B4F3A:size={w}x{h}", "-vf",
         f"drawtext=fontfile={font}:text='LOSE THE SWELLING':fontcolor=white:"
         f"fontsize=86:x=(w-tw)/2:y={int(h * 0.28)},"
         f"drawbox=x={w // 2 - 200}:y={int(h * 0.52)}:w=400:h=110:color=0xFFC93C:t=fill,"
         f"drawtext=fontfile={font}:text='GET THE PLAN':fontcolor=black:"
         f"fontsize=44:x=(w-tw)/2:y={int(h * 0.55)},"
         f"drawtext=fontfile={font}:text='Results vary. Not medical advice.':"
         f"fontcolor=0xBBBBBB:fontsize=22:x=(w-tw)/2:y={int(h * 0.93)}",
         "-frames:v", "1", str(path)], check=True, capture_output=True)
    return path


def banner_answers(**over):
    """What the compact brain is expected to answer with."""
    answers = {
        "tier": "full",
        "above": "the plain studio backdrop simply keeps going",
        "below": "the tabletop surface continues: same texture detail, same "
                 "grain, same depth of field and the same light direction",
        "cut_off": "nothing is cut off",
        "leave_cropped": "",
        "preserve": ["LOSE THE SWELLING", "GET THE PLAN"],
        "decor": "keep the new areas clean and empty",
        "graphic": False,
        "movers": ["the steam above the mug drifts upward and thins"],
        "central": "the steam rises through the middle of the frame",
        "frozen": "", "background": "", "seconds": 7,
    }
    answers.update(over)
    return json.dumps(answers)
