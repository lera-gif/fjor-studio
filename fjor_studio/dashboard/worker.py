"""A single background worker that advances jobs.

One at a time, deliberately. A generation stage blocks for minutes on a
provider, and running several jobs concurrently would multiply the ways a
crash can strand a paid task id. The queue is the honest model of what this
tool does: a producer starts things, and they finish in order.
"""
from __future__ import annotations

import queue
import threading
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class Activity:
    job_id: str
    action: str
    state: str = "queued"          # queued | running | done | failed
    detail: str = ""
    started_at: str = ""
    finished_at: str = ""


class Worker:
    def __init__(self, run_fn: Callable[[str, str, Dict[str, Any]], None]):
        self._run = run_fn
        self._q: "queue.Queue" = queue.Queue()
        self._lock = threading.Lock()
        self._log: List[Activity] = []
        self._current: Optional[Activity] = None
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # -- public --------------------------------------------------------------
    def submit(self, job_id: str, action: str,
               payload: Optional[Dict[str, Any]] = None) -> Activity:
        act = Activity(job_id=job_id, action=action)
        with self._lock:
            self._log.append(act)
            if len(self._log) > 200:
                del self._log[:-200]
        self._q.put((act, payload or {}))
        return act

    def busy_with(self) -> Optional[str]:
        cur = self._current
        return cur.job_id if cur and cur.state == "running" else None

    def queued_for(self, job_id: str) -> bool:
        with self._lock:
            return any(a.job_id == job_id and a.state in ("queued", "running")
                       for a in self._log)

    def activity(self, limit: int = 30) -> List[Dict[str, Any]]:
        with self._lock:
            return [a.__dict__ for a in self._log[-limit:]][::-1]

    # -- internals -----------------------------------------------------------
    def _loop(self) -> None:
        from ..engine.job import utcnow
        while True:
            act, payload = self._q.get()
            act.state, act.started_at = "running", utcnow()
            self._current = act
            try:
                self._run(act.job_id, act.action, payload)
                act.state = "done"
            except Exception as exc:  # noqa: BLE001
                act.state = "failed"
                act.detail = f"{type(exc).__name__}: {exc}"
                traceback.print_exc()
            finally:
                act.finished_at = utcnow()
                self._current = None
                self._q.task_done()
