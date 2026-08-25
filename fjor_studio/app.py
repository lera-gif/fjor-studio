"""Wiring. Everything that needs a working engine builds it here, so the CLI, a
future dashboard and the tests all get the same object graph."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from . import config as config_mod
from .config import Config
from .engine import Engine, JobStore
from .gen import build as build_providers
from .ids import delivered_ids, next_id
from .stages import all_stages


def open_studio(home: Optional[Path] = None,
                overrides: Optional[Dict[str, str]] = None
                ) -> Tuple[Config, JobStore, Engine]:
    cfg = config_mod.load(home)
    store = JobStore(cfg.jobs_dir)
    providers = build_providers(cfg.routing, cfg.auth, overrides)
    engine = Engine(store, cfg, all_stages(), providers=providers)
    return cfg, store, engine


def new_job(store: JobStore, config: Config, vertical: str,
            intake: Dict[str, Any], job_id: Optional[str] = None):
    """Intake is where an unknown vertical is refused -- nothing is paid for yet
    and a wrong delivery folder is cheap to fix here."""
    vert = config.vertical(vertical, strict=True)
    if job_id is None:
        taken = set(store.list_ids()) | delivered_ids(config.delivery.get("root"))
        job_id = next_id(vert["prefix"], taken)
    payload = dict(intake)
    payload.setdefault("vertical", vertical)
    payload.setdefault("folder", vert["folder"])
    return store.create(job_id, payload)
