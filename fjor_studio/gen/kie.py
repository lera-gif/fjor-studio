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
    needs_driver: bool = False   # refuses to run without a driver video
    takes_duration: bool = True  # False: the driver decides how long it runs
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
    # 720p, like its siblings. Their tool shipped Pro, 2.5 and Motion Control
    # silently generating 1080p at roughly TWICE the price, and fixed it in
    # r170-r234 -- the final is assembled at 1080x1920 from a 720p source
    # either way, so the extra resolution bought nothing but the bill.
    "bytedance/seedance-2": ModelSpec(
        "video", "bytedance/seedance-2", "reference_image_urls", 9,
        defaults=(("resolution", "720p"), ("aspect_ratio", "9:16"),
                  ("generate_audio", True), ("web_search", False),
                  ("nsfw_checker", False))),
    "kling-3.0/video": ModelSpec(
        "video", "kling-3.0/video", "image_urls", 1, single_image=True,
        defaults=(("mode", "std"), ("sound", True))),
    # Motion Control: our photograph, someone else's movement. Both take EXACTLY
    # one image and one driver video (maxItems 1 on each), and `mode` is the
    # resolution, not a speed tier.
    # `input_urls` and `video_urls` are ARRAYS of exactly one (maxItems: 1), and
    # neither takes a duration: the clip runs as long as the driver does. That
    # is also why the engine is chosen before the prompts are written -- a 23s
    # driver stops being silently cut to 15s.
    "kling-3.0/motion-control": ModelSpec(
        "video", "kling-3.0/motion-control", "input_urls", 1,
        needs_driver=True, takes_duration=False,
        defaults=(("mode", "720p"), ("character_orientation", "video"))),
    "kling-2.6/motion-control": ModelSpec(
        "video", "kling-2.6/motion-control", "input_urls", 1,
        needs_driver=True, takes_duration=False,
        defaults=(("mode", "720p"), ("character_orientation", "video"))),
}

# KIE's Motion Control is a PROXY ONTO FAL -- their model page carries
# `"channel":"fal_request"` -- so fal's schema is what actually validates, and
# fal's limits are what actually reject. The colleague lost a live generation to
# each of these before the cause was found; every number here is theirs.
KLING_MC_IMG_MAX_BYTES = 10 * 1024 * 1024     # the base64 upload inflates by ~33%
KLING_MC_VID_MAX_BYTES = 100 * 1024 * 1024
KLING_MC_IMG_MAX_PX = 3850                    # fal: max width/height 3850
KLING_MC_IMG_MIN_SHORT_PX = 340               # strictly greater than
KLING_MC_VIDEO_SUFFIXES = {".mp4", ".mov"}

# Never send this to Motion Control. It exists in KIE's OpenAPI markdown and
# NOWHERE else -- not in fal's schema, not in Kling's own API, not in KIE's own
# playground -- and sending it created the task, passed validation, then died on
# execution with a faceless `Internal Error` AFTER the money was committed.
# Background is steered through the prompt instead, which is what Kling's own
# Motion Control guide recommends.
FORBIDDEN_MC_FIELDS = ("background_source",)

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

    # -- Motion Control preflight --------------------------------------------
    @staticmethod
    def motion_control_precheck(image: Path, driver: Path) -> None:
        """Refuse a Motion Control request that fal will reject anyway.

        Every one of these limits was learned from a live failure: KIE accepts
        the task, charges for it, and fal kills it on execution with a faceless
        `Internal Error`. Checked here, the answer costs nothing."""
        image, driver = Path(image), Path(driver)
        if not image.is_file():
            raise GenError(f"motion control: no character image at {image}")
        if not driver.is_file():
            raise GenError(f"motion control: no driver video at {driver}")
        if image.stat().st_size > KLING_MC_IMG_MAX_BYTES:
            raise GenError(
                f"motion control: the image is "
                f"{image.stat().st_size / 1048576:.1f} MB and the limit is 10 MB "
                f"(the base64 upload inflates it by a third again)")
        if driver.stat().st_size > KLING_MC_VID_MAX_BYTES:
            raise GenError(
                f"motion control: the driver is "
                f"{driver.stat().st_size / 1048576:.1f} MB and the limit is 100 MB "
                f"-- cut a shorter piece")
        if driver.suffix.lower() not in KLING_MC_VIDEO_SUFFIXES:
            raise GenError(
                f"motion control: the driver must be mp4 or mov, not "
                f"'{driver.suffix}'")
        try:
            from ..assemble import probe
            streams = [s for s in probe(image)["streams"] if s.get("width")]
            w, h = int(streams[0]["width"]), int(streams[0]["height"])
        except Exception as exc:  # noqa: BLE001
            raise GenError(f"motion control: could not measure {image.name}: {exc}")
        short, long = min(w, h), max(w, h)
        if short <= KLING_MC_IMG_MIN_SHORT_PX:
            raise GenError(
                f"motion control: the image's short side is {short}px and fal "
                f"needs more than {KLING_MC_IMG_MIN_SHORT_PX}px")
        if long > KLING_MC_IMG_MAX_PX:
            raise GenError(
                f"motion control: the image is {w}x{h} and fal caps either side "
                f"at {KLING_MC_IMG_MAX_PX}px -- this is undocumented at KIE and "
                f"arrives as 'Internal Error' after the charge")

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

        # -- a driver video, an end frame, or neither --------------------
        # These three shapes are mutually exclusive, and mixing them is a
        # GUARANTEED refusal rather than a worse result. Seedance takes:
        #   plain           first_frame_url
        #   reference       reference_image_urls
        #   with a driver   reference_image_urls + reference_video_urls
        #   morph           first_frame_url + last_frame_url, and nothing else
        driver = params.pop("driver_video_url", None)
        end_frame = params.pop("end_frame_url", None)
        if spec.needs_driver and not driver:
            raise GenError(
                f"kie: {model} is Motion Control -- it transfers movement from a "
                f"driver video and cannot run without one. Attach a driver, or "
                f"route this shot to a plain video model.")
        if driver and end_frame:
            raise GenError(
                "kie: a driver video and an end frame cannot go in one request. "
                "Motion transfer takes its movement from the driver; a morph "
                "takes its movement from the two frames. Pick one.")
        for forbidden in FORBIDDEN_MC_FIELDS:
            if forbidden in params:
                raise GenError(
                    f"kie: '{forbidden}' must never be sent to Motion Control. "
                    f"KIE proxies it onto fal, whose schema has no such field: "
                    f"the task is created, passes validation, and then dies on "
                    f"execution with 'Internal Error' -- after it has been paid "
                    f"for. Steer the background through the prompt.")
        if driver:
            if spec.slug.endswith("motion-control"):
                body["video_urls"] = [driver]
            else:
                body["reference_video_urls"] = [driver]
                # a driver forces the reference shape: first_frame_url beside
                # reference_video_urls is refused outright
                if "first_frame_url" in body:
                    body.pop("first_frame_url")
        if end_frame:
            first = urls[0] if urls else None
            if not first:
                raise GenError("kie: a morph needs a start frame as well as an end frame")
            body.pop(spec.image_field, None)
            body["first_frame_url"] = first
            body["last_frame_url"] = end_frame

        if spec.kind == "video" and spec.takes_duration:
            raw = params.get("duration", params.get("duration_s", 5))
            duration = int(round(float(raw)))
            if not DURATION_MIN <= duration <= DURATION_MAX:
                raise GenError(
                    f"kie: duration {duration}s is outside the legal "
                    f"{DURATION_MIN}-{DURATION_MAX}s -- the API would reject it, "
                    f"and a rejected submission still costs a round trip")
            body["duration"] = duration

        for key in ("aspect_ratio", "resolution", "output_format", "generate_audio",
                    "nsfw_checker", "web_search", "mode", "sound",
                    "character_orientation"):
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
        # A driver video and an end frame are uploaded like any other media, but
        # they are NOT reference images -- they name a different field, and
        # putting them in the image list is one of the refusals build_input
        # exists to prevent.
        params = dict(params or {})
        for local_key, url_key in (("driver_video", "driver_video_url"),
                                   ("end_frame", "end_frame_url")):
            local = params.pop(local_key, None)
            if local and not params.get(url_key):
                if spec.needs_driver and local_key == "driver_video" and medias:
                    self.motion_control_precheck(Path(medias[0]), Path(local))
                params[url_key] = (str(local)
                                   if str(local).startswith(("http://", "https://"))
                                   else self.upload(local))
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
