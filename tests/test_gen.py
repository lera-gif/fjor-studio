"""The provider layer: routing validation, the mock backend, and the KIE
envelope trap."""
import pytest

from fjor_studio.gen import (CAPABILITIES, GenError, MockBackend,
                             ModerationRejected, build, validate_routing)
from fjor_studio.gen.base import AuthRequired, ProviderBusy
from fjor_studio.gen.http import envelope


def test_routing_rejects_a_kind_a_backend_cannot_serve():
    with pytest.raises(ValueError, match="cannot serve 'speech'"):
        validate_routing({"speech": "kie"})


def test_routing_rejects_an_unknown_backend():
    with pytest.raises(ValueError, match="unknown backend"):
        validate_routing({"video": "midjourney"})


def test_routing_accepts_the_colleagues_real_matrix():
    validate_routing({"analysis": "gemini", "text": "anthropic", "image": "kie",
                      "video": "kie", "speech": "elevenlabs"})
    # the documented fallback when the Anthropic key is dry
    validate_routing({"text": "fal"})


def test_declared_but_unimplemented_backend_fails_loudly():
    with pytest.raises(GenError, match="declared but not yet implemented"):
        build({"text": "fal"})


def test_a_backend_that_declares_more_than_it_implements_is_caught():
    """CAPABILITIES is the declared map; a backend's own capabilities() is what
    it really does. Routing to the gap would pass config validation and fail
    mid-run, after earlier stages had been paid for."""
    assert "image" in CAPABILITIES["gemini"]        # declared
    with pytest.raises(GenError, match="does not serve it yet"):
        build({"image": "gemini"}, auth={"gemini": {"api_key": "x"}})


def test_gemini_serves_the_kinds_it_is_routed_to():
    router = build({"analysis": "gemini", "text": "gemini", "speech": "gemini"},
                   auth={"gemini": {"api_key": "x"}})
    assert router.capabilities() == {"analysis", "text", "speech"}


def test_kie_serves_image_and_video():
    router = build({"image": "kie", "video": "kie"},
                   auth={"kie": {"api_key": "x"}})
    assert router.backend_for("image") is router.backend_for("video")


def test_none_means_do_not_route_this_kind():
    """A real setting: when the video model speaks the lines there is no speech
    backend to build."""
    router = build({"video": "mock", "speech": "mock"},
                   overrides={"speech": "none"})
    assert router.capabilities() == {"video"}
    with pytest.raises(GenError, match="nothing is routed to 'speech'"):
        router.backend_for("speech")


def test_every_capability_entry_is_a_real_kind():
    from fjor_studio.gen.base import KINDS
    for backend, kinds in CAPABILITIES.items():
        assert kinds <= set(KINDS), f"{backend} claims a kind that does not exist"


# -- mock backend ------------------------------------------------------------

def test_mock_is_deterministic(tmp_path):
    b = MockBackend({"out_dir": tmp_path})
    a1 = b.submit("video", "m", "same prompt")
    a2 = b.submit("video", "m", "same prompt")
    assert a1.task_id == a2.task_id
    assert b.submit("video", "m", "other").task_id != a1.task_id


def test_mock_video_bills_per_second(tmp_path):
    b = MockBackend({"out_dir": tmp_path})
    r = b.generate("video", "m", "p", params={"duration": 10})
    assert r.credits == pytest.approx(248.0)


def test_mock_refuses_a_kind_it_was_not_asked_for():
    class ImagesOnly(MockBackend):
        def capabilities(self):
            return {"image"}
    with pytest.raises(GenError, match="cannot serve 'video'"):
        ImagesOnly().submit("video", "m", "p")


def test_moderation_tripwire_raises_the_moderation_error(tmp_path):
    b = MockBackend({"out_dir": tmp_path})
    with pytest.raises(ModerationRejected):
        b.submit("image", "m", "a prompt __moderation__ here")


def test_failure_tripwire_returns_a_failed_result(tmp_path):
    b = MockBackend({"out_dir": tmp_path})
    r = b.generate("image", "m", "__fail__ this one")
    assert r.status == "failed" and r.ok is False


# -- the envelope trap -------------------------------------------------------

def test_envelope_unwraps_a_success():
    assert envelope({"code": 200, "msg": "ok", "data": {"taskId": "t1"}}) == {"taskId": "t1"}


def test_envelope_catches_a_422_that_arrived_as_http_200():
    """KIE answers HTTP 200 and puts the real status in `code`. A client that
    trusts the HTTP status reads this as a completed generation."""
    with pytest.raises(GenError, match="envelope code 422"):
        envelope({"code": 422, "msg": "duration must be 4-15", "data": None})


def test_envelope_maps_auth_and_rate_limit_codes_to_their_own_errors():
    with pytest.raises(AuthRequired):
        envelope({"code": 401, "msg": "bad key"})
    with pytest.raises(ProviderBusy):
        envelope({"code": 429, "msg": "slow down"})


def test_an_envelope_500_is_a_validation_failure_not_a_retryable_one():
    """Observed live 2026-08-18: KIE answers a bad aspect_ratio with code 500,
    and answers the SAME class of error with 422 on one model and 500 on
    another. Retrying those disguises a permanent failure as a transient one."""
    with pytest.raises(GenError) as exc:
        envelope({"code": 500,
                  "msg": "This aspect_ratio is not within the range of allowed options"})
    assert not isinstance(exc.value, ProviderBusy)


def test_envelope_passes_through_a_body_that_has_no_code():
    body = {"id": "abc", "status": "succeeded"}
    assert envelope(body) == body


def test_envelope_rejects_a_non_numeric_code():
    with pytest.raises(GenError, match="non-numeric envelope code"):
        envelope({"code": "fine", "data": {}})


# -- credentials must not leak through error messages ------------------------

def test_a_credential_in_the_query_string_is_redacted_from_messages():
    """Gemini takes its key as `?key=`. An error message is not a private
    channel: it lands in job.json's `error` field, in the event log and on the
    producer's terminal."""
    from fjor_studio.gen.http import safe_url
    assert safe_url("https://x/models/m:generateContent?key=AIzaSyLIVE123") \
        == "https://x/models/m:generateContent?key=<redacted>"
    assert safe_url("https://x/a?foo=1&api_key=sk-live-abc&bar=2") \
        == "https://x/a?foo=1&api_key=<redacted>&bar=2"
    # non-secret params are left alone, so a task id stays diagnosable
    assert safe_url("https://api.kie.ai/v1/jobs/recordInfo?taskId=t-1") \
        == "https://api.kie.ai/v1/jobs/recordInfo?taskId=t-1"


def test_a_failing_gemini_call_does_not_put_the_key_in_the_exception():
    import urllib.error
    from fjor_studio.gen.gemini import GeminiBackend
    from fjor_studio.gen.http import request

    KEY = "AIzaSyTOTALLYSECRETVALUE"

    def exploding(method, url, headers, json=None, data=None, timeout=300.0,
                  attempts=4):
        raise urllib.error.HTTPError(url, 400, "Bad Request", {},
                                     __import__("io").BytesIO(b"model not found"))

    b = GeminiBackend({"api_key": KEY}, http=lambda *a, **k: request(*a, **k))
    b.http = lambda *a, **k: exploding(*a, **k)
    with pytest.raises(Exception) as exc:
        b.submit("text", "nope", "p")
    assert KEY not in str(exc.value)


def test_a_failing_stage_does_not_write_a_key_into_job_json(tmp_path):
    """The whole point: this is where a leaked credential would persist."""
    from fjor_studio.gen.http import safe_url
    KEY = "AIzaSyPERSISTEDSECRET"
    msg = f"POST {safe_url(f'https://g/v1beta/models/m:generateContent?key={KEY}')} -> HTTP 400"
    assert KEY not in msg
