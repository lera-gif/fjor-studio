"""ElevenLabs text-to-speech.

The voice for a shot nobody is filmed saying. Their v4 note is short and every
clause in it is a scar, so each is honoured here:

    "Prepared right after QA rather than at the end, paid once per text, never
     silently absent."

  * **Paid once per text.** The same line spoken twice is the same audio, and a
    re-run, a revision or a variation would otherwise buy it again. Keyed on the
    text and the voice, cached in the job directory -- see `stages.steps`.
  * **Never silently absent.** A missing track is the failure that ships: the
    clip is silent by design, so nothing downstream looks wrong, and the ad goes
    out with no voice. This backend raises rather than returning an empty file.

Unlike Gemini's TTS this endpoint answers with the audio itself rather than JSON
with base64 inside, and it answers mp3 -- which ffmpeg mixes without complaint,
so it is written as it arrives instead of being transcoded on the way in.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import http as http_mod
from .base import Backend, GenError, GenResult

BASE = "https://api.elevenlabs.io"

# Their own default. `eleven_multilingual_v2` is the one this studio's config
# already names, and the one that speaks the Spanish and Portuguese cuts.
DEFAULT_MODEL = "eleven_multilingual_v2"

# What a voice sounds like, per their API. Left at the service's own defaults
# except for one: `speed`. An ad read at the model's natural pace runs long
# against a clip whose length was fixed when the plan was written.
DEFAULT_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75, "speed": 1.0}


class ElevenLabsBackend(Backend):
    name = "elevenlabs"

    def __init__(self, cfg: Optional[Dict[str, Any]] = None):
        cfg = cfg or {}
        self.api_key = str(cfg.get("api_key") or "").strip()
        if not self.api_key:
            raise GenError("elevenlabs backend needs an api_key -- load a kit "
                           "at the top of the dashboard, or fill in auth.yaml")
        self.base = str(cfg.get("base_url") or BASE).rstrip("/")
        self.http = cfg.get("http")

    def capabilities(self) -> set:
        return {"speech"}

    def voices(self) -> List[Dict[str, str]]:
        """The voices this key can use: id and name, nothing else.

        Exists so a producer can be TOLD the ids rather than sent to a web
        dashboard to copy one, which is where a wrong id comes from."""
        payload = http_mod.request_json(
            "GET", f"{self.base}/v1/voices", {"xi-api-key": self.api_key},
            None, timeout=60.0, http=self.http)
        return [{"id": v.get("voice_id", ""), "name": v.get("name", "")}
                for v in (payload.get("voices") or [])]

    def submit(self, kind, model, prompt, params=None, medias=None) -> GenResult:
        self.check(kind)
        params = dict(params or {})
        out = params.get("out_path")
        if not out:
            # checked BEFORE the request: audio we cannot save is audio we paid
            # for and threw away
            raise GenError("elevenlabs: params['out_path'] is required")
        text = str(prompt or "").strip()
        if not text:
            raise GenError(
                "elevenlabs was asked to speak nothing. A shot with a voice and "
                "no line is a shot that ships silent -- fix the plan, do not "
                "buy an empty track.")
        voice_id = str(params.get("voice") or "").strip()
        if not voice_id:
            raise GenError(
                "no ElevenLabs voice id. Set `voice.voice_id` in pipeline.yaml "
                "to one of the ids this key can use -- `fjor-studio voices` "
                "lists them. A NAME is not an id here, unlike Gemini's.")

        settings = dict(DEFAULT_SETTINGS)
        settings.update(params.get("voice_settings") or {})
        body = {"text": text, "model_id": model or DEFAULT_MODEL,
                "voice_settings": settings}
        status, headers, blob = http_mod.request(
            "POST", f"{self.base}/v1/text-to-speech/{voice_id}",
            {"xi-api-key": self.api_key, "Accept": "audio/mpeg"},
            json=body, timeout=300.0)
        # The API answers JSON on refusal and audio on success, so the content
        # type is the difference between a track and an error we would have
        # written to disk as if it were one.
        kind_of = str(headers.get("content-type", ""))
        if status >= 400 or not kind_of.startswith("audio"):
            detail = blob[:300].decode("utf-8", "replace")
            raise GenError(f"elevenlabs refused ({status}, {kind_of}): {detail}")
        if not blob:
            raise GenError("elevenlabs returned an empty track -- a silent "
                           "clip with no voice is the failure that ships")
        path = Path(out)
        if path.suffix.lower() != ".mp3":
            path = path.with_suffix(".mp3")     # it IS mp3; say so on disk
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
        return GenResult(
            kind="speech", backend=self.name, model=model or DEFAULT_MODEL,
            status="completed", task_id=f"11l-{abs(hash((text, voice_id))):x}",
            files=[str(path)],
            raw={"voice_id": voice_id, "bytes": len(blob), "chars": len(text)})

    def poll(self, result: GenResult, timeout_s: float = 1200.0) -> GenResult:
        return result          # the audio arrived with the request
