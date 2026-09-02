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

    def __init__(self, specs: Dict[str, str], auth: Optional[Dict] = None):
        # LAZY. A key is needed to RUN a job, not to look at one -- and building
        # eagerly meant a studio with no keys could not be opened at all, so on
        # a fresh deploy the dashboard would not render, and the controls that
        # LOAD the keys and set the delivery folder were unreachable. The
        # protection that construction gave is not lost: `check_all` does it at
        # INTAKE, before anything is bought. Found by unpacking a shipped zip.
        self.specs = dict(specs)
        self._auth = dict(auth or {})
        self._built: Dict[str, Backend] = {}

    @property
    def routes(self) -> Dict[str, Backend]:
        """Every routed backend, constructed. Kept for callers that want them
        all; prefer `backend_for`, which builds only what it needs."""
        return {kind: self.backend_for(kind) for kind in self.specs}

    def capabilities(self) -> set:
        return set(self.specs)

    def backend_for(self, kind: str) -> Backend:
        name = self.specs.get(kind)
        if name is None:
            raise GenError(
                f"nothing is routed to '{kind}'. Set providers.{kind} in the "
                f"config, or stop asking for it.")
        if name not in self._built:
            if name not in _BUILDERS:
                raise GenError(
                    f"providers.{kind}: backend '{name}' is declared but not "
                    f"yet implemented (implemented: "
                    f"{', '.join(implemented()) or 'none'})")
            backend = _BUILDERS[name](self._auth.get(name) or {})
            # CAPABILITIES is the DECLARED map, checked before construction.
            # This checks what the backend actually IMPLEMENTS, which can lag
            # behind -- routing `image` to a backend whose image support is not
            # written would otherwise pass config validation and fail mid-run.
            if kind not in backend.capabilities():
                raise GenError(
                    f"providers.{kind}: backend '{name}' declares '{kind}' but "
                    f"its implementation does not serve it yet (it does: "
                    f"{', '.join(sorted(backend.capabilities()))})")
            self._built[name] = backend
        return self._built[name]

    def check_all(self) -> None:
        """Construct every routed backend, so a missing key or an unimplemented
        capability is found HERE rather than mid-run. Called at intake."""
        for kind in self.specs:
            self.backend_for(kind)

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

    return Router(merged, auth)
