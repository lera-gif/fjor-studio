"""A finished job as the starting point for the next one.

Most variations change one thing. Re-running from scratch would re-analyse the
same reference, rewrite the same prompts and re-buy the same plates to arrive
at the same place -- so a derived job inherits everything up to the point where
it actually differs, and pays only for what comes after.

The cast travels whenever the prompts do. Whether the PORTRAITS travel with it
is `recast`: keeping them means the same person, dropping them means one new
person across every shot. Both are variations; five different women is not.

    from="assembly"  same clips, different cut         costs nothing
    from="clips"     same plates, new motion           costs clips
    from="plates"    same prompts, new plates          costs plates + clips
    from="prompts"   same analysis, rewritten          costs prompts + plates + clips

The inherited credits are recorded but NOT added to the child's ledger. The
ledger answers "what did this job spend", and the honest answer for a re-cut is
nothing; `meta.inherited` says what it was handed.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from .engine.job import Job, Scene
from .engine.store import JobStore

# What each starting point keeps. Ordered from cheapest to most expensive.
FROM_STAGES = ("assembly", "clips", "plates", "prompts")

_KEEPS = {
    "assembly": {"analysis", "prompts", "plates", "clips"},
    "clips": {"analysis", "prompts", "plates"},
    "plates": {"analysis", "prompts"},
    "prompts": {"analysis"},
}


class DeriveError(Exception):
    pass


def plan(source: Job, from_stage: str) -> Dict[str, Any]:
    """What a derivation would inherit and what it would re-buy. No side
    effects -- the dialog shows this before anything is created."""
    if from_stage not in FROM_STAGES:
        raise DeriveError(f"'{from_stage}' is not a starting point "
                          f"({', '.join(FROM_STAGES)})")
    keeps = _KEEPS[from_stage]
    scenes = source.scene_objs()
    return {
        "from": from_stage,
        "keeps": sorted(keeps),
        "scenes": len(scenes),
        "plates_kept": sum(1 for s in scenes if s.plate) if "plates" in keeps else 0,
        "clips_kept": sum(1 for s in scenes if s.clip) if "clips" in keeps else 0,
        "rebuys": [k for k in ("plates", "clips") if k not in keeps],
        "inherited_credits": round(source.spent, 1),
    }


def derive(store: JobStore, source_id: str, new_id: str, from_stage: str,
           intake_overrides: Optional[Dict[str, Any]] = None,
           note: str = "", recast: bool = False,
           cast_descriptions: Optional[Dict[str, str]] = None) -> Job:
    """`recast` decides WHO the variation stars, which is a separate question
    from whether it is consistent.

    Both answers are legitimate and the pipeline cannot guess between them: a
    second cut of the same creative wants the same host, and a new test of the
    same script usually wants a different one. What is never wanted is the third
    outcome -- a different face in every shot -- which is what happens when the
    cast does not travel at all.

    False: the parent's portraits come across, so it is the same person.
    True:  the descriptions come across and the portraits do not, so the shots
           are consistent with each other and with nobody else.
    `cast_descriptions` rewrites who a character is, which is how a variation
    gets a visibly different person rather than another draw of the same words.
    """
    if from_stage not in FROM_STAGES:
        raise DeriveError(f"'{from_stage}' is not a starting point "
                          f"({', '.join(FROM_STAGES)})")
    source = store.load(source_id)
    if not source.scenes:
        raise DeriveError(f"{source_id} has no plan to inherit")
    keeps = _KEEPS[from_stage]
    if "clips" in keeps and not all(s.get("clip") for s in source.scenes):
        raise DeriveError(
            f"{source_id} does not have a clip for every scene, so there is "
            f"nothing to re-cut -- derive from 'clips' instead")
    if "plates" in keeps and not all(s.get("plate") for s in source.scenes):
        raise DeriveError(f"{source_id} does not have a plate for every scene")

    intake = dict(source.intake)
    intake.pop("creative_name", None)
    intake.update({k: v for k, v in (intake_overrides or {}).items() if v is not None})
    intake["derived_from"] = source_id
    if note:
        # the note is what makes it a variation rather than a copy, so it goes
        # where the writer and the regenerators will actually read it
        intake["brief"] = ((intake.get("brief") or "") + "\n\n" + note).strip()

    job = store.create(new_id, intake, initial_state=from_stage)
    src_dir, dst_dir = store.job_dir(source_id), store.job_dir(new_id)

    # the reference always comes across: re-uploading the same file to make a
    # variation of it is the friction this exists to remove
    _copy_dir(src_dir / "ref", dst_dir / "ref")
    if "analysis" in keeps:
        _copy_dir(src_dir / "analysis", dst_dir / "analysis")
        job.analysis = dict(source.analysis)
    if "plates" in keeps:
        _copy_dir(src_dir / "plates", dst_dir / "plates")
    if "clips" in keeps:
        _copy_dir(src_dir / "clips", dst_dir / "clips")

    for raw in source.scenes:
        s = Scene(**raw)
        if "prompts" not in keeps:
            s.image_prompt = s.video_prompt = ""
        if "plates" not in keeps:
            s.plate, s.plate_attempts, s.plate_qa = None, 0, None
        if "clips" not in keeps:
            s.clip, s.clip_attempts, s.clip_qa = None, 0, None
        # submissions describe what the PARENT paid for; carrying them would
        # make the child look like it could collect generations it never made
        s.submissions = []
        job.put_scene(s)

    if "prompts" in keeps:
        job.plan = dict(source.plan)
        # The cast is part of the plan, so it travels with it. `scene.characters`
        # comes across with the prompts; without the cast beside it the child
        # names people it cannot anchor, `anchors_for` finds nothing, and every
        # plate invents a face again -- the exact failure the cast exists to
        # prevent (BLUEPRINT 3.4c). LME109, derived from LME108 at 'plates',
        # came back as five different women.
        #
        # The portraits come too, even when the scene plates do not: a portrait
        # is identity, not a shot. Re-buying the plates of a variation should
        # produce the SAME person, which is the whole point of deriving.
        job.cast = [dict(c) for c in source.cast]
        for member in job.cast:
            new_desc = (cast_descriptions or {}).get(member["id"])
            if new_desc:
                member["description"] = str(new_desc).strip()
            rel = member.get("plate")
            # recast, a rewritten description, or a portrait the parent has lost:
            # all three mean the face is bought again from the words. The
            # description travels regardless, so the child is never unanchored.
            if recast or new_desc or not rel or not (src_dir / rel).is_file():
                member["plate"], member["attempts"], member["qa"] = None, 0, None
                continue
            (dst_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_dir / rel, dst_dir / rel)
    for stage in ("ref", "analysis", "plates", "clips"):
        for path in sorted((dst_dir / stage).glob("*")):
            if path.is_file():
                job.add_artifact(stage, f"{stage}/{path.name}")

    job.meta["derived_from"] = source_id
    job.meta["derived_from_stage"] = from_stage
    job.meta["inherited"] = plan(source, from_stage)
    job.add_event("derived",
                  f"from {source_id}, starting at '{from_stage}' — inherits "
                  f"{', '.join(sorted(keeps))}"
                  + (f"; note: {note}" if note else ""))
    store.save(job)

    source.meta.setdefault("derivatives", []).append(new_id)
    source.add_event("derivative", f"{new_id} derived from this job at '{from_stage}'")
    store.save(source)
    return job


def _copy_dir(src: Path, dst: Path) -> None:
    if not src.is_dir():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.glob("*")):
        if path.is_file() and not path.name.startswith("."):
            shutil.copy2(path, dst / path.name)
