"""The narrow generation interface every backend implements.

Generation is deliberately TWO calls, not one:

    result = backend.submit(...)   # returns a task id; the money is now spent
    scene.record(...); store.save(job)
    result = backend.poll(result)  # may take 20 minutes, may crash

KIE has no cancel endpoint -- once `createTask` returns a taskId the credits are
committed whatever happens next. A single `generate()` that submits and waits
gives a crash nowhere to write the id down, and an unrecorded id is a paid
generation that can never be collected. `generate()` exists as a convenience for
backends and callers where that does not apply, but the pipeline uses the split.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

KINDS = ("analysis", "text", "image", "video", "speech")


class GenError(Exception):
    """Base for generation failures."""


class AuthRequired(GenError):
    """Missing or rejected credentials."""


class ModerationRejected(GenError):
    """The provider's moderation refused the framing. Surfaced to the producer
    with the reason -- never silently retried, because a retry of the same
    prompt costs money and fails the same way."""


class ProviderBusy(GenError):
    """Transient: rate limit, queue full, 5xx after retries."""


@dataclass
class GenResult:
    kind: str
    backend: str
    model: str
    status: str                       # submitted | running | completed | failed
    task_id: str = ""
    urls: List[str] = field(default_factory=list)
    files: List[str] = field(default_factory=list)   # local paths, once fetched
    text: str = ""                                   # for kind == analysis|text
    credits: Optional[float] = None                  # what was ACTUALLY charged
    notices: List[str] = field(default_factory=list)
    raw: Any = None

    @property
    def done(self) -> bool:
        return self.status in ("completed", "failed")

    @property
    def ok(self) -> bool:
        return self.status == "completed"


class Backend(ABC):
    """One provider. A backend declares which kinds it can serve; the registry
    refuses to route a kind the backend never claimed."""

    name: str = "backend"

    @abstractmethod
    def capabilities(self) -> set:
        """The subset of KINDS this backend can serve."""

    @abstractmethod
    def submit(self, kind: str, model: str, prompt: str,
               params: Optional[Dict[str, Any]] = None,
               medias: Optional[List[str]] = None) -> GenResult:
        """Start a generation. Returns as soon as an id exists. MAY have spent
        money already -- the caller must persist the result before polling."""

    @abstractmethod
    def poll(self, result: GenResult, timeout_s: float = 1200.0) -> GenResult:
        """Block, with backoff, until `result` is terminal."""

    def generate(self, kind: str, model: str, prompt: str,
                 params: Optional[Dict[str, Any]] = None,
                 medias: Optional[List[str]] = None,
                 timeout_s: float = 1200.0) -> GenResult:
        return self.poll(self.submit(kind, model, prompt, params, medias),
                         timeout_s=timeout_s)

    def check(self, kind: str) -> None:
        if kind not in KINDS:
            raise GenError(f"unknown kind '{kind}' (known: {', '.join(KINDS)})")
        if kind not in self.capabilities():
            raise GenError(
                f"backend '{self.name}' cannot serve '{kind}' "
                f"(it does: {', '.join(sorted(self.capabilities()))})")
