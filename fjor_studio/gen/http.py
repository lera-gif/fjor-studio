"""The shared HTTP helper for REST backends. Injectable, so tests never touch a
network.

The `envelope` function here exists because of one specific, expensive trap:
KIE answers HTTP 200 and puts the REAL status in a `code` field in the body. A
422 arrives looking exactly like a success, so any client that checks only the
HTTP status will happily treat a validation failure as a completed generation.
Every KIE response goes through `envelope`.
"""
from __future__ import annotations

import json as _json
import re
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple

from .base import AuthRequired, GenError, ProviderBusy

RETRYABLE = (429, 500, 502, 503, 504, 529)
USER_AGENT = "fjor-studio/0.1"

# Some APIs take their credential in the query string -- Gemini's `?key=` is the
# one we use. Every URL that reaches a log, an exception or job.json goes through
# `safe_url` first: an error message is not a private channel. It lands in the
# job's `error` field, in the event log, and on the producer's terminal.
_SECRET_PARAM = re.compile(
    r"(?i)([?&](?:key|api_?key|access_token|token|secret)=)([^&\s]+)")


def safe_url(url: str) -> str:
    return _SECRET_PARAM.sub(lambda m: f"{m.group(1)}<redacted>", str(url))

Http = Callable[..., Tuple[int, Dict[str, str], bytes]]


def request(method: str, url: str, headers: Dict[str, str],
            json: Optional[Dict[str, Any]] = None,
            data: Optional[bytes] = None,
            timeout: float = 300.0,
            attempts: int = 4) -> Tuple[int, Dict[str, str], bytes]:
    body = _json.dumps(json).encode("utf-8") if json is not None else data
    hdrs = dict(headers)
    hdrs.setdefault("User-Agent", USER_AGENT)
    if json is not None:
        hdrs.setdefault("Content-Type", "application/json")
    backoff = 3.0
    last: Optional[Exception] = None
    for attempt in range(attempts):
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return (resp.status,
                        {k.lower(): v for k, v in resp.headers.items()},
                        resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:400]
            if e.code in (401, 403):
                raise AuthRequired(f"{method} {safe_url(url)} -> HTTP {e.code}: {detail}")
            if e.code in RETRYABLE and attempt < attempts - 1:
                last = e
                time.sleep(backoff)
                backoff *= 2
                continue
            if e.code in RETRYABLE:
                raise ProviderBusy(f"{method} {safe_url(url)} -> HTTP {e.code}: {detail}")
            raise GenError(f"{method} {safe_url(url)} -> HTTP {e.code}: {detail}")
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            if attempt < attempts - 1:
                time.sleep(backoff)
                backoff *= 2
                continue
            raise ProviderBusy(f"{method} {safe_url(url)} failed after {attempts} attempts: {e}")
    raise GenError(f"{method} {safe_url(url)} failed: {last}")


def request_json(method: str, url: str, headers: Dict[str, str],
                 json: Optional[Dict[str, Any]] = None,
                 timeout: float = 300.0,
                 http: Optional[Http] = None) -> Dict[str, Any]:
    fn = http or request
    _status, _hdrs, raw = fn(method, url, headers, json, None, timeout)
    try:
        return _json.loads(raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise GenError(f"{safe_url(url)}: non-JSON response ({exc}): {raw[:200]!r}")


def envelope(payload: Dict[str, Any], url: str = "",
             ok_codes: Tuple[int, ...] = (200,)) -> Dict[str, Any]:
    """Unwrap a KIE-style `{code, msg, data}` body and return `data`.

    KIE returns HTTP 200 for errors and puts the real status in `code`, so a
    caller that trusts the HTTP status reads a 422 validation failure as a
    successful generation. Never bypass this for a "simple" KIE call.
    """
    url = safe_url(url)
    if not isinstance(payload, dict):
        raise GenError(f"{url}: expected a JSON object, got {type(payload).__name__}")
    if "code" not in payload:
        # Not an enveloped response. Returning it unchanged is right for
        # backends that do use HTTP status honestly.
        return payload
    code = payload.get("code")
    try:
        code_int = int(code)
    except (TypeError, ValueError):
        raise GenError(f"{url}: non-numeric envelope code {code!r}")
    if code_int in ok_codes:
        data = payload.get("data")
        return data if isinstance(data, dict) else {"data": data}
    msg = str(payload.get("msg") or payload.get("message") or "no message")
    if code_int in (401, 403):
        raise AuthRequired(f"{url}: envelope code {code_int}: {msg}")
    # ONLY 429 is retryable here, and deliberately not the 5xx range.
    #
    # An envelope code is an APPLICATION status that merely looks like an HTTP
    # one; transport-level 5xx is already retried in `request()`. Treating them
    # alike is not theoretical: KIE returns `code: 500` for plain validation
    # failures -- "This aspect_ratio is not within the range of allowed options"
    # (observed live, 2026-08-18) -- and it answers the SAME class of error with
    # 422 on seedance-2-fast and 500 on seedance-2-mini. Retrying those wastes
    # four round trips, and inside a poll loop it disguises a permanent failure
    # as a transient one.
    if code_int == 429:
        raise ProviderBusy(f"{url}: envelope code {code_int}: {msg}")
    raise GenError(f"{url}: envelope code {code_int}: {msg}")
