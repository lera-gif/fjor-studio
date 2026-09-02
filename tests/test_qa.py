"""QA parsing and the regeneration policy -- the logic that decides whether to
spend money again."""
import json

import pytest

from fjor_studio.qa import (QaSettings, Verdict, apply_voice_context,
                            blocking_scenes, is_speech_only, parse,
                            should_regenerate, technical_failure)


def v(**kw):
    base = dict(passed=False, severity="critical", issues=["something"], summary="")
    base.update(kw)
    return Verdict(**base)


# -- parsing -----------------------------------------------------------------

def test_parses_plain_json():
    out = parse('{"passed": false, "severity": "critical", '
                '"issues": ["brand logo visible"], "summary": "Nike swoosh"}')
    assert out.passed is False
    assert out.severity == "critical"
    assert out.issues == ["brand logo visible"]
    assert out.technical is False


def test_parses_through_a_markdown_fence():
    out = parse('```json\n{"passed": true, "severity": "ok", "issues": []}\n```')
    assert out.passed is True and out.severity == "ok"


def test_parses_json_embedded_in_prose():
    out = parse('Here is my verdict:\n{"passed": false, "severity": "minor", '
                '"issues": ["hair flyaway"]}\nHope that helps.')
    assert out.severity == "minor" and out.issues == ["hair flyaway"]


def test_unparseable_reply_is_passed_not_failed():
    """An unparseable reply must never look like a defect -- treating it as one
    is what put the colleague's tool into a paid regeneration loop."""
    out = parse("the video looks fine to me honestly")
    assert out.passed is True
    assert out.severity == "unclear"
    assert out.technical is False


def test_empty_reply_is_a_technical_failure():
    out = parse("")
    assert out.technical is True and out.passed is False


def test_explicit_false_survives_a_truthiness_check():
    """A missing key and a literal false must not be confused."""
    with_key = parse('{"passed": false, "severity": "ok", "issues": []}')
    without = parse('{"severity": "ok", "issues": []}')
    assert with_key.passed is False
    assert without.passed is True


def test_unknown_severity_becomes_unclear():
    assert parse('{"passed": true, "severity": "catastrophic"}').severity == "unclear"


# -- the speech-only guard ---------------------------------------------------

@pytest.mark.parametrize("issue", [
    "The actor does not speak at all",
    "No dialogue is audible in the clip",
    "Mouth stays closed throughout",
    "there is no lip-sync",
    "Silence for the whole clip",
])
def test_speech_only_recognised(issue):
    assert is_speech_only(v(issues=[issue])) is True


def test_mixed_issues_are_not_speech_only():
    assert is_speech_only(v(issues=["No dialogue is audible",
                                    "A Nike logo is visible on the shirt"])) is False


def test_empty_issue_list_is_not_speech_only():
    """A verdict that failed while naming nothing is not evidence of anything.
    A guard that cannot see its inputs must not report all-clear."""
    assert is_speech_only(v(issues=[])) is False


def test_voice_context_only_applies_when_the_voice_is_external():
    silent = v(issues=["the actor does not speak"])
    assert apply_voice_context(silent, voice_is_external=False).speech_only is False
    assert apply_voice_context(silent, voice_is_external=True).speech_only is True


def test_speech_only_verdict_does_not_block():
    verdict = apply_voice_context(v(issues=["no speech at all"]), True)
    assert verdict.blocking is False


def test_technical_verdict_does_not_block():
    assert technical_failure("HTTP 503").blocking is False


def test_a_real_critical_verdict_blocks():
    assert v(issues=["a Nike swoosh is visible"]).blocking is True


# -- the regeneration policy -------------------------------------------------

DEFAULTS = QaSettings()


def test_critical_plate_regenerates_within_the_cap():
    assert should_regenerate(v(), "plate", attempts=1, settings=DEFAULTS) is True
    assert should_regenerate(v(), "plate", attempts=2, settings=DEFAULTS) is False


def test_clips_do_not_auto_regenerate_by_default():
    """A clip re-roll costs real money and often returns the same artifact."""
    assert should_regenerate(v(), "clip", attempts=1, settings=DEFAULTS) is False


def test_clips_regenerate_when_the_producer_turns_it_on():
    s = QaSettings(clips_auto_regen=True, clips_max_attempts=2)
    assert should_regenerate(v(), "clip", attempts=1, settings=s) is True


def test_a_technical_failure_never_costs_a_regeneration():
    s = QaSettings(clips_auto_regen=True, clips_max_attempts=3)
    assert should_regenerate(technical_failure("timeout"), "clip", 1, s) is False


def test_a_silent_clip_never_costs_a_regeneration():
    s = QaSettings(clips_auto_regen=True, clips_max_attempts=3)
    silent = apply_voice_context(v(issues=["no dialogue heard"]), True)
    assert should_regenerate(silent, "clip", 1, s) is False


def test_minor_issues_do_not_regenerate():
    s = QaSettings(clips_auto_regen=True, clips_max_attempts=3)
    assert should_regenerate(v(severity="minor"), "clip", 1, s) is False


def test_master_switch_stops_all_qa():
    s = QaSettings(enabled=False, plates_auto_regen=True)
    assert s.runs_for("plate") is False
    assert should_regenerate(v(), "plate", 1, s) is False


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        should_regenerate(v(), "audio", 1, DEFAULTS)


# -- reading verdicts back off a job -----------------------------------------

def test_blocking_scenes_reads_stored_verdicts():
    scenes = [
        {"idx": 0, "clip_qa": v(issues=["a Nike swoosh"]).as_dict()},
        {"idx": 1, "clip_qa": technical_failure("503").as_dict()},
        {"idx": 2, "clip_qa": Verdict(True, "ok").as_dict()},
        {"idx": 3, "clip_qa": None},
    ]
    assert blocking_scenes(scenes, "clip_qa") == [0]


def test_every_qa_prompt_asks_for_the_shape_the_parser_reads():
    """AW025's first live banner plate came back `unclear` -- the banner prompts
    asked for a `verdict` key and the parser reads `severity`, so the verdict was
    never read and passed silently. A check that cannot be understood is a check
    that cannot fail: rule 4, from a new direction."""
    import json as _json

    from fjor_studio.qa import parse
    from fjor_studio.qa.prompts import system_for

    for kind in ("plate", "clip"):
        for banner in (False, True):
            prompt = system_for(kind, banner=banner)
            assert '"severity"' in prompt, (kind, banner)
            assert '"passed"' in prompt, (kind, banner)
            assert '"verdict"' not in prompt, (kind, banner)
    # and the shape those prompts describe really does parse as critical
    verdict = parse(_json.dumps({"passed": False, "severity": "critical",
                                 "issues": ["a seam across the frame"],
                                 "summary": "the join is visible"}))
    assert verdict.severity == "critical" and verdict.passed is False
