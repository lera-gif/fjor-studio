"""Gemini, against a fake transport."""
import base64
import json
import struct

import pytest

from fjor_studio.gen.base import GenError, ModerationRejected, ProviderBusy
from fjor_studio.gen.gemini import GeminiBackend, write_wav


class FakeHttp:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, method, url, headers, json_body=None, data=None,
                 timeout=300.0, attempts=4):
        self.requests.append({"method": method, "url": url, "headers": headers,
                              "body": json_body, "data": data})
        if not self.responses:
            raise AssertionError(f"unexpected request: {method} {url}")
        r = self.responses.pop(0)
        if isinstance(r, tuple):                      # (headers, body)
            return 200, r[0], json.dumps(r[1]).encode()
        return 200, {}, json.dumps(r).encode()


def backend(*responses, **cfg):
    http = FakeHttp(*responses)
    cfg.setdefault("api_key", "test-key")
    cfg.setdefault("poll_interval", 0)
    return GeminiBackend(cfg, http=http), http


def reply(text, finish="STOP"):
    return {"candidates": [{"finishReason": finish,
                            "content": {"parts": [{"text": text}]}}],
            "usageMetadata": {"totalTokenCount": 10}}


# -- text and analysis -------------------------------------------------------

def test_text_generation_returns_the_joined_parts():
    b, http = backend({"candidates": [{"finishReason": "STOP", "content": {
        "parts": [{"text": "half "}, {"text": "and half"}]}}]})
    r = b.submit("text", "gemini-3-pro", "write something")
    assert r.text == "half and half"
    assert r.status == "completed"
    assert "gemini-3-pro:generateContent" in http.requests[0]["url"]
    assert "key=test-key" in http.requests[0]["url"]


def test_the_api_key_never_appears_in_a_request_body():
    b, http = backend(reply("x"))
    b.submit("text", "m", "p")
    assert "test-key" not in json.dumps(http.requests[0]["body"])


def test_a_system_instruction_is_its_own_field():
    b, http = backend(reply("ok"))
    b.submit("text", "m", "p", {"system": "you are a QA checker"})
    body = http.requests[0]["body"]
    assert body["systemInstruction"]["parts"][0]["text"] == "you are a QA checker"


def test_json_mode_sets_the_response_mime_type():
    b, http = backend(reply("{}"))
    b.submit("text", "m", "p", {"json": True})
    assert http.requests[0]["body"]["generationConfig"]["responseMimeType"] \
        == "application/json"


def test_aspect_ratio_is_nested_under_image_config():
    """A top-level aspectRatio is ignored and every image comes back landscape."""
    b, http = backend(reply("ok"))
    b.submit("text", "m", "p", {"aspect_ratio": "9:16"})
    gen = http.requests[0]["body"]["generationConfig"]
    assert gen["imageConfig"] == {"aspectRatio": "9:16"}
    assert "aspectRatio" not in gen


def test_an_image_is_sent_inline_and_before_the_question(tmp_path):
    plate = tmp_path / "plate.png"
    plate.write_bytes(b"PNGBYTES")
    b, http = backend(reply("looks fine"))
    b.submit("analysis", "m", "QA this plate", medias=[str(plate)])
    parts = http.requests[0]["body"]["contents"][0]["parts"]
    assert parts[0]["inlineData"]["mimeType"] == "image/png"
    assert base64.b64decode(parts[0]["inlineData"]["data"]) == b"PNGBYTES"
    assert parts[-1]["text"] == "QA this plate"


# -- the File API ------------------------------------------------------------

def test_a_video_goes_through_the_resumable_file_api(tmp_path):
    ref = tmp_path / "ref.mp4"
    ref.write_bytes(b"VIDEOBYTES")
    b, http = backend(
        ({"x-goog-upload-url": "https://upload/session/1"}, {}),
        {"file": {"uri": "https://files/abc", "name": "files/abc",
                  "mimeType": "video/mp4", "state": "ACTIVE"}},
        reply("a 3-shot testimonial"),
    )
    r = b.submit("analysis", "m", "analyse this", medias=[str(ref)])
    assert r.text == "a 3-shot testimonial"
    start = http.requests[0]
    assert start["headers"]["X-Goog-Upload-Command"] == "start"
    assert start["headers"]["X-Goog-Upload-Header-Content-Length"] == "10"
    assert http.requests[1]["url"] == "https://upload/session/1"
    assert http.requests[1]["data"] == b"VIDEOBYTES"
    parts = http.requests[2]["body"]["contents"][0]["parts"]
    assert parts[0]["fileData"] == {"mimeType": "video/mp4",
                                    "fileUri": "https://files/abc"}


def test_a_file_still_processing_is_waited_for(tmp_path):
    """Referencing a PROCESSING file fails the call, and the failure does not
    say why."""
    ref = tmp_path / "ref.mp4"
    ref.write_bytes(b"V")
    b, http = backend(
        ({"x-goog-upload-url": "https://upload/1"}, {}),
        {"file": {"uri": "https://files/a", "name": "files/a",
                  "mimeType": "video/mp4", "state": "PROCESSING"}},
        {"state": "PROCESSING", "mimeType": "video/mp4"},
        {"state": "ACTIVE", "mimeType": "video/mp4"},
        reply("done"),
    )
    assert b.submit("analysis", "m", "p", medias=[str(ref)]).text == "done"


def test_a_failed_upload_is_not_waited_on_forever(tmp_path):
    ref = tmp_path / "ref.mp4"
    ref.write_bytes(b"V")
    b, _ = backend(({"x-goog-upload-url": "https://u/1"}, {}),
                   {"file": {"uri": "u", "name": "files/a", "state": "FAILED"}})
    with pytest.raises(GenError, match="failed processing"):
        b.submit("analysis", "m", "p", medias=[str(ref)])


def test_a_missing_upload_url_is_reported_clearly(tmp_path):
    ref = tmp_path / "ref.mp4"
    ref.write_bytes(b"V")
    b, _ = backend(({}, {}))
    with pytest.raises(GenError, match="resumable handshake did not begin"):
        b.submit("analysis", "m", "p", medias=[str(ref)])


def test_the_same_video_is_uploaded_once(tmp_path):
    ref = tmp_path / "ref.mp4"
    ref.write_bytes(b"V")
    b, http = backend(
        ({"x-goog-upload-url": "https://u/1"}, {}),
        {"file": {"uri": "https://files/a", "name": "files/a",
                  "mimeType": "video/mp4", "state": "ACTIVE"}},
        reply("one"), reply("two"))
    b.submit("analysis", "m", "pass 1", medias=[str(ref)])
    b.submit("analysis", "m", "pass 2", medias=[str(ref)])
    handshakes = [r for r in http.requests
                  if r["headers"].get("X-Goog-Upload-Command") == "start"]
    assert len(handshakes) == 1                 # cached, not re-uploaded
    assert len(http.requests) == 4              # start, upload, and two prompts


# -- failure modes -----------------------------------------------------------

def test_a_safety_block_is_a_moderation_error_not_a_retry():
    b, _ = backend({"candidates": [{"finishReason": "SAFETY", "content": {}}]})
    with pytest.raises(ModerationRejected, match="SAFETY"):
        b.submit("text", "m", "p")


def test_a_blocked_prompt_is_a_moderation_error():
    b, _ = backend({"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}})
    with pytest.raises(ModerationRejected, match="PROHIBITED_CONTENT"):
        b.submit("text", "m", "p")


def test_hitting_max_tokens_with_no_text_says_so():
    b, _ = backend({"candidates": [{"finishReason": "MAX_TOKENS",
                                    "content": {"parts": []}}]})
    with pytest.raises(GenError, match="MAX_TOKENS"):
        b.submit("text", "m", "p")


def test_an_empty_answer_is_an_error_not_an_empty_string():
    b, _ = backend({"candidates": [{"finishReason": "STOP",
                                    "content": {"parts": [{"text": "  "}]}}]})
    with pytest.raises(GenError, match="empty answer"):
        b.submit("text", "m", "p")


# -- speech ------------------------------------------------------------------

def test_tts_wraps_headerless_pcm_into_a_wav(tmp_path):
    pcm = struct.pack("<8h", *range(8))
    b, _ = backend({"candidates": [{"content": {"parts": [{"inlineData": {
        "mimeType": "audio/L16;codec=pcm;rate=24000",
        "data": base64.b64encode(pcm).decode()}}]}}]})
    out = tmp_path / "vo.wav"
    r = b.submit("speech", "gemini-2.5-flash-preview-tts", "hello",
                 {"out_path": str(out)})
    raw = out.read_bytes()
    assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"
    assert struct.unpack("<I", raw[24:28])[0] == 24000       # sample rate
    assert raw[44:] == pcm
    assert r.files == [str(out)]


def test_the_sample_rate_is_read_off_the_mime_type(tmp_path):
    b, _ = backend({"candidates": [{"content": {"parts": [{"inlineData": {
        "mimeType": "audio/L16;codec=pcm;rate=16000",
        "data": base64.b64encode(b"\x00\x00").decode()}}]}}]})
    out = tmp_path / "vo.wav"
    b.submit("speech", "m", "hi", {"out_path": str(out)})
    assert struct.unpack("<I", out.read_bytes()[24:28])[0] == 16000


def test_tts_without_an_out_path_is_refused_before_the_request():
    """Audio we cannot save is audio we paid for and threw away."""
    b, http = backend()
    with pytest.raises(GenError, match="out_path"):
        b.submit("speech", "m", "hi")
    assert http.requests == []


def test_write_wav_produces_a_readable_header(tmp_path):
    import wave
    p = write_wav(str(tmp_path / "a.wav"), b"\x01\x00" * 100, rate=24000)
    with wave.open(p, "rb") as w:
        assert w.getframerate() == 24000
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getnframes() == 100


# -- capabilities ------------------------------------------------------------

def test_gemini_refuses_a_kind_it_does_not_implement():
    b, _ = backend()
    with pytest.raises(GenError, match="cannot serve 'video'"):
        b.submit("video", "m", "p")


# -- thinking budgets --------------------------------------------------------

def test_thinking_budget_is_nested_under_thinking_config():
    b, http = backend(reply("ok"))
    b.submit("text", "m", "p", {"thinking_budget": 0})
    gen = http.requests[0]["body"]["generationConfig"]
    assert gen["thinkingConfig"] == {"thinkingBudget": 0}


def test_max_tokens_is_not_set_unless_asked_for():
    """On a thinking model the cap is shared with reasoning: measured on
    gemini-3-flash-preview, a 300-token cap spent 286 thinking and returned a
    10-token fragment. A default cap would silently break every call."""
    b, http = backend(reply("ok"))
    b.submit("text", "m", "p")
    assert "maxOutputTokens" not in (
        http.requests[0]["body"].get("generationConfig") or {})


def test_a_truncated_answer_is_an_error_not_a_short_answer():
    """The fragment parses as text but never as the JSON the stage asked for."""
    b, _ = backend({"candidates": [{"finishReason": "MAX_TOKENS", "content": {
        "parts": [{"text": "Here is the JSON requested:\n```json"}]}}]})
    with pytest.raises(GenError, match="cut off at MAX_TOKENS"):
        b.submit("text", "m", "p")


def test_the_max_tokens_error_names_thinking_as_the_likely_cause():
    b, _ = backend({"candidates": [{"finishReason": "MAX_TOKENS",
                                    "content": {"parts": []}}]})
    with pytest.raises(GenError, match="thinking_budget=0"):
        b.submit("text", "m", "p")
