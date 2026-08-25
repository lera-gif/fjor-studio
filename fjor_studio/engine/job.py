"""The job record. `job.json` is the single source of truth for a run.

The unit of work is a Scene -- what the colleague's tool calls a GEN block. Each
scene carries its own prompts, its plate, its clip, its QA verdicts and, most
importantly, the provider task ids it has already paid for.

That last field is not bookkeeping. KIE has no cancel endpoint: the moment
`createTask` returns a taskId the credits are committed, so a taskId we fail to
write down is money we cannot get back and cannot collect the result of. Every
submission is recorded BEFORE we start waiting on it.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Submission:
    """One paid provider call. Written before the poll loop starts."""
    kind: str                 # image | video | speech
    backend: str              # kie | fal | gemini | ...
    model: str
    task_id: str
    submitted_at: str = field(default_factory=utcnow)
    status: str = "submitted"  # submitted | completed | failed | abandoned
    credits: Optional[float] = None
    url: Optional[str] = None
    note: str = ""


@dataclass
class Character:
    """Someone who appears in more than one shot.

    Their `plate` is an identity reference generated once and attached to every
    scene they are in. Without it each plate invents a new face from the same
    description, and scenes 0, 2 and 4 of a podcast ad come back as three
    different women wearing the same top."""
    id: str
    description: str = ""
    plate: Optional[str] = None
    attempts: int = 0
    qa: Optional[Dict[str, Any]] = None
    submissions: List[Dict[str, Any]] = field(default_factory=list)

    def record(self, sub: "Submission") -> "Submission":
        self.submissions.append(asdict(sub))
        return sub

    def finish(self, task_id: str, status: str, credits: Optional[float] = None,
               url: Optional[str] = None, note: str = "") -> None:
        for s in self.submissions:
            if s.get("task_id") == task_id:
                s["status"] = status
                if credits is not None:
                    s["credits"] = credits
                if url:
                    s["url"] = url
                if note:
                    s["note"] = note
                return
        raise KeyError(f"character {self.id}: no submission with task_id {task_id!r}")


@dataclass
class Scene:
    """A GEN block: one plate and the clip animated from it."""
    idx: int
    characters: List[str] = field(default_factory=list)
    # on_camera: the model renders the speech with the picture.
    # vo: a voice with no visible speaker -- generated SILENT, because asking
    #     for one makes the model invent a soundtrack and the whole generation
    #     gets refused for copyright (BPW026, refused three times).
    # silent: room tone only.
    voice: str = "on_camera"
    line: str = ""
    vo_track: Optional[str] = None
    image_prompt: str = ""
    video_prompt: str = ""
    duration_s: float = 5.0
    plate: Optional[str] = None       # job-relative path
    clip: Optional[str] = None
    plate_attempts: int = 0
    clip_attempts: int = 0
    plate_qa: Optional[Dict[str, Any]] = None
    clip_qa: Optional[Dict[str, Any]] = None
    submissions: List[Dict[str, Any]] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)

    def record(self, sub: Submission) -> Submission:
        self.submissions.append(asdict(sub))
        return sub

    def finish(self, task_id: str, status: str, credits: Optional[float] = None,
               url: Optional[str] = None, note: str = "") -> None:
        for s in self.submissions:
            if s.get("task_id") == task_id:
                s["status"] = status
                if credits is not None:
                    s["credits"] = credits
                if url:
                    s["url"] = url
                if note:
                    s["note"] = note
                return
        raise KeyError(f"scene {self.idx}: no submission with task_id {task_id!r}")

    @property
    def paid(self) -> float:
        return sum(float(s.get("credits") or 0.0) for s in self.submissions)


@dataclass
class Job:
    id: str
    state: str
    intake: Dict[str, Any]
    created_at: str
    updated_at: str
    scenes: List[Dict[str, Any]] = field(default_factory=list)
    cast: List[Dict[str, Any]] = field(default_factory=list)
    analysis: Dict[str, Any] = field(default_factory=dict)
    plan: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    ledger: List[Dict[str, Any]] = field(default_factory=list)
    artifacts: Dict[str, List[str]] = field(default_factory=dict)
    revisions: List[Dict[str, Any]] = field(default_factory=list)
    forecasts: Dict[str, Any] = field(default_factory=dict)
    meta: Dict[str, Any] = field(default_factory=dict)
    gate_ready: bool = False
    revise_return: Optional[str] = None
    error: Optional[str] = None

    # -- scenes --------------------------------------------------------------
    def scene(self, idx: int) -> Scene:
        for raw in self.scenes:
            if raw["idx"] == idx:
                return Scene(**raw)
        raise KeyError(f"job {self.id}: no scene {idx}")

    def scene_objs(self) -> List[Scene]:
        return [Scene(**raw) for raw in self.scenes]

    def put_scene(self, scene: Scene) -> None:
        raw = asdict(scene)
        for i, existing in enumerate(self.scenes):
            if existing["idx"] == scene.idx:
                self.scenes[i] = raw
                return
        self.scenes.append(raw)
        self.scenes.sort(key=lambda s: s["idx"])

    # -- cast ----------------------------------------------------------------
    def character(self, cid: str) -> Character:
        for raw in self.cast:
            if raw["id"] == cid:
                return Character(**raw)
        raise KeyError(f"job {self.id}: no character '{cid}'")

    def cast_objs(self) -> List[Character]:
        return [Character(**raw) for raw in self.cast]

    def put_character(self, ch: Character) -> None:
        raw = asdict(ch)
        for i, existing in enumerate(self.cast):
            if existing["id"] == ch.id:
                self.cast[i] = raw
                return
        self.cast.append(raw)

    def anchors_for(self, scene: "Scene", limit: int = 2) -> List[str]:
        """Identity plates for the people in this shot, most-specific first.

        Capped: two faces is what an image model can hold. Beyond that the
        references start competing and the result drifts toward an average of
        them."""
        out = []
        for cid in scene.characters:
            try:
                ch = self.character(cid)
            except KeyError:
                continue
            if ch.plate:
                out.append(ch.plate)
        return out[:limit]

    # -- log -----------------------------------------------------------------
    def add_event(self, kind: str, msg: str = "", **data: Any) -> None:
        ev: Dict[str, Any] = {"ts": utcnow(), "type": kind,
                              "state": self.state, "msg": msg}
        if data:
            ev["data"] = data
        self.events.append(ev)

    def add_artifact(self, stage: str, relpath: str) -> None:
        paths = self.artifacts.setdefault(stage, [])
        if relpath not in paths:
            paths.append(relpath)

    def spend(self, stage: str, item: str, credits: float,
              backend: str = "", scene: Optional[int] = None) -> None:
        """Every line is tagged with the backend that charged it, so cost can be
        read per provider without parsing the free-text item label."""
        self.ledger.append({"ts": utcnow(), "stage": stage, "item": item,
                            "credits": float(credits), "backend": backend,
                            "scene": scene})

    @property
    def spent(self) -> float:
        return sum(float(e["credits"]) for e in self.ledger)

    def spent_by_backend(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for e in self.ledger:
            out[e.get("backend") or "?"] = out.get(e.get("backend") or "?", 0.0) + float(e["credits"])
        return out

    def open_submissions(self) -> List[Dict[str, Any]]:
        """Paid calls we submitted and never resolved. On resume these are
        collected by id rather than re-bought."""
        out = []
        for raw in self.scenes:
            for s in raw.get("submissions", []):
                if s.get("status") == "submitted":
                    out.append(dict(s, scene=raw["idx"]))
        return out
