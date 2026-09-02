"""Keys arrive with the producer, not with the repository.

A kit is a JSON file of API keys that a producer supplies at runtime. The studio
reads it, holds it in the memory of one process, and never writes it anywhere.
Restart the process and the keys are gone with it.

WHY. `config/auth.yaml` works and is gitignored, but a file of live keys sitting
in the working tree is a permanent invitation: to a stray `git add -f`, to a
backup, to a screen share, to a traceback that interpolates the wrong object.
On 2026-09-02 one wrong argument in a throwaway script printed all six of this
studio's keys, because `Config` was a plain dataclass and its repr carried
`auth`. That repr is fixed -- and a key that is not on the disk cannot be
printed off it at all.

Their tool solved this the same way, from the other direction: it is a browser
app, so its keys live in localStorage and travel as an exported "kit" JSON that
the team imports. We read THAT FILE TOO, unchanged, because the team already has
one and passes it around -- see `_from_their_kit`.

Nothing here ever logs a value. `providers()` returns names.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

KIT_ENV = "FJOR_STUDIO_KIT"

# Their settings blob, and where the keys sit inside it.
_THEIR_BLOB = "creative_pipeline_v1"

# Providers this studio can route to. A kit may carry more -- theirs also holds
# replicate and volcengine -- and the extras are kept rather than dropped, so a
# kit stays one file for both tools.
KNOWN = ("kie", "fal", "gemini", "anthropic", "openai", "elevenlabs",
         "higgsfield")

# What a kit is allowed to carry besides keys. Anything else is ignored: a kit
# is credentials, not configuration, and a file that could also change the
# delivery root or the models would be a second config nobody is reading.
_EXTRA = {"kie": ("base_url", "upload_base")}


class KitError(Exception):
    pass


def _normalise(raw: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """`{provider: "key"}` or `{provider: {...}}` -> the shape `auth` uses."""
    out: Dict[str, Dict[str, Any]] = {}
    for name, value in (raw or {}).items():
        provider = str(name).strip().lower()
        if not provider:
            continue
        if isinstance(value, str):
            entry: Dict[str, Any] = {"api_key": value.strip()}
        elif isinstance(value, dict):
            entry = {"api_key": str(value.get("api_key") or "").strip()}
            for extra in _EXTRA.get(provider, ()):
                if value.get(extra):
                    entry[extra] = value[extra]
            if provider == "dashboard" and value.get("token"):
                entry = {"token": value["token"]}
        else:
            continue
        if any(str(v).strip() for v in entry.values()):
            out[provider] = entry
    return out


def _from_their_kit(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The colleague's browser export, read as-is.

    Their file is a dump of localStorage plus IndexedDB blobs; the keys are a
    JSON string inside a JSON object. We take only the keys and ignore the rest
    -- the style library and the CTA blobs mean nothing here."""
    blob = ((data.get("localStorage") or {}) or {}).get(_THEIR_BLOB)
    if not isinstance(blob, str):
        return None
    try:
        settings = json.loads(blob)
    except Exception as exc:  # noqa: BLE001
        raise KitError(f"the kit's settings blob is not JSON: {exc}")
    keys = (settings or {}).get("keys")
    if not isinstance(keys, dict):
        raise KitError("this looks like a settings-kit but carries no `keys`")
    return keys


def parse(data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Keys out of either shape. Raises rather than returning an empty kit,
    because "loaded, and it did nothing" is the failure this is meant to end."""
    if not isinstance(data, dict):
        raise KitError("a kit is a JSON object")
    theirs = _from_their_kit(data)
    raw = theirs if theirs is not None else data.get("keys", data)
    out = _normalise(raw if isinstance(raw, dict) else {})
    usable = [p for p in out if p in KNOWN]
    if not usable:
        raise KitError(
            "no usable API keys in this kit. Expected either "
            "{\"kie\": {\"api_key\": \"...\"}, ...} or the colleague's "
            "settings-kit export. Providers this studio routes to: "
            + ", ".join(KNOWN))
    return out


def read(path: Path) -> Dict[str, Dict[str, Any]]:
    path = Path(path).expanduser()
    if not path.is_file():
        raise KitError(f"no kit at {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise KitError(f"{path.name} is not readable JSON: {exc}")
    return parse(data)


# --- the keys this process is holding ---------------------------------------
# Deliberately a module global: it IS process-scoped state, and pretending
# otherwise by threading it through every call would only hide where it lives.
_SESSION: Optional[Dict[str, Dict[str, Any]]] = None
_SOURCE: str = ""


def use(keys: Dict[str, Dict[str, Any]], source: str = "kit") -> List[str]:
    global _SESSION, _SOURCE
    _SESSION, _SOURCE = dict(keys), source
    return providers()


def clear() -> None:
    global _SESSION, _SOURCE
    _SESSION, _SOURCE = None, ""


def current() -> Optional[Dict[str, Dict[str, Any]]]:
    """The kit in memory, or the one $FJOR_STUDIO_KIT points at."""
    if _SESSION is not None:
        return _SESSION
    env = os.environ.get(KIT_ENV, "").strip()
    if env:
        return read(Path(env))
    return None


def source() -> str:
    if _SESSION is not None:
        return _SOURCE
    return f"${KIT_ENV}" if os.environ.get(KIT_ENV, "").strip() else ""


def providers() -> List[str]:
    """Names only. A value never leaves this module."""
    return sorted(k for k, v in (_SESSION or {}).items()
                  if str(v.get("api_key") or "").strip())
