"""The one path through which money is spent.

Every paid generation goes through `run_generation`, which does, in order:

    1. submit          -- the credits are committed here
    2. record + save   -- the task id is on disk BEFORE anything can crash
    3. poll
    4. finish + save   -- actual credits charged, from the provider
    5. ledger

Step 2 is the whole point. KIE has no cancel endpoint, so an id we did not
persist is a paid generation we can neither collect nor account for. Nothing
else in this codebase may call `backend.submit` directly.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from ..engine.job import Job, Scene, Submission
from ..gen.base import GenError, GenResult, ProviderBusy


def find_existing(scene: Scene, kind: str, model: str) -> Optional[Dict[str, Any]]:
    """A submission for this kind/model that we already paid for and never
    resolved. On resume it is collected, not re-bought."""
    for s in scene.submissions:
        if s.get("kind") == kind and s.get("model") == model \
                and s.get("status") == "submitted":
            return s
    return None


def run_generation(ctx, scene, kind: str, model: str, prompt: str,
                   out_path: Path, params: Optional[Dict[str, Any]] = None,
                   medias: Optional[List[str]] = None,
                   stage: str = "", put=None, label: str = "") -> GenResult:
    """`scene` is anything that records submissions -- a Scene or a Character.
    Both buy plates, and both must persist a task id before waiting on it."""
    job: Job = ctx.job
    put = put or job.put_scene
    label = label or f"scene {getattr(scene, 'idx', getattr(scene, 'id', '?'))}"
    backend = ctx.providers.backend_for(kind)
    params = dict(params or {})
    params.setdefault("out_path", str(out_path))

    resumed = find_existing(scene, kind, model)
    if resumed:
        job.add_event("collecting", f"{label}: collecting an already-paid "
                                    f"{kind} generation ({resumed['task_id']})",
                      task_id=resumed["task_id"])
        result = GenResult(kind=kind, backend=resumed.get("backend", backend.name),
                           model=model, status="submitted",
                           task_id=resumed["task_id"],
                           raw={"prompt": prompt, "params": params,
                                "medias": list(medias or [])})
    else:
        result = backend.submit(kind, model, prompt, params, medias)
        scene.record(Submission(kind=kind, backend=result.backend, model=model,
                                task_id=result.task_id))
        put(scene)
        # persisted BEFORE the wait: a crash from here on loses no money
        ctx.store.save(job)

    try:
        result = backend.poll(result)
    except ProviderBusy as exc:
        # transient: the task is alive and still ours to collect
        scene.finish(result.task_id, "submitted", note=f"poll interrupted: {exc}")
        put(scene)
        ctx.store.save(job)
        raise
    except Exception as exc:  # noqa: BLE001
        # TERMINAL. The provider finished and refused. Leaving it "submitted"
        # made `find_existing` collect it on every retry, so the job could never
        # get past a refused generation -- it re-polled a corpse forever.
        scene.finish(result.task_id, "failed", note=str(exc)[:300])
        put(scene)
        ctx.store.save(job)
        raise

    if not result.ok:
        scene.finish(result.task_id, "failed",
                     credits=result.credits,
                     note="; ".join(result.notices) or "provider reported failure")
        put(scene)
        if result.credits:
            job.spend(stage or kind, f"{label} {kind} (failed)",
                      result.credits, result.backend, getattr(scene, "idx", None))
        ctx.store.save(job)
        raise GenError(f"{label}: {kind} generation failed "
                       f"({result.task_id}): {'; '.join(result.notices) or 'no detail'}")

    scene.finish(result.task_id, "completed", credits=result.credits,
                 url=(result.urls or [None])[0])
    put(scene)
    if result.credits:
        # the provider's own number, not our forecast -- these must be allowed
        # to disagree, and the ledger records what was actually charged
        job.spend(stage or kind, f"{label} {kind}", result.credits,
                  result.backend, getattr(scene, "idx", None))
    ctx.store.save(job)
    return result
