"""A deterministic backend that spends nothing and writes real files.

It is not only a test double. It is how a producer can walk the whole pipeline,
see every gate and every forecast, and check the shape of a job before any of it
costs money.

Deterministic on purpose: the same prompt yields the same fake id and the same
bytes, so a resume test can prove the pipeline collected an existing generation
rather than quietly buying a new one.
"""
from __future__ import annotations

import hashlib
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import Backend, GenError, GenResult, KINDS, ModerationRejected

# A prompt containing this marker is rejected the way a real moderation refusal
# arrives, so the failure path can be exercised without tripping a real filter.
MODERATION_TRIPWIRE = "__moderation__"
FAIL_TRIPWIRE = "__fail__"


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


class MockBackend(Backend):
    name = "mock"

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        cfg = cfg or {}
        self.out_dir = Path(cfg.get("out_dir", ".")) if cfg.get("out_dir") else None
        self.credits_per_call = float(cfg.get("credits", 0.0))
        # Scripted replies, keyed by kind or by "qa:plate" / "qa:clip". A list is
        # consumed in order and its last entry repeats, which is how a test says
        # "fail the first plate, pass the retry".
        self.replies: Dict[str, Any] = dict(cfg.get("replies") or {})
        # "the model returned its input unchanged". An image edit -- a keyed
        # card, a banner expansion -- is given the frame it edits, and a double
        # that hands back an unrelated prototype cannot exercise a check that
        # COMPARES the two.
        self.echo_images = bool(cfg.get("echo_images"))
        # ... at ITS OWN resolution, which is what a real one does. AW025 cost
        # two paid failures to discover that nano-banana-pro answers a 1080x1920
        # canvas with 768x1376 (or 1536x2752 at 2K), the same size every time,
        # whatever the prompt asks for. A double that always answers in the
        # exact size it was given cannot fail the way the real thing does.
        self.echo_size = cfg.get("echo_size") or None
        self._reply_pos: Dict[str, int] = {}
        self.calls: List[Dict[str, Any]] = []

    def _reply_key(self, kind: str, params: Dict[str, Any]) -> str:
        qa_kind = (params or {}).get("qa_kind")
        return f"qa:{qa_kind}" if qa_kind else kind

    def _scripted(self, key: str) -> Optional[str]:
        script = self.replies.get(key)
        if script is None:
            return None
        if isinstance(script, (list, tuple)):
            if not script:
                return None
            pos = self._reply_pos.get(key, 0)
            self._reply_pos[key] = pos + 1
            return str(script[min(pos, len(script) - 1)])
        return str(script)

    def capabilities(self) -> set:
        return set(KINDS)

    def submit(self, kind, model, prompt, params=None, medias=None) -> GenResult:
        self.check(kind)
        params = params or {}
        if MODERATION_TRIPWIRE in (prompt or ""):
            raise ModerationRejected(
                f"mock moderation refused this framing ({kind}/{model})")
        task_id = f"mock-{kind}-{_digest(kind, model, prompt or '')}"
        self.calls.append({"op": "submit", "kind": kind, "model": model,
                           "task_id": task_id, "prompt": prompt,
                           "params": dict(params), "medias": list(medias or [])})
        return GenResult(kind=kind, backend=self.name, model=model,
                         status="submitted", task_id=task_id,
                         raw={"prompt": prompt, "params": dict(params),
                              "medias": list(medias or [])})

    def poll(self, result: GenResult, timeout_s: float = 1200.0) -> GenResult:
        self.calls.append({"op": "poll", "task_id": result.task_id})
        prompt = (result.raw or {}).get("prompt", "") if isinstance(result.raw, dict) else ""
        if FAIL_TRIPWIRE in prompt:
            result.status = "failed"
            result.notices.append("mock failure tripwire")
            return result
        params = (result.raw or {}).get("params", {}) if isinstance(result.raw, dict) else {}
        result.status = "completed"
        result.credits = self._credits(result.kind, params)
        if result.kind in ("analysis", "text"):
            result.text = self._text(result)
        else:
            result.files = [self._write(result)]
            result.urls = [f"mock://{result.task_id}"]
        return result

    # -- internals -----------------------------------------------------------
    def _credits(self, kind: str, params: Dict[str, Any]) -> float:
        if self.credits_per_call:
            return self.credits_per_call
        # mirror the real shape: video bills per second, images flat
        if kind == "video":
            return round(24.8 * float(params.get("duration", 5) or 5), 4)
        return {"image": 7.0, "speech": 1.0}.get(kind, 0.0)

    def _text(self, result: GenResult) -> str:
        raw = result.raw if isinstance(result.raw, dict) else {}
        params = raw.get("params") or {}
        canned = params.get("mock_reply")
        if canned is not None:
            return str(canned)
        scripted = self._scripted(self._reply_key(result.kind, params))
        if scripted is not None:
            return scripted
        return f"[mock {result.kind}] {result.task_id}"

    def _write(self, result: GenResult) -> str:
        raw = result.raw if isinstance(result.raw, dict) else {}
        target = (raw.get("params") or {}).get("out_path")
        if not target:
            if self.out_dir is None:
                raise GenError("mock backend: params['out_path'] or cfg['out_dir'] "
                               "is required so the artifact has somewhere to land")
            ext = {"image": "png", "video": "mp4", "speech": "wav"}[result.kind]
            target = self.out_dir / f"{result.task_id}.{ext}"
        path = Path(target)
        path.parent.mkdir(parents=True, exist_ok=True)
        medias = raw.get("medias") or []
        if self.echo_images and result.kind == "image" and medias:
            if self.echo_size:
                w, h = (int(v) for v in self.echo_size)
                _ffmpeg(["-i", str(medias[0]), "-vf",
                         f"scale={w}:{h}:flags=lanczos", "-frames:v", "1",
                         str(path)], path)
            else:
                shutil.copyfile(medias[0], path)
            return str(path)
        # REAL media, not a text file with a media extension. Assembly is ffmpeg,
        # and a mock whose output ffmpeg cannot open would let the whole assembly
        # stage pass in tests while being incapable of ever working.
        shutil.copyfile(_prototype(result.kind), path)
        return str(path)


# -- prototype media ---------------------------------------------------------
# Built once per process and copied thereafter: tiny, valid, openable files.

_PROTOTYPES: Dict[str, Path] = {}


def _png(width: int = 64, height: int = 114, rgb=(40, 40, 48)) -> bytes:
    rows = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows))
            + chunk(b"IEND", b""))


def _prototype(kind: str) -> Path:
    if kind in _PROTOTYPES and _PROTOTYPES[kind].exists():
        return _PROTOTYPES[kind]
    tmp = Path(tempfile.mkdtemp(prefix="fjor-mock-"))
    if kind == "image":
        p = tmp / "plate.png"
        p.write_bytes(_png())
    elif kind == "video":
        p = tmp / "clip.mp4"
        _ffmpeg(["-f", "lavfi", "-i", "color=c=#282830:size=64x114:rate=30:duration=1",
                 "-f", "lavfi", "-i",
                 "anullsrc=channel_layout=stereo:sample_rate=48000",
                 "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", str(p)], p)
    elif kind == "speech":
        p = tmp / "vo.wav"
        _ffmpeg(["-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=24000",
                 "-t", "1", str(p)], p)
    else:
        raise GenError(f"mock: no prototype for kind '{kind}'")
    _PROTOTYPES[kind] = p
    return p


def _ffmpeg(args: List[str], expect: Path) -> None:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise GenError("mock backend needs ffmpeg to produce real media "
                       "(assembly is ffmpeg, so a stub would prove nothing)")
    proc = subprocess.run([exe, "-y", "-v", "error"] + args,
                          capture_output=True, text=True)
    if proc.returncode != 0 or not expect.exists():
        raise GenError(f"mock: ffmpeg failed building a prototype: "
                       f"{proc.stderr[-300:]}")
