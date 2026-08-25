"""KIE, against a fake transport. Nothing here reaches the network."""
import json

import pytest

from fjor_studio.gen.base import (AuthRequired, GenError, GenResult,
                                  ModerationRejected, ProviderBusy)
from fjor_studio.gen.kie import MODELS, KieBackend


class FakeHttp:
    """Records requests and replays scripted responses."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, method, url, headers, json_body=None, data=None,
                 timeout=300.0, attempts=4):
        self.requests.append({"method": method, "url": url,
                              "headers": headers, "body": json_body})
        if not self.responses:
            raise AssertionError(f"unexpected request: {method} {url}")
        r = self.responses.pop(0)
        if isinstance(r, bytes):
            return 200, {}, r
        return 200, {}, json.dumps(r).encode()


def backend(*responses, **cfg):
    http = FakeHttp(*responses)
    cfg.setdefault("api_key", "test-key")
    cfg.setdefault("poll_interval", 0)
    return KieBackend(cfg, http=http), http


def ok(data):
    return {"code": 200, "msg": "success", "data": data}


def record(state, **extra):
    return ok(dict({"state": state}, **extra))


# -- the envelope trap -------------------------------------------------------

def test_a_422_arriving_as_http_200_is_not_a_success():
    """The single most expensive trap in this API."""
    b, _ = backend({"code": 422, "msg": "duration must be between 4 and 15",
                    "data": None})
    with pytest.raises(GenError, match="envelope code 422"):
        b.submit("video", "bytedance/seedance-2-fast", "p", {"duration": 5})


def test_a_401_envelope_becomes_an_auth_error():
    b, _ = backend({"code": 401, "msg": "invalid key"})
    with pytest.raises(AuthRequired):
        b.submit("video", "bytedance/seedance-2-fast", "p", {"duration": 5})


def test_a_missing_key_is_refused_before_any_request():
    with pytest.raises(GenError, match="needs auth.yaml kie.api_key"):
        KieBackend({})


# -- request bodies ----------------------------------------------------------

def test_seedance_r2v_uses_reference_image_urls():
    b, _ = backend()
    slug, body = b.build_input("bytedance/seedance-2-fast", "p",
                               {"duration": 6}, ["u1", "u2"])
    assert slug == "bytedance/seedance-2-fast"
    assert body["reference_image_urls"] == ["u1", "u2"]
    assert body["duration"] == 6
    assert body["nsfw_checker"] is False and body["web_search"] is False


def test_seedance_i2v_uses_a_single_first_frame_url():
    """A different field AND a single value, not a list of one."""
    b, _ = backend()
    _slug, body = b.build_input("bytedance/seedance-2-fast", "p",
                                {"duration": 5, "mode": "i2v"}, ["f1", "f2"])
    assert body["first_frame_url"] == "f1"
    assert "reference_image_urls" not in body


def test_gpt_image_2_splits_into_two_slugs():
    """KIE ships t2i and i2i as separate models under one name."""
    b, _ = backend()
    assert b.build_input("gpt-image-2", "p", None, [])[0] == "gpt-image-2-text-to-image"
    slug, body = b.build_input("gpt-image-2", "p", None, ["a"])
    assert slug == "gpt-image-2-image-to-image"
    assert body["input_urls"] == ["a"]


def test_banana_uses_image_input_and_defaults_to_1k():
    b, _ = backend()
    _slug, body = b.build_input("nano-banana-pro", "p", None, ["a"])
    assert body["image_input"] == ["a"]
    assert body["resolution"] == "1K" and body["output_format"] == "png"


def test_reference_images_are_capped_per_model():
    b, _ = backend()
    _s, body = b.build_input("bytedance/seedance-2-fast", "p", {"duration": 5},
                             [f"u{i}" for i in range(20)])
    assert len(body["reference_image_urls"]) == 9
    _s, body = b.build_input("nano-banana-pro", "p", None,
                             [f"u{i}" for i in range(20)])
    assert len(body["image_input"]) == 10


@pytest.mark.parametrize("bad", [3, 16, 0, 100])
def test_an_illegal_duration_is_refused_before_the_request(bad):
    """Caught locally: a rejected submission still costs a round trip, and the
    duration sweep that discovered these bounds cost 471 credits."""
    b, http = backend()
    with pytest.raises(GenError, match="outside the legal 4-15s"):
        b.build_input("bytedance/seedance-2-fast", "p", {"duration": bad})
    assert http.requests == []


@pytest.mark.parametrize("good", [4, 15])
def test_the_boundary_durations_are_legal(good):
    b, _ = backend()
    _s, body = b.build_input("bytedance/seedance-2-fast", "p", {"duration": good})
    assert body["duration"] == good


def test_a_model_of_the_wrong_kind_is_refused():
    b, _ = backend()
    with pytest.raises(GenError, match="makes image, not video"):
        b.submit("video", "nano-banana-pro", "p")


def test_every_model_spec_declares_a_real_kind():
    for name, spec in MODELS.items():
        assert spec.kind in ("image", "video"), name
        assert spec.slug, name
        if spec.image_field:
            assert spec.max_images > 0, name


# -- submit / poll -----------------------------------------------------------

def test_submit_returns_the_task_id_without_waiting():
    b, http = backend(ok({"taskId": "t-123"}))
    r = b.submit("video", "bytedance/seedance-2-fast", "p", {"duration": 5})
    assert r.status == "submitted" and r.task_id == "t-123"
    assert http.requests[0]["url"].endswith("/api/v1/jobs/createTask")
    assert http.requests[0]["body"]["model"] == "bytedance/seedance-2-fast"
    assert http.requests[0]["headers"]["Authorization"] == "Bearer test-key"


def test_submit_without_a_task_id_is_an_error():
    b, _ = backend(ok({"msg": "queued"}))
    with pytest.raises(GenError, match="no taskId"):
        b.submit("video", "bytedance/seedance-2-fast", "p", {"duration": 5})


def test_poll_reads_result_urls_out_of_the_json_string(tmp_path):
    """`resultJson` is a JSON *string*, not a nested object."""
    out = tmp_path / "clip.mp4"
    b, _ = backend(
        ok({"taskId": "t-1"}),
        record("generating"),
        record("success", creditsConsumed=124.0,
               resultJson=json.dumps({"resultUrls": ["https://cdn/x.mp4"]})),
        b"VIDEO-BYTES",
    )
    r = b.submit("video", "bytedance/seedance-2-fast", "p",
                 {"duration": 5, "out_path": str(out)})
    r = b.poll(r)
    assert r.status == "completed"
    assert r.urls == ["https://cdn/x.mp4"]
    assert r.credits == 124.0
    assert out.read_bytes() == b"VIDEO-BYTES"


def test_success_without_result_urls_is_an_error():
    b, _ = backend(ok({"taskId": "t-1"}), record("success", resultJson="{}"))
    r = b.submit("video", "bytedance/seedance-2-fast", "p", {"duration": 5})
    with pytest.raises(GenError, match="success with no resultUrls"):
        b.poll(r)


def test_a_moderation_refusal_is_its_own_error():
    """Final, not transient: the same prompt fails the same way, and a retry
    costs another submission."""
    b, _ = backend(ok({"taskId": "t-1"}),
                   record("fail", failMsg="Request flagged by content policy"))
    r = b.submit("video", "bytedance/seedance-2-fast", "p", {"duration": 5})
    with pytest.raises(ModerationRejected, match="content policy"):
        b.poll(r)


def test_an_ordinary_failure_is_not_a_moderation_error():
    b, _ = backend(ok({"taskId": "t-1"}), record("fail", failMsg="internal error"))
    r = b.submit("video", "bytedance/seedance-2-fast", "p", {"duration": 5})
    with pytest.raises(GenError) as exc:
        b.poll(r)
    assert not isinstance(exc.value, ModerationRejected)


def test_a_timeout_says_the_task_is_paid_for_and_collectable():
    """There is no cancel endpoint. The message must not suggest resubmitting."""
    b, _ = backend(ok({"taskId": "t-1"}), record("generating"))
    r = b.submit("video", "bytedance/seedance-2-fast", "p", {"duration": 5})
    with pytest.raises(ProviderBusy, match="collect it by id"):
        b.poll(r, timeout_s=-1)


# -- uploads -----------------------------------------------------------------

def test_a_local_file_is_uploaded_to_the_other_host(tmp_path):
    """Data URIs are refused by the API at every size; the upload host is a
    different hostname entirely."""
    plate = tmp_path / "plate.png"
    plate.write_bytes(b"PNGDATA")
    b, http = backend(ok({"downloadUrl": "https://cdn/plate.png"}),
                      ok({"taskId": "t-1"}))
    b.submit("video", "bytedance/seedance-2-fast", "p", {"duration": 5},
             medias=[str(plate)])
    up = http.requests[0]
    assert up["url"] == "https://kieai.redpandaai.co/api/file-base64-upload"
    assert up["body"]["base64Data"].startswith("data:image/png;base64,")
    assert up["body"]["fileName"] == "plate.png"
    assert http.requests[1]["body"]["input"]["reference_image_urls"] == \
        ["https://cdn/plate.png"]


def test_an_http_url_is_passed_through_without_uploading(tmp_path):
    b, http = backend(ok({"taskId": "t-1"}))
    b.submit("video", "bytedance/seedance-2-fast", "p", {"duration": 5},
             medias=["https://already/hosted.png"])
    assert len(http.requests) == 1          # no upload call


def test_the_same_file_is_uploaded_once(tmp_path):
    plate = tmp_path / "p.png"
    plate.write_bytes(b"X")
    b, http = backend(ok({"downloadUrl": "https://cdn/p.png"}),
                      ok({"taskId": "t-1"}), ok({"taskId": "t-2"}))
    for _ in range(2):
        b.submit("video", "bytedance/seedance-2-fast", "p", {"duration": 5},
                 medias=[str(plate)])
    uploads = [r for r in http.requests if "file-base64-upload" in r["url"]]
    assert len(uploads) == 1


def test_a_missing_file_fails_before_any_request(tmp_path):
    b, http = backend()
    with pytest.raises(GenError, match="no such file"):
        b.upload(str(tmp_path / "nope.png"))
    assert http.requests == []


def test_a_copyright_refusal_is_not_a_moderation_block():
    """Different animal: moderation refuses the prompt, this refuses the audio
    the model wrote. Reporting it as moderation sends a producer off rewriting
    the wrong thing."""
    b, _ = backend(ok({"taskId": "t-1"}),
                   record("fail", failMsg="The request failed because the output "
                                          "audio may be related to copyright "
                                          "restrictions."))
    r = b.submit("video", "bytedance/seedance-2-fast", "p", {"duration": 5})
    with pytest.raises(GenError) as exc:
        b.poll(r)
    assert not isinstance(exc.value, ModerationRejected)
    assert "audio" in str(exc.value)


def test_the_copyright_message_does_not_promise_a_retry_will_work():
    """Measured on BPW026: the same prompt was refused twice. Telling a producer
    to retry would have them spend on a shot that cannot pass as written."""
    b, _ = backend(ok({"taskId": "t-1"}),
                   record("fail", failMsg="output audio may be related to copyright"))
    r = b.submit("video", "bytedance/seedance-2-fast", "p", {"duration": 5})
    with pytest.raises(GenError) as exc:
        b.poll(r)
    text = str(exc.value)
    assert "does NOT clear it" in text
    assert "Name the audio explicitly" in text
