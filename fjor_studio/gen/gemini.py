"""Gemini — reference analysis, prompt writing, media QA and TTS.

One key covers all of them, which is why the whole brain is routed here.

Three facts worth knowing before editing this:

- **Video must go through the File API.** Inline bytes are fine for an image but
  not for a reference video, and the File API is a three-step resumable upload
  whose result is not usable until its `state` reaches ACTIVE.
- **Image aspect ratio lives at `generationConfig.imageConfig.aspectRatio`.**
  Omit it and you get landscape, silently.
- **TTS returns headerless PCM.** It has to be wrapped into a WAV container or
  nothing will play it. There is also no speech-rate control -- measured around
  2.5 words/second, take it or leave it.
- **Gemini 3 models think, and thinking tokens are spent out of
  `maxOutputTokens`.** Measured on gemini-3-flash-preview, 2026-08-18: the same
  prompt under a 300-token cap spent 286 on thinking and 10 on the answer,
  finishing MAX_TOKENS with a truncated fragment; uncapped it answered in 25.
  So a small cap does not truncate the answer, it *replaces* it. `max_tokens` is
  therefore unset by default, and `thinking_budget: 0` is available for
  deterministic work like media QA -- it produced byte-identical output with
  zero thinking tokens.

Unlike KIE, generateContent is synchronous: `submit` does the work and `poll`
returns it unchanged. There is no task id to collect, so nothing is lost by that.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import struct
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import http as http_mod
from .base import (AuthRequired, Backend, GenError, GenResult,
                   ModerationRejected, ProviderBusy)

BASE = "https://generativelanguage.googleapis.com"
API = "/v1beta"

VIDEO_EXT = {".mp4", ".mov", ".webm", ".m4v", ".avi", ".mkv"}
# Blocked-for-safety finish reasons. Distinguished from an empty answer because
# a safety block will repeat, and retrying one is time spent to fail again.
_BLOCKED = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY"}


class GeminiBackend(Backend):
    name = "gemini"

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, http=None):
        cfg = cfg or {}
        self.api_key = cfg.get("api_key") or ""
        if not self.api_key:
            raise GenError("gemini backend needs auth.yaml gemini.api_key")
        self.base = str(cfg.get("base_url", BASE)).rstrip("/")
        self.http = http or http_mod.request
        self.file_wait_s = float(cfg.get("file_wait_s", 300.0))
        self.poll_interval = float(cfg.get("poll_interval", 2.0))
        self._files: Dict[str, Dict[str, str]] = {}   # local path -> {uri, mime}

    def capabilities(self) -> set:
        return {"analysis", "text", "speech"}

    # -- files ---------------------------------------------------------------
    def upload(self, path: str) -> Dict[str, str]:
        """Resumable upload, then wait for ACTIVE.

        A file that is merely uploaded is not yet usable: referencing one in
        PROCESSING state fails the generateContent call, and the failure does
        not say why."""
        if path in self._files:
            return self._files[path]
        p = Path(path)
        if not p.exists():
            raise GenError(f"gemini upload: no such file: {p}")
        raw = p.read_bytes()
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"

        status, headers, _body = self.http(
            "POST", f"{self.base}/upload{API}/files?key={self.api_key}",
            {"X-Goog-Upload-Protocol": "resumable",
             "X-Goog-Upload-Command": "start",
             "X-Goog-Upload-Header-Content-Length": str(len(raw)),
             "X-Goog-Upload-Header-Content-Type": mime},
            {"file": {"display_name": p.name}}, None, 300.0)
        upload_url = headers.get("x-goog-upload-url")
        if not upload_url:
            raise GenError("gemini upload: no X-Goog-Upload-URL in the start "
                           "response -- the resumable handshake did not begin")

        _s, _h, body = self.http(
            "POST", upload_url,
            {"Content-Length": str(len(raw)), "X-Goog-Upload-Offset": "0",
             "X-Goog-Upload-Command": "upload, finalize"},
            None, raw, 900.0)
        info = (json.loads(body.decode("utf-8")) or {}).get("file") or {}
        uri, name = info.get("uri"), info.get("name")
        if not uri:
            raise GenError(f"gemini upload: no file uri returned: {body[:200]!r}")

        state = str(info.get("state") or "").upper()
        deadline = time.time() + self.file_wait_s
        while state and state != "ACTIVE":
            if state == "FAILED":
                raise GenError(f"gemini upload: {p.name} failed processing")
            if time.time() > deadline:
                raise ProviderBusy(
                    f"gemini: {p.name} still {state} after {self.file_wait_s:.0f}s")
            time.sleep(self.poll_interval)
            info = http_mod.request_json(
                "GET", f"{self.base}{API}/{name}?key={self.api_key}", {},
                http=self.http)
            state = str(info.get("state") or "").upper()
        out = {"uri": uri, "mime": info.get("mimeType") or mime, "name": name or ""}
        self._files[path] = out
        return out

    # -- request building ----------------------------------------------------
    def parts_for(self, prompt: str, medias: Optional[List[str]] = None
                  ) -> List[Dict[str, Any]]:
        """Media first, then the instruction. A video referenced after its
        question is answered less reliably than one referenced before it."""
        parts: List[Dict[str, Any]] = []
        for m in medias or []:
            p = Path(m)
            if p.suffix.lower() in VIDEO_EXT:
                f = self.upload(str(p))
                parts.append({"fileData": {"mimeType": f["mime"], "fileUri": f["uri"]}})
            else:
                mime = mimetypes.guess_type(p.name)[0] or "image/png"
                parts.append({"inlineData": {
                    "mimeType": mime,
                    "data": base64.b64encode(p.read_bytes()).decode()}})
        parts.append({"text": prompt})
        return parts

    def build_body(self, prompt: str, params: Dict[str, Any],
                   medias: Optional[List[str]] = None) -> Dict[str, Any]:
        body: Dict[str, Any] = {"contents": [
            {"role": "user", "parts": self.parts_for(prompt, medias)}]}
        system = params.get("system")
        if system:
            body["systemInstruction"] = {"parts": [{"text": str(system)}]}
        gen: Dict[str, Any] = {}
        if params.get("json"):
            gen["responseMimeType"] = "application/json"
        if params.get("temperature") is not None:
            gen["temperature"] = float(params["temperature"])
        if params.get("max_tokens"):
            # Only ever set this deliberately: on a thinking model the cap is
            # shared with reasoning, and too low a value returns nothing at all.
            gen["maxOutputTokens"] = int(params["max_tokens"])
        budget = params.get("thinking_budget")
        if budget is not None:
            gen["thinkingConfig"] = {"thinkingBudget": int(budget)}
        aspect = params.get("aspect_ratio")
        if aspect:
            # NOT a top-level field. Omit it and every image comes back landscape.
            gen["imageConfig"] = {"aspectRatio": str(aspect)}
        if gen:
            body["generationConfig"] = gen
        return body

    # -- generate ------------------------------------------------------------
    def submit(self, kind, model, prompt, params=None, medias=None) -> GenResult:
        self.check(kind)
        params = dict(params or {})
        if kind == "speech":
            return self._speech(model, prompt, params)
        body = self.build_body(prompt, params, medias)
        payload = http_mod.request_json(
            "POST", f"{self.base}{API}/models/{model}:generateContent?key={self.api_key}",
            {}, body, timeout=600.0, http=self.http)
        text = _text_of(payload, model)
        return GenResult(kind=kind, backend=self.name, model=model,
                         status="completed", task_id=f"gemini-{id(payload):x}",
                         text=text, credits=None,
                         raw={"usage": payload.get("usageMetadata")})

    def poll(self, result: GenResult, timeout_s: float = 1200.0) -> GenResult:
        return result          # generateContent is synchronous

    # -- speech --------------------------------------------------------------
    def _speech(self, model: str, prompt: str, params: Dict[str, Any]) -> GenResult:
        out = params.get("out_path")
        if not out:
            # checked BEFORE the request: audio we cannot save is audio we paid
            # for and threw away
            raise GenError("gemini speech: params['out_path'] is required")
        voice = params.get("voice", "Kore")
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {"voiceConfig": {
                    "prebuiltVoiceConfig": {"voiceName": voice}}},
            },
        }
        payload = http_mod.request_json(
            "POST", f"{self.base}{API}/models/{model}:generateContent?key={self.api_key}",
            {}, body, timeout=600.0, http=self.http)
        blob = _inline_audio(payload, model)
        # headerless PCM -- without a container nothing will play it
        path = write_wav(out, base64.b64decode(blob["data"]),
                         rate=_rate_of(blob.get("mimeType", "")))
        return GenResult(kind="speech", backend=self.name, model=model,
                         status="completed", task_id=f"gemini-tts-{id(payload):x}",
                         files=[path], raw={"mime": blob.get("mimeType")})


# -- response helpers --------------------------------------------------------

def _text_of(payload: Dict[str, Any], model: str) -> str:
    candidates = payload.get("candidates") or []
    if not candidates:
        fb = (payload.get("promptFeedback") or {}).get("blockReason")
        if fb:
            raise ModerationRejected(f"gemini/{model} blocked the prompt: {fb}")
        raise GenError(f"gemini/{model} returned no candidates: "
                       f"{json.dumps(payload)[:300]}")
    cand = candidates[0]
    reason = str(cand.get("finishReason") or "").upper()
    if reason in _BLOCKED:
        raise ModerationRejected(f"gemini/{model} stopped: {reason}")
    parts = ((cand.get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts)
    if text.strip() and reason == "MAX_TOKENS":
        raise GenError(
            f"gemini/{model} was cut off at MAX_TOKENS after "
            f"{len(text)} characters. The answer is a fragment, not a short "
            f"answer -- raise max_tokens or pass thinking_budget=0.")
    if not text.strip():
        if reason == "MAX_TOKENS":
            raise GenError(
                f"gemini/{model} hit MAX_TOKENS before writing anything. On a "
                f"thinking model the cap is shared with reasoning, so it was "
                f"probably all spent thinking -- raise max_tokens, or pass "
                f"thinking_budget=0 for work that does not need it")
        raise GenError(f"gemini/{model} returned an empty answer "
                       f"(finishReason={reason or 'none'})")
    return text


def _inline_audio(payload: Dict[str, Any], model: str) -> Dict[str, str]:
    for cand in payload.get("candidates") or []:
        for part in ((cand.get("content") or {}).get("parts")) or []:
            blob = part.get("inlineData") or part.get("inline_data")
            if blob and blob.get("data"):
                return blob
    raise GenError(f"gemini/{model} returned no audio: {json.dumps(payload)[:300]}")


def _rate_of(mime: str) -> int:
    """`audio/L16;codec=pcm;rate=24000`"""
    m = re.search(r"rate=(\d+)", mime or "")
    return int(m.group(1)) if m else 24000


def write_wav(out_path: str, pcm: bytes, rate: int = 24000,
              channels: int = 1, width: int = 2) -> str:
    """Wrap headerless signed 16-bit PCM in a RIFF container."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    byte_rate = rate * channels * width
    header = (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
              + struct.pack("<IHHIIHH", 16, 1, channels, rate, byte_rate,
                            channels * width, width * 8)
              + b"data" + struct.pack("<I", len(pcm)))
    p.write_bytes(header + pcm)
    return str(p)
