"""Cost forecasting, so a gate can show the producer real money before they
approve it.

The rates below are MEASURED, not quoted. Seedance on KIE bills per second of
output -- 4s cost 99.2 credits and 15s cost 372.0, exactly linear at 24.8/s at
720p. A flat per-clip estimate under-quoted a nine-scene job roughly five-fold,
which is the specific failure this module exists to prevent.

`creditsConsumed` on KIE's recordInfo is the truth. When a real run disagrees
with a rate here, change the rate -- do not average it away.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class Rate:
    """`per_second` bills by output duration; `per_call` bills flat."""
    backend: str
    model: str
    per_second: Optional[float] = None
    per_call: Optional[float] = None
    note: str = ""

    def credits(self, duration_s: float = 0.0) -> float:
        if self.per_second is not None:
            if duration_s <= 0:
                raise ValueError(
                    f"{self.backend}/{self.model} bills per second -- a forecast "
                    f"needs a duration, got {duration_s}")
            return round(self.per_second * float(duration_s), 4)
        if self.per_call is not None:
            return float(self.per_call)
        raise ValueError(f"{self.backend}/{self.model} has no rate set")


# Measured 2026-08-17 against live KIE. Re-measure before trusting after a
# provider reprice; every entry should be traceable to a real invoice line.
RATES: Dict[str, Rate] = {
    "kie/bytedance/seedance-2-fast": Rate(
        "kie", "bytedance/seedance-2-fast", per_second=24.8,
        note="720p; measured 4s->99.2, 15s->372.0, linear"),
    "kie/nano-banana-pro": Rate(
        "kie", "nano-banana-pro", per_call=18.0,
        note="1K; measured 2026-08-18 on LIPIL025, 5 plates at 18.0 each"),
    "kie/bytedance/seedance-2-mini": Rate(
        "kie", "bytedance/seedance-2-mini", per_second=24.8,
        note="UNVERIFIED -- assumed same as fast; measure before relying on it"),
    "kie/bytedance/seedance-2": Rate(
        "kie", "bytedance/seedance-2", per_second=24.8,
        note="UNVERIFIED -- 1080p tier, expected higher; measure"),
}

# The mock backend charges a schedule of its own (gen/mock.py `_credits`), and
# these mirror it EXACTLY. Pricing a dry run at them is therefore accurate --
# it predicts what the mock will actually charge -- not a guess dressed up as a
# forecast. They are keyed by kind, not model, for the same reason the mock is.
MOCK_RATES: Dict[str, Rate] = {
    "video": Rate("mock", "*", per_second=24.8, note="mirrors gen/mock.py"),
    "image": Rate("mock", "*", per_call=7.0, note="mirrors gen/mock.py"),
    "speech": Rate("mock", "*", per_call=1.0, note="mirrors gen/mock.py"),
}

# Anything not in RATES has no number we have actually seen. A forecast that
# silently invents one is worse than a forecast that says it does not know.
UNKNOWN = "unknown"


@dataclass
class LineItem:
    stage: str
    scene: Optional[int]
    backend: str
    model: str
    duration_s: float
    credits: Optional[float]     # None == we have no measured rate
    note: str = ""

    @property
    def known(self) -> bool:
        return self.credits is not None


@dataclass
class Forecast:
    items: List[LineItem]

    @property
    def total(self) -> float:
        return round(sum(i.credits for i in self.items if i.known), 2)

    @property
    def unknown_items(self) -> List[LineItem]:
        return [i for i in self.items if not i.known]

    @property
    def complete(self) -> bool:
        """False when any line has no measured rate. A gate must SAY this rather
        than present a partial total as if it were the price."""
        return not self.unknown_items

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "complete": self.complete,
            "unpriced": [f"{i.backend}/{i.model}" for i in self.unknown_items],
            "items": [i.__dict__ for i in self.items],
        }


def rate_for(backend: str, model: str,
             kind: str = "") -> Optional[Rate]:
    exact = RATES.get(f"{backend}/{model}")
    if exact is not None:
        return exact
    if backend == "mock" and kind:
        return MOCK_RATES.get(kind)
    return None


def line(stage: str, backend: str, model: str, duration_s: float = 0.0,
         scene: Optional[int] = None, kind: str = "") -> LineItem:
    r = rate_for(backend, model, kind)
    if r is None:
        return LineItem(stage, scene, backend, model, duration_s, None,
                        note="no measured rate")
    return LineItem(stage, scene, backend, model, duration_s,
                    r.credits(duration_s), note=r.note)


def forecast(lines: Iterable[LineItem]) -> Forecast:
    return Forecast(list(lines))
