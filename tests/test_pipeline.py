import pytest

from fjor_studio.engine import pipeline as p


def test_states_are_ordered_and_reachable():
    assert p.PIPELINE[0] == "intake"
    assert p.PIPELINE[-1] == "done"
    for a, b in zip(p.PIPELINE, p.PIPELINE[1:]):
        assert p.next_state(a) == b


def test_gates_sit_before_every_paid_stage():
    for stage in p.PAID_STAGES:
        before = p.PIPELINE[p.PIPELINE.index(stage) - 1]
        assert before in p.GATES, f"{stage} is not preceded by a gate ({before})"


def test_only_gate_plan_may_be_skipped():
    assert p.skippable_gates(["GATE_PLAN"]) == {"GATE_PLAN"}
    assert p.skippable_gates([]) == set()
    for locked in ("GATE_PLATES", "GATE_DRAFT"):
        with pytest.raises(p.PipelineError, match="cannot be skipped"):
            p.skippable_gates([locked])


def test_unknown_gate_in_skip_list_is_an_error():
    with pytest.raises(p.PipelineError, match="is not a gate"):
        p.skippable_gates(["GATE_NOPE"])


def test_every_revisable_target_is_a_real_stage():
    for gate, options in p.REVISABLE.items():
        assert gate in p.GATES
        for label, stage in options.items():
            assert stage in p.PIPELINE
            # a revision must rewind, never jump forward past its own gate
            assert p.PIPELINE.index(stage) < p.PIPELINE.index(gate)
