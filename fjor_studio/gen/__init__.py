from .base import (AuthRequired, Backend, GenError, GenResult, KINDS,
                   ModerationRejected, ProviderBusy)
from .elevenlabs import ElevenLabsBackend
from .gemini import GeminiBackend
from .kie import KieBackend
from .mock import MockBackend
from .registry import (CAPABILITIES, Router, build, implemented, register,
                       validate_routing)

register("mock", lambda cfg: MockBackend(cfg))
register("kie", lambda cfg: KieBackend(cfg))
register("gemini", lambda cfg: GeminiBackend(cfg))
register("elevenlabs", lambda cfg: ElevenLabsBackend(cfg))

__all__ = ["Backend", "GenResult", "GenError", "AuthRequired",
           "ModerationRejected", "ProviderBusy", "KINDS", "MockBackend",
           "KieBackend", "GeminiBackend", "CAPABILITIES", "Router", "build",
           "register", "implemented", "validate_routing"]
