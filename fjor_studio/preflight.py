"""Preflight: the checks a final must pass before anyone sees it.

Every check reports whether it was ABLE TO LOOK, separately from whether it
passed. A check whose inputs make it structurally incapable of failing must not
report all-clear -- that failure mode has burned this pipeline's predecessor
repeatedly, and the message always read like evidence.
"""
from __future__ import annotations

from typing import Any, Dict, List


def _check(name: str, ok: bool, detail: str = "", looked: bool = True) -> Dict[str, Any]:
    return {"name": name, "ok": bool(ok), "looked": bool(looked), "detail": detail}


def run_checks(ctx) -> Dict[str, Any]:
    job = ctx.job
    checks: List[Dict[str, Any]] = []

    from .naming import parse as parse_final

    formats = list(((ctx.config.pipeline or {}).get("delivery") or {})
                   .get("formats", ["9:16"]))
    sizes = ctx.config.sizes
    on_disk = sorted(p.name for p in ctx.dir("finals").glob("*")
                     if p.name != "build_manifest.json")
    # A final is checked by the name the WEEK FOLDER will receive, not by an
    # internal one -- a file that will not parse there is a file nobody can find.
    parsed = {(int(d["w"]), int(d["h"])): name
              for name, d in ((n, parse_final(n)) for n in on_disk) if d}
    unparsed = [n for n in on_disk if not parse_final(n)]
    for fmt in formats:
        want = tuple(sizes.get(fmt) or ())
        if not want:
            checks.append(_check(f"final:{fmt}", False,
                                 f"no size configured for '{fmt}'", looked=False))
            continue
        checks.append(_check(
            f"final:{fmt}", want in parsed,
            f"looked for a {want[0]}x{want[1]} final; found "
            + (", ".join(on_disk) if on_disk else "nothing")))
    checks.append(_check("final filenames parse", not unparsed,
                         f"unparseable: {unparsed or 'none'}",
                         looked=bool(on_disk)))

    ids = {parse_final(n)["id"] for n in on_disk if parse_final(n)}
    checks.append(_check(
        "finals carry this job's id", ids in ({job.id}, set()),
        f"found {sorted(ids) or 'no ids'}; expected {job.id}",
        looked=bool(ids)))

    # QA that should stop delivery. `blocking` already excludes technical
    # failures and intended-silence verdicts.
    from .qa import blocking_scenes
    blocked = blocking_scenes(job.scenes, "clip_qa")
    judged = [s["idx"] for s in job.scenes if s.get("clip_qa")]
    checks.append(_check(
        "clip QA", not blocked,
        f"{len(judged)} of {len(job.scenes)} scenes have a verdict; "
        f"blocking: {blocked or 'none'}",
        looked=bool(judged)))

    missing = [s["idx"] for s in job.scenes if not s.get("clip")]
    checks.append(_check("every scene has a clip", not missing,
                         f"missing: {missing or 'none'}",
                         looked=bool(job.scenes)))

    unlooked = [c["name"] for c in checks if not c["looked"]]
    failed = [c["name"] for c in checks if not c["ok"]]
    return {
        "checks": checks,
        "failed": failed,
        # surfaced deliberately: a run where nothing failed but several checks
        # could not look is not the same as a clean run
        "could_not_look": unlooked,
        "clean": not failed and not unlooked,
    }
