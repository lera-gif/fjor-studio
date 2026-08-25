"""One directory per job under <home>/jobs/. Every mutation goes through
JobStore.save(), which writes atomically (temp file + os.replace), so a kill -9
can never leave a half-written job.json behind."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List

from .job import Job, utcnow

SUBDIRS = ("ref", "analysis", "plates", "clips", "audio", "draft", "finals", "review")


class StoreError(Exception):
    pass


class JobStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def exists(self, job_id: str) -> bool:
        return (self.job_dir(job_id) / "job.json").exists()

    def create(self, job_id: str, intake: Dict[str, Any],
               initial_state: str = "intake") -> Job:
        if self.exists(job_id):
            raise StoreError(f"job '{job_id}' already exists")
        jdir = self.job_dir(job_id)
        for sub in SUBDIRS:
            (jdir / sub).mkdir(parents=True, exist_ok=True)
        job = Job(id=job_id, state=initial_state, intake=dict(intake),
                  created_at=utcnow(), updated_at=utcnow())
        job.add_event("created", f"job created in state '{initial_state}'")
        self.save(job)
        return job

    def load(self, job_id: str) -> Job:
        path = self.job_dir(job_id) / "job.json"
        if not path.exists():
            raise StoreError(f"no such job: {job_id}")
        with open(path, "r", encoding="utf-8") as f:
            return Job(**json.load(f))

    def save(self, job: Job) -> None:
        job.updated_at = utcnow()
        jdir = self.job_dir(job.id)
        jdir.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(jdir), prefix=".job.", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(job), f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, str(jdir / "job.json"))
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def delete(self, job_id: str) -> Path:
        """Retire a job and free its creative id. Moved into `_deleted/`, never
        unlinked -- a mis-click costs nothing, and paid media stays recoverable."""
        src = self.job_dir(job_id)
        if not (src / "job.json").exists():
            raise StoreError(f"no such job: {job_id}")
        trash = self.root / "_deleted"
        trash.mkdir(parents=True, exist_ok=True)
        dest = trash / f"{job_id}_{int(time.time())}"
        shutil.move(str(src), str(dest))
        return dest

    def list_ids(self) -> List[str]:
        if not self.root.is_dir():
            return []
        return sorted(d.name for d in self.root.iterdir()
                      if d.is_dir() and not d.name.startswith("_")
                      and (d / "job.json").exists())

    def load_all(self) -> List[Job]:
        return [self.load(jid) for jid in self.list_ids()]
