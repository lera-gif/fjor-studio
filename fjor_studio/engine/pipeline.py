"""The pipeline states, derived from the six steps of the colleague's tool.

Their UI steps map onto ours one-for-one; the gates are the two places their tool
already stops (`pauseBeforePhotos`, `pauseBeforeVideos`) plus a review of the cut:

    Step 1  Upload reference video     -> intake
    Step 2  Gemini analysis            -> analysis
    Step 3  Creative prompts           -> prompts
            (pauseBeforePhotos)        -> GATE_PLAN
    Step 4  Plates                     -> plates
            (pauseBeforeVideos)        -> GATE_PLATES
    Step 5  Image-to-video             -> clips
                                       -> GATE_CLIPS (the shots, before the cut)
    Step 6  Final assembly             -> assembly (the watermarked cut)
                                       -> GATE_DRAFT
                                       -> finalize (clean masters, both sizes)

Invariants:
- every transition appends an event and saves the job, so resume is load + run
- stages are re-runnable: a stage interrupted by a crash simply runs again
- GATE_PLATES and GATE_DRAFT are NEVER skipped, in any mode
"""
from __future__ import annotations

from typing import Dict, List

PIPELINE: List[str] = [
    "intake",
    "analysis",
    "prompts",
    "GATE_PLAN",
    "plates",
    "GATE_PLATES",
    "clips",
    "voiceovers",
    "GATE_CLIPS",
    "assembly",
    "GATE_DRAFT",
    "finalize",
    "preflight",
    "delivery",
    "done",
]

GATES = {"GATE_PLAN", "GATE_PLATES", "GATE_CLIPS", "GATE_DRAFT"}

# The gates a config may pass through without stopping. GATE_PLAN mirrors the
# colleague's `pauseBeforePhotos`, which they ship defaulting to OFF because
# plates are cheap. GATE_CLIPS is skippable because everything after it is free
# -- skipping it costs nothing but a look. The other two guard real money (the
# video spend) and the last chance to reject a cut, so no config can skip them
# -- see `skippable_gates()`, which raises rather than quietly honouring a bad
# config.
SKIPPABLE_GATES = {"GATE_PLAN", "GATE_CLIPS"}

TERMINAL = {"done", "failed", "cancelled"}
REVISE_PREFIX = "revising_"

# What a producer may ask to redo at each gate -> the stage the job rewinds to.
# The run then continues FORWARD through the later stages and stops at the same
# gate again, so a revision never skips a checkpoint it has not passed since.
REVISABLE: Dict[str, Dict[str, str]] = {
    "GATE_PLAN": {
        "analysis": "analysis",
        "plan": "analysis",
        "prompts": "prompts",
        "script": "prompts",
        "copy": "prompts",
    },
    "GATE_PLATES": {
        # Rewriting the words is a text call; only `plates` re-buys images.
        "prompts": "prompts",
        "script": "prompts",
        "copy": "prompts",
        "plates": "plates",
        "plate": "plates",
        "photos": "plates",
    },
    # Nothing after this gate has been built yet, so there is no assembly to
    # rewind to: a bad shot is a re-buy, and a shot that is merely unwanted is
    # dropped from the edit instead of regenerated.
    "GATE_CLIPS": {
        "clips": "clips",
        "clip": "clips",
        "animation": "clips",
        "motion": "clips",
        "voice": "voiceovers",
        "vo": "voiceovers",
    },
    # Everything here rewinds to a stage BEFORE the gate -- the draft is cut in
    # `assembly` and only then reviewed, so a caption fix is free (ffmpeg) while
    # a motion fix re-buys the clip.
    "GATE_DRAFT": {
        "clips": "clips",
        "clip": "clips",
        "animation": "clips",
        "motion": "clips",
        "voice": "voiceovers",
        "vo": "voiceovers",
        "assembly": "assembly",
        "draft": "assembly",
        "captions": "assembly",
        "subtitles": "assembly",
        "music": "assembly",
    },
}

# Stages that spend money. The gate immediately before each one has to forecast
# it, which is why they are named here rather than inferred from the ledger.
PAID_STAGES = {"plates", "clips"}


class PipelineError(Exception):
    pass


def next_state(state: str) -> str:
    try:
        return PIPELINE[PIPELINE.index(state) + 1]
    except (ValueError, IndexError):
        raise PipelineError(f"no state follows '{state}'")


def skippable_gates(configured: List[str]) -> set:
    """Validate a config's gate-skip list. Listing GATE_PLATES or GATE_DRAFT is a
    hard error, not a warning -- the whole point of those two is that no setting
    can turn them off, and a silently-ignored skip would read as if it worked."""
    out = set()
    for name in configured or []:
        name = str(name).strip().upper()
        if name not in GATES:
            raise PipelineError(f"gates.skip: '{name}' is not a gate "
                                f"(gates: {', '.join(sorted(GATES))})")
        if name not in SKIPPABLE_GATES:
            raise PipelineError(
                f"gates.skip: '{name}' cannot be skipped. Only "
                f"{', '.join(sorted(SKIPPABLE_GATES))} may be, because the others "
                f"guard the video spend and the last look at the cut.")
        out.add(name)
    return out
