"""When a failed QA verdict is worth paying to fix.

A regenerated clip costs real money and often returns the SAME artifact, because
these failures are largely deterministic. So the bar for spending again is higher
than "QA said no".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

from .verdict import Verdict

# Complaints that amount to "nobody is speaking". Under an external voice track
# (ElevenLabs, or any separately-recorded VO) the clip is MEANT to be silent, so
# these are not defects -- they are the plan working.
_SPEECH_ONLY = re.compile(
    r"\b(no (speech|dialogue|audio|voice|sound)|silen(t|ce)|not? speaking|"
    r"does ?n[o']?t speak|mouth (stays |remains )?closed|no lip[- ]?sync|"
    r"lip[- ]?sync (is )?absent|no words|inaudible|says nothing|"
    r"dialogue (is )?missing|missing dialogue|no spoken|"
    # the phrasings the QA model actually uses for a shot whose line is spoken
    # separately: "Missing audio voiceover", "Missing voiceover dialogue",
    # "Audio dialogue is missing"
    r"missing (audio |voice ?over |voiceover )?(voice ?over|dialogue|audio|speech)|"
    r"(audio|voice ?over|voiceover|speech)( dialogue)? (is )?missing|"
    r"no voice ?over)\b", re.I)


@dataclass
class QaSettings:
    enabled: bool = True            # master switch for ALL media QA
    plates_enabled: bool = True
    plates_auto_regen: bool = True
    plates_max_attempts: int = 2    # plates are cheap; a re-roll usually helps
    clips_enabled: bool = True
    clips_auto_regen: bool = False  # clips are not; default to asking a human
    clips_max_attempts: int = 1

    @classmethod
    def from_config(cls, raw: Optional[dict]) -> "QaSettings":
        raw = raw or {}
        plates = raw.get("plates") or {}
        clips = raw.get("clips") or {}
        return cls(
            enabled=bool(raw.get("enabled", True)),
            plates_enabled=bool(plates.get("enabled", True)),
            plates_auto_regen=bool(plates.get("auto_regen", True)),
            plates_max_attempts=int(plates.get("max_attempts", 2)),
            clips_enabled=bool(clips.get("enabled", True)),
            clips_auto_regen=bool(clips.get("auto_regen", False)),
            clips_max_attempts=int(clips.get("max_attempts", 1)),
        )

    def runs_for(self, kind: str) -> bool:
        if not self.enabled:
            return False
        return self.plates_enabled if kind == "plate" else self.clips_enabled


def is_speech_only(verdict: Verdict) -> bool:
    """True when EVERY complaint is about the absence of speech.

    An empty issue list returns False on purpose. A verdict that failed while
    naming nothing is not evidence of a speech-only failure -- it is evidence
    that we do not know why it failed, and a guard that cannot see its inputs
    must not report all-clear.
    """
    if not verdict.issues:
        return False
    return all(_SPEECH_ONLY.search(issue) for issue in verdict.issues)


def regeneration_note(issues: List[str], silent_by_design: bool) -> str:
    """The QA findings, phrased as the note a regeneration is steered by.

    A verdict's issues are written for a producer; the note is read by the
    generator, appended to the approved prompt. Complaints about silence are
    dropped when the shot was MEANT to be silent -- its line is spoken
    separately -- because telling the video model "the voiceover is missing"
    is asking it to invent a soundtrack, which is what gets a generation
    refused (BPW026). Everything else is passed through as written: the QA
    model saw the frame and named what was wrong with it."""
    kept = [str(i).strip().rstrip(".") for i in (issues or []) if str(i).strip()]
    if silent_by_design:
        kept = [i for i in kept if not _SPEECH_ONLY.search(i)]
    if not kept:
        return ""
    return ("The previous attempt was rejected by QA for: "
            + "; ".join(kept) + ". Fix these and change nothing else.")


def apply_voice_context(verdict: Verdict, voice_is_external: bool) -> Verdict:
    """Mark a verdict whose only complaint is silence, when silence is intended.

    Without this, one such verdict under an external VO would both burn paid
    regenerations and block the whole unattended assembly."""
    if voice_is_external and not verdict.passed and is_speech_only(verdict):
        verdict.speech_only = True
    return verdict


def should_regenerate(verdict: Verdict, kind: str, attempts: int,
                      settings: QaSettings) -> bool:
    """`kind` is 'plate' or 'clip'; `attempts` is how many times it has been
    generated already (1 after the first generation)."""
    if kind not in ("plate", "clip"):
        raise ValueError(f"kind must be 'plate' or 'clip', got {kind!r}")
    if not settings.runs_for(kind):
        return False
    auto = settings.plates_auto_regen if kind == "plate" else settings.clips_auto_regen
    if not auto:
        return False
    cap = settings.plates_max_attempts if kind == "plate" else settings.clips_max_attempts
    if attempts >= cap:
        return False
    if verdict.passed:
        return False
    if verdict.technical:
        return False   # QA broke, not the media -- never pay for this
    if verdict.speech_only:
        return False   # the clip is silent because we asked it to be
    return verdict.severity == "critical"


def blocking_scenes(job_scenes: List[dict], field: str = "clip_qa") -> List[int]:
    """Scene indices whose QA should stop an unattended run. Reads the stored
    verdict dicts, so it sees exactly what the run recorded."""
    out: List[int] = []
    for raw in job_scenes:
        stored = raw.get(field)
        if not stored:
            continue
        v = Verdict(**{k: stored[k] for k in stored if k in Verdict.__dataclass_fields__})
        if v.blocking:
            out.append(raw["idx"])
    return out
