"""Configuration: three files under <home>/config/.

    pipeline.yaml   how the pipeline behaves (QA, gates, analysis depth)
    models.yaml     which backend and model serves each kind
    verticals.yaml  id prefix + delivery folder per vertical
    delivery.yaml   where finals land and what they are called
    auth.yaml       keys, if a machine keeps them on disk. Never committed,
                    never printed. A KIT supplied at runtime is preferred and
                    overrides it -- see `kit.py`.

`Config.redacted()` is the only representation that may be logged or shown.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

DEFAULT_PIPELINE: Dict[str, Any] = {
    "analysis": {"depth": "default", "ref_kind": "ugc"},
    "prompts": {"self_audit": True, "validation": True},
    "qa": {
        "enabled": True,
        "plates": {"enabled": True, "auto_regen": True, "max_attempts": 2},
        "clips": {"enabled": True, "auto_regen": False, "max_attempts": 1},
    },
    "gates": {"skip": []},
    "voice": {"source": "seedance"},   # seedance == the video model speaks
    "delivery": {"formats": ["9:16", "4:5"]},
}

DEFAULT_MODELS: Dict[str, Any] = {
    "providers": {"analysis": "mock", "text": "mock", "image": "mock",
                  "video": "mock", "speech": "mock"},
    "models": {"analysis": "gemini-3.1-pro-preview",
               "text": "claude-opus-4-8",
               "qa": "gemini-3-flash-preview",
               "image": "banana-pro",
               "video": "bytedance/seedance-2-fast",
               "speech": "eleven_multilingual_v2"},
}

# No default root, deliberately. There is no path that is right on someone
# else's machine, and a wrong one is worse than a missing one: finals are the
# end of a run that has already been paid for, so a plausible-looking default
# would scatter them somewhere nobody looks. Set `root` in delivery.yaml or
# $FJOR_STUDIO_DELIVERY_ROOT; intake refuses the job if neither is set.
DEFAULT_DELIVERY: Dict[str, Any] = {
    "root": "",
    "week_folder": "{week} week",
    "trash_subfolder": "_to_delete",
    "naming": {"channel": "fb", "type": "video", "source": "nano",
               "default_producer": "lp",
               "producers": ["lp", "ts", "am", "ag", "kk", "pl"]},
    "sizes": {"9:16": [1080, 1920], "4:5": [1080, 1350]},
    "export": {"crf": 21, "preset": "veryfast"},
}

_SECRET_HINTS = ("key", "token", "secret", "password")


class UnknownVertical(KeyError):
    pass


class MissingDeliveryRoot(RuntimeError):
    pass


def _deep_merge(base: Dict[str, Any], over: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return data


def _redact(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v) for v in value]
    if isinstance(value, str) and any(h in key.lower() for h in _SECRET_HINTS):
        if not value:
            return ""
        return f"{value[:3]}…{value[-2:]} ({len(value)} chars)"
    return value


@dataclass
class Config:
    home: Path
    pipeline: Dict[str, Any] = field(default_factory=dict)
    models: Dict[str, Any] = field(default_factory=dict)
    auth: Dict[str, Any] = field(default_factory=dict)
    verticals: Dict[str, Any] = field(default_factory=dict)
    delivery: Dict[str, Any] = field(default_factory=dict)
    lore: Dict[str, Any] = field(default_factory=dict)

    def __repr__(self) -> str:
        """Redacted, always, because a repr is not asked for -- it happens.

        The docstring at the top of this file has said since it was written that
        `redacted()` is the only representation that may be shown, and nothing
        enforced it: `Config` was a plain dataclass, so its generated repr
        carried every API key in `auth`. That is not a hypothetical leak. Any
        exception whose message interpolates a Config prints them; `job.error`
        is built by interpolating an exception, and it is stored in job.json and
        rendered on the dashboard. It took one wrong argument in a throwaway
        script to print the lot, on 2026-09-02.

        A secret that only stays secret while nobody makes a mistake is not
        kept, it is gambled."""
        return (f"Config(home={self.home!r}, "
                f"verticals={sorted((self.verticals or {}).get('verticals') or {})}, "
                f"auth=<redacted: {', '.join(sorted(self.auth or {}))}>)")

    @property
    def jobs_dir(self) -> Path:
        return self.home / "jobs"

    @property
    def assets_dir(self) -> Path:
        return Path(self.delivery.get("assets_dir") or (self.home / "assets"))

    @property
    def routing(self) -> Dict[str, str]:
        return dict(self.models.get("providers") or {})

    def model_for(self, kind: str) -> str:
        m = (self.models.get("models") or {}).get(kind)
        if not m:
            raise KeyError(f"models.yaml has no model for '{kind}'")
        return str(m)

    def vertical(self, name: str, strict: bool = True) -> Dict[str, Any]:
        """Look up a vertical's id prefix and delivery folder.

        `strict` is the whole point of the flag. Intake refuses an unknown
        vertical, because nothing has been paid for yet and a wrong folder is
        cheap to fix. Delivery does NOT: by then the creative is built,
        preflighted and paid for, and killing it over a config lookup would
        strand finished files."""
        entry = (self.verticals.get("verticals") or {}).get(name)
        if entry:
            return dict(entry)
        if strict:
            known = ", ".join(sorted((self.verticals.get("verticals") or {})))
            raise UnknownVertical(
                f"'{name}' is not in verticals.yaml (known: {known}). Add it "
                f"there -- its delivery folder must be an existing directory "
                f"under {self.delivery.get('root')}.")
        return {"prefix": "".join(c for c in name.upper() if c.isalpha())[:5] or "JOB",
                "folder": name}

    def vertical_for_prefix(self, prefix: str) -> Optional[str]:
        """Which vertical an id belongs to. `LIPIL025` -> lipedema_pilates.

        The prefix is the only part of a creative name that says what the ad is
        for, so pasting a name is enough to place it -- no separate picker."""
        want = str(prefix or "").strip().upper()
        for name, entry in (self.verticals.get("verticals") or {}).items():
            if str(entry.get("prefix", "")).upper() == want:
                return name
        return None

    @property
    def sizes(self) -> Dict[str, Any]:
        return dict(self.delivery.get("sizes") or {})

    @property
    def delivery_root(self) -> Path:
        root = str(self.delivery.get("root") or "").strip()
        if not root:
            raise MissingDeliveryRoot(
                "no delivery root is set, so there is nowhere to put a final. "
                "Set it at the top of the dashboard -- it is the folder that "
                "holds your vertical folders, and it can be anywhere. It can "
                "also be `root:` in config/delivery.yaml or the "
                "FJOR_STUDIO_DELIVERY_ROOT environment variable. This is "
                "checked at INTAKE, before anything is bought, because a run "
                "that discovers it at the end has already been paid for.")
        return Path(root).expanduser()

    def week_dir(self, vertical: str, week) -> Path:
        vert = self.vertical(vertical, strict=False)
        return (self.delivery_root / vert["folder"]
                / str(self.delivery["week_folder"]).format(week=int(week)))

    def redacted(self) -> Dict[str, Any]:
        """The ONLY form safe to print. The colleague's settings export carries
        live keys in plaintext; nothing here should ever repeat that."""
        return {"home": str(self.home), "pipeline": self.pipeline,
                "models": self.models, "verticals": self.verticals,
                "delivery": self.delivery, "auth": _redact(self.auth)}


def load(home: Optional[Path] = None) -> Config:
    home = Path(home or os.environ.get("FJOR_STUDIO_HOME") or Path.cwd())
    cfg_dir = home / "config"
    pipeline = _deep_merge(DEFAULT_PIPELINE, _read(cfg_dir / "pipeline.yaml"))
    models = _deep_merge(DEFAULT_MODELS, _read(cfg_dir / "models.yaml"))
    # Keys, in order of preference. A kit held by THIS PROCESS wins; then one
    # $FJOR_STUDIO_KIT points at; then auth.yaml, which still works and is what
    # this studio has always used, but is no longer what a new deployment is
    # told to do -- a file of live keys in the working tree is a standing
    # invitation, and `kit.py` says why at length.
    from . import kit as _kit
    auth = _read(cfg_dir / "auth.yaml")
    session = _kit.current()
    if session:
        # merged, not replaced: a kit carries keys, and auth.yaml may also hold
        # the dashboard token, which is not a provider credential
        auth = _deep_merge(auth, session)
    verticals = _read(cfg_dir / "verticals.yaml")
    lore = _read(cfg_dir / "lore.yaml")
    # Lore for a vertical nobody registered would never be read, and a silent
    # no-op is how a producer comes to believe a niche is configured when it is
    # not. The registry is the authority on what exists.
    stray = sorted(set((lore.get("lore") or {}))
                   - set((verticals.get("verticals") or {})))
    if stray:
        raise UnknownVertical(
            f"config/lore.yaml has lore for {', '.join(stray)}, which "
            f"verticals.yaml does not register -- so nothing would ever read "
            f"it. Register them, or remove the lore.")
    delivery = _deep_merge(DEFAULT_DELIVERY, _read(cfg_dir / "delivery.yaml"))
    # the env var wins: one checkout, several machines, no edit to a tracked file
    env_root = os.environ.get("FJOR_STUDIO_DELIVERY_ROOT")
    if env_root:
        delivery["root"] = env_root
    if os.environ.get("FJOR_STUDIO_BACKEND") == "mock":
        models["providers"] = {k: "mock" for k in models.get("providers", {})}
    return Config(home=home, pipeline=pipeline, models=models, auth=auth, lore=lore,
                  verticals=verticals, delivery=delivery)
