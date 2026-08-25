"""Which backend serves which kind, and how one is built.

The capability map is the colleague's generation matrix written down. It is
declared separately from the builders so that a mis-route ("send speech to KIE")
fails at config time with a readable message, rather than at 2am inside a paid
run.

Only `mock` is implemented in this milestone. The rest are declared so the map,
the router and the config validation are real and tested now; each entry becomes
a builder as its backend lands.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .base import Backend, GenError, GenResult, KINDS

# backend -> kinds it can serve. Sources: the colleague's providerPreference
# matrix and their generate* function routing.
CAPABILITIES: Dict[str, set] = {
    "mock": set(KINDS),
    # aggregator, and the colleague's default for both images and video
    "kie": {"image", "video"},
    # the standing reserve for everything KIE does, plus an OpenRouter text route
    # that matters specifically when the Anthropic key is out of credit
    "fal": {"image", "video", "text"},
    "openai": {"image"},
    "gemini": {"analysis", "text", "image", "video", "speech"},
    "anthropic": {"text"},
    "elevenlabs": {"speech"},
    # Soul. Out of credits and never used by the colleague -- declared for
    # completeness, not because anything routes here.
    "higgsfield": {"image"},
}

Builder = Callable[[Dict[str, Any]], Backend]
_BUILDERS: Dict[str, Builder] = {}


def register(name: str, builder: Builder) -> None:
    if name not in CAPABILITIES:
        raise ValueError(f"'{name}' has no entry in CAPABILITIES -- declare what "
                         f"it can serve before registering a builder for it")
    _BUILDERS[name] = builder


def implemented() -> List[str]:
    return sorted(_BUILDERS)


class Router(Backend):
    """Presents many backends as one, routing by kind."""

    name = "router"

    def __init__(self, routes: Dict[str, Backend]):
        self.routes = routes

    def capabilities(self) -> set:
        return set(self.routes)

    def backend_for(self, kind: str) -> Backend:
        b = self.routes.get(kind)
        if b is None:
            raise GenError(
                f"nothing is routed to '{kind}'. Set providers.{kind} in the "
                f"config, or stop asking for it.")
        return b

    def submit(self, kind, model, prompt, params=None, medias=None) -> GenResult:
        return self.backend_for(kind).submit(kind, model, prompt, params, medias)

    def poll(self, result: GenResult, timeout_s: float = 1200.0) -> GenResult:
        return self.backend_for(result.kind).poll(result, timeout_s)


def validate_routing(routing: Dict[str, str]) -> None:
    """Fail loudly on a route that can never work."""
    for kind, backend in routing.items():
        if kind not in KINDS:
            raise ValueError(f"providers: '{kind}' is not a kind "
                             f"(kinds: {', '.join(KINDS)})")
        if backend is None:
            continue
        if backend not in CAPABILITIES:
            raise ValueError(f"providers.{kind}: unknown backend '{backend}' "
                             f"(known: {', '.join(sorted(CAPABILITIES))})")
        if kind not in CAPABILITIES[backend]:
            raise ValueError(
                f"providers.{kind}: backend '{backend}' cannot serve '{kind}' "
                f"(it does: {', '.join(sorted(CAPABILITIES[backend]))})")


def build(routing: Dict[str, str], auth: Optional[Dict[str, Any]] = None,
          overrides: Optional[Dict[str, str]] = None) -> Router:
    """`routing` is the config default; `overrides` is this job's picks.
    A value of `none` means "do not route this kind at all" -- which is a real
    setting, not an omission: when the video model renders speech with the
    picture, there is no speech backend to build."""
    auth = auth or {}
    merged = dict(routing)
    for kind, name in (overrides or {}).items():
        merged[kind] = None if str(name).strip().lower() in ("none", "off") else name
    merged = {k: v for k, v in merged.items() if v is not None}
    validate_routing(merged)

    built: Dict[str, Backend] = {}
    routes: Dict[str, Backend] = {}
    for kind, name in merged.items():
        if name not in _BUILDERS:
            raise GenError(
                f"providers.{kind}: backend '{name}' is declared but not yet "
                f"implemented (implemented: {', '.join(implemented()) or 'none'})")
        if name not in built:
            built[name] = _BUILDERS[name](auth.get(name) or {})
        backend = built[name]
        # CAPABILITIES is the DECLARED map, used to validate config before
        # anything is constructed. This checks what the backend actually
        # implements, which can lag behind -- routing `image` to a backend whose
        # image support is not written yet would otherwise pass config
        # validation and fail mid-run, after earlier stages had been paid for.
        if kind not in backend.capabilities():
            raise GenError(
                f"providers.{kind}: backend '{name}' declares '{kind}' but its "
                f"implementation does not serve it yet "
                f"(it does: {', '.join(sorted(backend.capabilities()))})")
        routes[kind] = backend
    return Router(routes)
