"""Cost forecasting. The failure this guards against is a flat per-clip estimate
under-quoting a job roughly five-fold at the gate where the producer says yes."""
import pytest

from fjor_studio import costs


def test_seedance_bills_per_second_and_is_linear():
    """Measured against live KIE: 4s -> 99.2, 15s -> 372.0."""
    r = costs.rate_for("kie", "bytedance/seedance-2-fast")
    assert r.credits(4) == pytest.approx(99.2)
    assert r.credits(15) == pytest.approx(372.0)
    assert r.credits(8) == pytest.approx(2 * r.credits(4))


def test_a_per_second_rate_refuses_to_price_a_missing_duration():
    r = costs.rate_for("kie", "bytedance/seedance-2-fast")
    with pytest.raises(ValueError, match="needs a duration"):
        r.credits(0)


def test_nine_scenes_at_five_seconds():
    lines = [costs.line("clips", "kie", "bytedance/seedance-2-fast", 5.0, i)
             for i in range(9)]
    f = costs.forecast(lines)
    assert f.total == pytest.approx(1116.0)   # 9 * 5 * 24.8
    assert f.complete is True


def test_an_unpriced_model_makes_the_forecast_incomplete():
    """A total that silently omits a line reads as the price. It must not."""
    lines = [costs.line("clips", "kie", "bytedance/seedance-2-fast", 5.0, 0),
             costs.line("clips", "fal", "some/unmeasured-model", 5.0, 1)]
    f = costs.forecast(lines)
    assert f.complete is False
    assert f.total == pytest.approx(124.0)    # only the line we can price
    assert [i.model for i in f.unknown_items] == ["some/unmeasured-model"]
    assert f.as_dict()["unpriced"] == ["fal/some/unmeasured-model"]


def test_unverified_rates_say_so():
    """Entries we assumed rather than measured must carry the warning, so a
    later reader does not mistake them for invoice-backed numbers."""
    for key in ("kie/bytedance/seedance-2-mini", "kie/bytedance/seedance-2"):
        assert "UNVERIFIED" in costs.RATES[key].note
