"""KIE — the aggregator that serves both images and video.

Everything here is written against `docs/PROVIDER_FACTS.md`. Four things about
this API cost money or a day to learn, and each has a named guard below:

1. **KIE answers HTTP 200 and puts the real status in `code`.** A 422 arrives
   looking like success. Every response goes through `http.envelope`.
2. **There is no cancel endpoint.** Once `createTask` returns a taskId the spend
   is committed, which is why `submit` and `poll` are separate calls.
3. **Images must be hosted.** Data URIs are refused at every size. They go to a
   *different host* first (`upload_base`), and come back as URLs.
4. **Every model names its reference-image field differently.** `image_input` vs
   `input_urls` vs `first_frame_url` vs `reference_image_urls` vs `image_urls`.
   That lives in MODELS below, not in a branch someone can miss.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import http as http_mod
from .base import (Backend, GenError, GenResult, ModerationRejected,
                   ProviderBusy)

API_PATH = "/api/v1"
UPLOAD_PATH = "/api/file-base64-upload"
DEFAULT_UPLOAD_DIR = "fjor-studio/refs"

_MODERATION = re.compile(
    r"polic|moderat|nsfw|sensitive|likeness|real.?people|flagged", re.I)

# A different animal to a moderation block. Seedance writes the audio itself, and
# sometimes what it writes trips a copyright filter -- so this is a refusal of
# one stochastic OUTPUT, not of the prompt. Re-rolling the same prompt often
# passes, which is exactly why it must not be reported as a permanent refusal.
_COPYRIGHT = re.compile(r"copyright", re.I)


@dataclass(frozen=True)
class ModelSpec:
    kind: str
    slug: str
    image_field: str = ""        # where reference images go, "" = takes none
    max_images: int = 0
    single_image: bool = False   # the field is one URL, not a list
    t2i_slug: str = ""           # slug to use when there are NO images
    defaults: Tuple[Tuple[str, Any], ...] = ()


# Slugs and field names read off the colleague's working calls, not from docs.
MODELS: Dict[str, ModelSpec] = {
    "nano-banana-pro": ModelSpec(
        "image", "nano-banana-pro", "image_input", 10,
        defaults=(("aspect_ratio", "9:16"), ("resolution", "1K"),
                  ("output_format", "png"))),
    # one name, two slugs: KIE splits t2i and i2i into separate models
    "gpt-image-2": ModelSpec(
        "image", "gpt-image-2-image-to-image", "input_urls", 8,
        t2i_slug="gpt-image-2-text-to-image",
        defaults=(("aspect_ratio", "9:16"),)),
    "bytedance/seedance-2-fast": ModelSpec(
        "video", "bytedance/seedance-2-fast", "reference_image_urls", 9,
        defaults=(("resolution", "720p"), ("aspect_ratio", "9:16"),
                  ("generate_audio", True), ("web_search", False),
                  ("nsfw_checker", False))),
    "bytedance/seedance-2-mini": ModelSpec(
        "video", "bytedance/seedance-2-mini", "reference_image_urls", 9,
        defaults=(("resolution", "720p"), ("aspect_ratio", "9:16"),
                  ("generate_audio", True), ("web_search", False),
                  ("nsfw_checker", False))),
    "bytedance/seedance-2": ModelSpec(
        "video", "bytedance/seedance-2", "reference_image_urls", 9,
        defaults=(("resolution", "1080p"), ("aspect_ratio", "9:16"),
                  ("generate_audio", True), ("web_search", False),
                  ("nsfw_checker", False))),
    "kling-3.0/video": ModelSpec(
        "video", "kling-3.0/video", "image_urls", 1, single_image=True,
        defaults=(("mode", "std"), ("sound", True))),
}

# Seedance i2v takes ONE start frame under a different key than r2v's list.
I2V_FIELD = "first_frame_url"

DURATION_MIN, DURATION_MAX = 4, 15


class KieBackend(Backend):
    name = "kie"

    def __init__(self, cfg: Optional[Dict[str, Any]] = None, http=None):
        cfg = cfg or {}
        self.api_key = cfg.get("api_key") or ""
        if not self.api_key:
            raise GenError("kie backend needs auth.yaml kie.api_key")
        self.base = str(cfg.get("base_url", "https://api.kie.ai")).rstrip("/")
        self.upload_base = str(
            cfg.get("upload_base", "https://kieai.redpandaai.co")).rstrip("/")
        self.upload_dir = cfg.get("upload_dir", DEFAULT_UPLOAD_DIR)
        self.poll_interval = float(cfg.get("poll_interval", 5.0))
        self.http = http or http_mod.request
        self._uploads: Dict[str, str] = {}   # local path -> hosted URL

    def capabilities(self) -> set:
        return {"image", "video"}

    # -- plumbing ------------------------------------------------------------
    @property
    def _headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def _call(self, method: str, url: str,
              body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = http_mod.request_json(method, url, self._headers, body,
                                        http=self.http)
        return http_mod.envelope(payload, url)

    def upload(self, path: str) -> str:
        """Host a local file and return its URL.

        A *different host* to the API, and the only way to get an image into a
        KIE generation at all -- data URIs are refused at every size. Results
        are cached per path so a regeneration does not re-upload the same plate."""
        if path in self._uploads:
            return self._uploads[path]
        p = Path(path)
        if not p.exists():
            raise GenError(f"kie upload: no such file: {p}")
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        data_url = f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()
        data = self._call("POST", f"{self.upload_base}{UPLOAD_PATH}", {
            "base64Data": data_url,
            "uploadPath": self.upload_dir,
            "fileName": p.name,
        })
        url = data.get("downloadUrl") or data.get("fileUrl")
        if not url:
            raise GenError(f"kie upload: no downloadUrl in response: "
                           f"{json.dumps(data)[:200]}")
        self._uploads[path] = url
        return url

    # -- submit --------------------------------------------------------------
    def build_input(self, model: str, prompt: str,
                    params: Optional[Dict[str, Any]] = None,
                    image_urls: Optional[List[str]] = None
                    ) -> Tuple[str, Dict[str, Any]]:
        """The request body, without sending it. Separated so a contract can be
        checked -- and a probe built -- without a submission."""
        spec = MODELS.get(model)
        if spec is None:
            raise GenError(f"kie: unknown model '{model}' "
                           f"(known: {', '.join(sorted(MODELS))})")
        params = dict(params or {})
        urls = list(image_urls or [])
        body: Dict[str, Any] = {"prompt": prompt}
        for k, v in spec.defaults:
            body[k] = v

        slug = spec.slug
        if not urls and spec.t2i_slug:
            slug = spec.t2i_slug          # KIE splits t2i and i2i into two models
        elif urls:
            if len(urls) > spec.max_images:
                urls = urls[:spec.max_images]
            field = spec.image_field
            if spec.kind == "video" and params.get("mode") == "i2v":
                field, urls = I2V_FIELD, urls[:1]
            body[field] = urls[0] if (spec.single_image or field == I2V_FIELD) else urls

        if spec.kind == "video":
            raw = params.get("duration", params.get("duration_s", 5))
            duration = int(round(float(raw)))
            if not DURATION_MIN <= duration <= DURATION_MAX:
                raise GenError(
                    f"kie: duration {duration}s is outside the legal "
                    f"{DURATION_MIN}-{DURATION_MAX}s -- the API would reject it, "
                    f"and a rejected submission still costs a round trip")
            body["duration"] = duration

        for key in ("aspect_ratio", "resolution", "output_format", "generate_audio",
                    "nsfw_checker", "web_search", "mode", "sound"):
            if key in params and key != "mode":
                body[key] = params[key]
        return slug, body

    def submit(self, kind, model, prompt, params=None, medias=None) -> GenResult:
        self.check(kind)
        spec = MODELS.get(model)
        if spec is None:
            raise GenError(f"kie: unknown model '{model}'")
        if spec.kind != kind:
            raise GenError(f"kie: model '{model}' makes {spec.kind}, not {kind}")
        urls = [self.upload(m) if not str(m).startswith(("http://", "https://"))
                else str(m) for m in (medias or [])]
        slug, body = self.build_input(model, prompt, params, urls)
        data = self._call("POST", f"{self.base}{API_PATH}/jobs/createTask",
                          {"model": slug, "input": body})
        task_id = data.get("taskId") or data.get("task_id")
        if not task_id:
            raise GenError(f"kie createTask returned no taskId: "
                           f"{json.dumps(data)[:200]}")
        return GenResult(kind=kind, backend=self.name, model=model,
                         status="submitted", task_id=str(task_id),
                         raw={"slug": slug, "input": body,
                              "params": dict(params or {})})

    # -- poll ----------------------------------------------------------------
    def record_info(self, task_id: str) -> Dict[str, Any]:
        return self._call(
            "GET", f"{self.base}{API_PATH}/jobs/recordInfo?taskId={task_id}")

    def poll(self, result: GenResult, timeout_s: float = 1200.0) -> GenResult:
        deadline = time.time() + timeout_s
        transient = 0
        while True:
            if time.time() > deadline:
                raise ProviderBusy(
                    f"kie: {result.task_id} still running after {timeout_s:.0f}s. "
                    f"It is PAID and still generating -- collect it by id rather "
                    f"than resubmitting.")
            try:
                st = self.record_info(result.task_id)
                transient = 0
            except ProviderBusy:
                transient += 1
                if transient >= 12:
                    raise ProviderBusy(
                        f"kie: 12 consecutive polling failures for "
                        f"{result.task_id}. The task is paid for and may still "
                        f"succeed -- collect it by id.")
                time.sleep(self.poll_interval)
                continue

            state = str(st.get("state") or "").lower()
            if state == "success":
                result.credits = _as_float(st.get("creditsConsumed"))
                result.urls = _result_urls(st)
                if not result.urls:
                    raise GenError(
                        f"kie: {result.task_id} reported success with no "
                        f"resultUrls: {str(st.get('resultJson'))[:200]}")
                out = (result.raw or {}).get("params", {}).get("out_path")
                if out:
                    result.files = [self.fetch(result.urls[0], out)]
                result.status = "completed"
                return result
            if state == "fail":
                msg = str(st.get("failMsg") or st.get("failCode") or "no detail")
                result.status = "failed"
                result.credits = _as_float(st.get("creditsConsumed"))
                if _COPYRIGHT.search(msg):
                    raise GenError(
                        f"kie: {result.task_id} was refused because the audio it "
                        f"generated may be copyrighted: {msg}\n"
                        f"Seedance writes the audio from the prompt, and a shot "
                        f"that leaves the soundtrack unspecified invites it to "
                        f"invent music -- which is what gets refused. Measured on "
                        f"BPW026: an on-camera studio line passed, while two "
                        f"outdoor voiceover shots were refused twice each. "
                        f"Retrying the same prompt does NOT clear it. Name the "
                        f"audio explicitly instead -- the voice plus specific "
                        f"ambience, and no music.")
                if _MODERATION.search(msg):
                    # final, not transient: the same prompt will fail the same
                    # way, and a retry costs another submission
                    raise ModerationRejected(f"kie moderation refused "
                                             f"{result.task_id}: {msg}")
                raise GenError(f"kie: {result.task_id} failed: {msg}")
            time.sleep(self.poll_interval)

    def fetch(self, url: str, out_path: str) -> str:
        _status, _hdrs, raw = self.http("GET", url, {}, None, None, 300.0)
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(raw)
        return str(p)


def _as_float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _result_urls(st: Dict[str, Any]) -> List[str]:
    """`resultJson` is a JSON *string*, not a nested object."""
    raw = st.get("resultJson")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except Exception:  # noqa: BLE001
            return []
    if not isinstance(raw, dict):
        return []
    urls = raw.get("resultUrls") or raw.get("resultUrl") or []
    return [urls] if isinstance(urls, str) else [str(u) for u in urls]
