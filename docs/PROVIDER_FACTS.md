# Provider facts

Verified against live APIs. Several of these cost credits to learn. Treat this as
the reference when a backend is implemented, and **update it when a real run
disagrees** rather than working around the discrepancy in code.

Source: the colleague's tool + kit export, and `fjor-video`'s own live spikes
(2026-08-17).

---

## KIE — the colleague's default aggregator

**Base:** `https://api.kie.ai` · **Upload host:** `https://kieai.redpandaai.co`
(a *different* host; same Bearer key)

### Seedance

- Slugs: `bytedance/seedance-2-fast` | `-mini` | `-2`
- Submit: `POST /api/v1/jobs/createTask`, body `{model, input}`
- `input` fields: `prompt` (**no truncation** — Seedance takes long prompts),
  `generate_audio`, `resolution` (`720p`; `1080p` on pro), `aspect_ratio`,
  `duration` **4–15 inclusive**, `web_search: false`, `nsfw_checker: false`
- Images: **`first_frame_url`** for i2v, **`reference_image_urls`** (≤9) for r2v
- Poll: `GET /api/v1/jobs/recordInfo?taskId=…`;
  states `waiting|queuing|generating → success|fail`
- The result URL is inside **`resultJson`, a JSON *string***, not a nested object

> The FAL path uses `image_urls` and a different slug format
> (`bytedance/seedance-2.0/fast`). **Do not mix the two conventions.**

### Confirmed model slugs (probed live 2026-08-18, nothing generated)

All seven exist; every probe was rejected at validation, so none created a task.

| slug | kind | reference-image field |
|---|---|---|
| `bytedance/seedance-2-fast` / `-mini` / `-2` | video | `reference_image_urls` (r2v, ≤9) or `first_frame_url` (i2v, one) |
| `kling-3.0/video` | video | `image_urls` (one) |
| `nano-banana-pro` | image | `image_input` (≤10) |
| `gpt-image-2-text-to-image` | image | — |
| `gpt-image-2-image-to-image` | image | `input_urls` (≤8) |

**Every model names that field differently.** In `gen/kie.py` this lives in the
`MODELS` table rather than a branch, because a branch is where it gets missed.
Note KIE ships gpt-image-2 as *two* models, chosen by whether refs are present.

### Four traps

1. **KIE answers HTTP 200 and puts the real status in a `code` field.** A 422
   arrives looking like success. Everything goes through
   `gen/http.py:envelope()`; never bypass it for a "simple" call.
2. **There is no cancel endpoint.** `/jobs/cancelTask` and `/jobs/cancel` both
   404. Once `createTask` returns a taskId the spend is committed. This is why
   `stages/paid.py` persists the id before polling.
3. **Images must be hosted, not inlined.** Data URIs are refused at every size.
   Upload first: `POST https://kieai.redpandaai.co/api/file-base64-upload`
   `{base64Data, uploadPath, fileName}` → `data.downloadUrl`. 401s without the
   Bearer key.
4. **An envelope `code: 500` is a validation failure, not a server error, and
   the codes are not consistent between models.** Observed live 2026-08-18: a
   bad `aspect_ratio` returns `code: 500` "This aspect_ratio is not within the
   range of allowed options", and the *same* out-of-range duration returns
   `422 Invalid duration` on `seedance-2-fast` but `500 Value must be within the
   specified range` on `-mini`. So `envelope()` retries **only 429** — an
   envelope code is an application status that merely resembles an HTTP one, and
   transport 5xx is already retried a layer below. Retrying these inside a poll
   loop disguises a permanent failure as a transient one.

### Pricing

**24.8 credits/second at 720p** on `seedance-2-fast`. Measured 4s → 99.2,
15s → 372.0 — exactly linear. `creditsConsumed` on `recordInfo` is the truth.
`-mini` and `-2` are **unverified**; `costs.py` says so in their notes.

---

## Gemini

- **The key goes in the URL (`?key=…`), so it must be stripped from every
  message.** Found the hard way 2026-08-18: an error message carrying the URL
  put the live key on the terminal, and would have written it into `job.json`'s
  `error` field and the event log. `gen/http.py:safe_url()` redacts
  `key|api_key|token|secret` params and is applied to every URL that reaches an
  exception.
- **Gemini 3 models think, and thinking tokens come out of `maxOutputTokens`.**
  Measured on `gemini-3-flash-preview`, 2026-08-18, same prompt:

  | setting | thinking | answer | result |
  |---|---|---|---|
  | `maxOutputTokens: 300` | 286 | 10 | `MAX_TOKENS`, a truncated fragment |
  | no cap | 179 | 25 | correct JSON |
  | `thinkingConfig.thinkingBudget: 0` | 0 | 25 | identical JSON, free |

  A small cap does not shorten the answer, it **replaces** it. `max_tokens` is
  therefore never set by default, and media QA runs with `thinking_budget: 0`.
- **Model availability, listed live 2026-08-18** (50 on this account):
  `gemini-3.1-pro-preview` ✓, `gemini-3-flash-preview` ✓,
  `gemini-3-pro-image-preview` ✓, `gemini-2.5-flash-preview-tts` ✓.
  **`gemini-3-pro-preview` does NOT exist** — the `3.1` is not optional.
- Image aspect ratio lives at `generationConfig.imageConfig.aspectRatio`; `9:16`
  and `4:5` are legal. **Omit it and you get landscape.**
- **Video must go through the File API**, a three-step resumable upload, and the
  file is unusable until its `state` reaches `ACTIVE`. Referencing one still in
  `PROCESSING` fails the call without saying why.
- Reference images go **inline** (`inlineData` parts). The colleague brackets
  character anchors with labelled text on *both* sides, downsizes to 1280px JPEG,
  and sends **at most 2**.
- Model matters for identity: Gemini 2.5 Flash Image has poor identity
  consistency (their note: *"отсюда плывущие лица"* — hence the drifting faces).
  They moved to **Gemini 3 Pro Image**.
- QA runs on **`gemini-3-flash-preview`**, ≈$0.005 per check.
- TTS (`gemini-2.5-flash-preview-tts`) returns **headerless PCM** — wrap to WAV.
  **No speech-rate control**; measured ~2.5 words/second.

---

## Others

- **FAL** `fal-ai/nano-banana-pro/edit` accepts up to **14** reference images.
- **FAL openrouter** routes Anthropic prompt calls (`anthropic/claude-opus-4.8`)
  when the Anthropic key is out of credit. Their `providerPreference.text` has
  `anthropic | fal | openai`, with **no Sonnet fallback on purpose** — a refusal
  should be loud rather than quietly served by a weaker model.
- **Replicate was removed entirely** from their tool; KIE covers its roles.
- **Higgsfield (Soul)** is out of credits and the colleague never used it.
- **ElevenLabs** key is out of quota. Speech is routed to Gemini TTS instead.
- **Keys**: the VIDEOTOOL kit export (2026-08-05) carries live plaintext keys
  for gemini, kie, fal, openai, anthropic, elevenlabs and replicate. `fal` is
  the one `fjor-video`'s auth.yaml does not have.

---

## Probing an API for free

A deliberately malformed POST proves endpoint, auth, model and body shape without
spending: a validation 422 is a successful probe.

**Keep the *same* field invalid in every request.** A duration sweep that included
the legal values 4 and 15 submitted two real generations and cost 471 credits.
The invalid field is the only thing between a probe and a paid job.

---

## Kling Motion Control on KIE (their r170–r234, ported 2026-08-31)

**KIE's Motion Control is a proxy onto fal.** Their model page carries
`"channel":"fal_request"` for both 3.0 and 2.6. This is the fact everything else
follows from: fal's schema is what validates, fal's limits are what reject, and
KIE's own documentation describes a contract that is not the one being enforced.

The failure mode is expensive and identical every time: **KIE accepts the task
and charges for it, then fal kills it on execution** and the poll returns
`state: fail`, `failMsg: "Internal Error"`. Nothing says which field was wrong.

- **`background_source` must never be sent.** It appears in KIE's OpenAPI
  markdown and nowhere else — not in fal's schema, not in Kling's own API, not
  in KIE's playground, not in their cURL example. A lone line of documentation
  with no executable contract behind it. Background is steered through the
  prompt, which is what Kling's Motion Control guide recommends anyway.
- **`input_urls` and `video_urls` are arrays of exactly one** (`maxItems: 1`).
- **No `duration`.** The clip runs as long as the driver does. This is why the
  engine is chosen before the prompts are written: a 23s driver is no longer
  silently cut to 15s.
- `mode` is the RESOLUTION (720p), not a speed tier. `character_orientation` is
  `video`.
- Limits, all fal's: image ≤ 10 MB and ≤ 3850px on the long side, short side
  **strictly greater** than 340px; driver ≤ 100 MB, mp4 or mov. The 3850px cap
  is undocumented at KIE entirely. `KieBackend.motion_control_precheck` checks
  every one of them before anything is submitted.
- The image goes up base64 (KIE recommends ≤10 MB, and the encoding inflates the
  body by a third); the driver goes up by the streaming endpoint.

## Seedance: three shapes, and they do not mix

Which fields are present IS the scenario. Mixing them is a guaranteed refusal,
not a degraded result:

| Scenario | Fields |
|---|---|
| plain | `first_frame_url` |
| reference | `reference_image_urls` |
| with a driver | `reference_image_urls` + `reference_video_urls` |
| morph | `first_frame_url` + `last_frame_url`, and neither of the others |

`first_frame_url` beside `reference_video_urls` is refused outright, so a driver
forces the reference shape. `duration` is clamped 4–15s.

