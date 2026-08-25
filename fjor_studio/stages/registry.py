"""Maps each pipeline state to its handler."""
from __future__ import annotations

from typing import Callable, Dict

from . import steps

STAGES: Dict[str, Callable] = {
    "intake": steps.intake,
    "analysis": steps.analysis,
    "prompts": steps.prompts,
    "GATE_PLAN": steps.gate_plan,
    "plates": steps.plates,
    "GATE_PLATES": steps.gate_plates,
    "clips": steps.clips,
    "voiceovers": steps.voiceovers,
    "GATE_CLIPS": steps.gate_clips,
    "assembly": steps.assembly,
    "GATE_DRAFT": steps.gate_draft,
    "finalize": steps.finalize,
    "preflight": steps.preflight,
    "delivery": steps.delivery,
}


def all_stages() -> Dict[str, Callable]:
    return dict(STAGES)
