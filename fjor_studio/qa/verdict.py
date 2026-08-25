"""Parsing a media-QA verdict out of a vision model's reply.

Two distinctions here are load-bearing, and both were learned by burning credits
in the colleague's tool:

1. A verdict the model could not produce is NOT a verdict that the media is bad.
   A 503, a timeout or an unparseable reply means QA did not run; the clip is
   probably fine. Those become `technical=True`, which never triggers a paid
   regeneration and never blocks assembly.

2. `passed=False` is not automatically a reason to re-buy the shot. Whether it
   is depends on WHY, which is what `Verdict.issues` is for -- see policy.py.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

SEVERITIES = ("ok", "minor", "critical", "unclear", "error")

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.I)


@dataclass
class Verdict:
    passed: bool
    severity: str
    issues: List[str] = field(default_factory=list)
    summary: str = ""
    dialogue_match: str = "unclear"
    technical: bool = False        # QA failed to run; says nothing about the media
    speech_only: bool = False      # the only complaint is silence (see policy)
    model: str = ""
    raw: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def blocking(self) -> bool:
        """Should this verdict stop an unattended run from assembling?

        A technical error must not: it is a statement about the QA call, not the
        clip. A speech-only failure must not either: under an external voice
        track the clip is SUPPOSED to be silent."""
        return (not self.passed) and not self.technical and not self.speech_only


def technical_failure(reason: str, model: str = "") -> Verdict:
    return Verdict(
        passed=False, severity="error", technical=True, model=model,
        issues=[f"QA did not run: {reason}"],
        summary=("QA could not be performed (technical error). The media itself is "
                 "probably fine -- look at it, or re-run the check."))


def parse(reply: str, model: str = "") -> Verdict:
    """Turn a model reply into a Verdict.

    An unparseable reply is deliberately NOT a failure. Treating it as one meant
    an auto-regen loop paying for a clip again because a JSON fence moved."""
    text = (reply or "").strip()
    if not text:
        return technical_failure("empty reply", model)

    cleaned = _FENCE.sub("", text).strip()
    data: Optional[Dict[str, Any]] = None
    try:
        data = json.loads(cleaned)
    except Exception:
        # a fenced reply with prose around it: take the outermost {...}
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(cleaned[start:end + 1])
            except Exception:
                data = None

    if not isinstance(data, dict):
        return Verdict(
            passed=True, severity="unclear", model=model, raw=text[:2000],
            issues=["QA reply did not parse as JSON -- treated as passed"],
            summary=text[:200])

    severity = str(data.get("severity", "unclear")).strip().lower()
    if severity not in SEVERITIES:
        severity = "unclear"
    issues = [str(i) for i in (data.get("issues") or []) if str(i).strip()]
    # An explicit `passed` wins. Absent, infer it -- and note that `data.get(
    # "passed")` alone cannot be used, because a missing key and a literal false
    # are indistinguishable to a truthiness check.
    if "passed" in data:
        passed = bool(data["passed"])
    else:
        passed = severity in ("ok", "minor", "unclear")

    return Verdict(
        passed=passed,
        severity=severity,
        issues=issues,
        summary=str(data.get("summary", ""))[:1000],
        dialogue_match=str(data.get("dialogue_match", "unclear")).strip().lower(),
        model=model,
        raw=text[:2000],
    )
