# fjor-studio

> **First run on a new machine?** Read [`docs/DEPLOY.md`](docs/DEPLOY.md) first.
> Nothing is configured out of the box: there is no delivery root and no keys,
> and the studio refuses to start a job rather than guess either.

The colleague's proven video-ad pipeline, behind a producer-facing job engine.

Their tool makes good ads and loses work: no job model, no resume, no ledger, no
cost accounting — close the tab mid-run and it is gone. This keeps the pipeline
and puts an engine under it: one directory per job, atomic state, crash-safe
resume, a ledger tagged per backend, and gates that show the money **before** you
approve it.

Clean-room rebuild. `fjor-video` is reference only and is not touched.

---

## Try it without spending anything

The mock backend walks the entire pipeline — every gate, every review file, every
forecast — for zero credits, and it is deterministic.

```bash
python3 -m venv .venv && ./.venv/bin/pip install pyyaml pytest
```

```bash
export FJOR_STUDIO_HOME="$PWD" && ./.venv/bin/python -m fjor_studio.cli new menopause_yoga ref.mp4 --week 34 --concept ugc --scenes 3 --run
```

Then approve your way through:

```bash
./.venv/bin/python -m fjor_studio.cli approve MENY072
```

## The dashboard

Double-click **`FJOR Studio.command`** to open it, or **`Restart FJOR Studio.command`**
to replace whatever is running with a fresh one. From a terminal:

```bash
./scripts/dashboard.sh --port 8422
```

It runs in the foreground and stops when you close the window. Starting it twice
is harmless — the second one notices the first and opens the browser instead.

"Notices" means it asks the running server a question, not just whether the port
answers: a server can hold the port and be unable to read its own config, and a
launcher that only pings the port would report all-clear and open a dashboard
where every action fails. If the one it finds cannot answer, it says why and
replaces it.

It binds to `127.0.0.1` and has no login. Serving it anywhere else requires
`FJOR_STUDIO_TOKEN`, and it refuses to start without one — every gate it shows
can be approved, and approving one spends credits. See
[`docs/DEPLOY.md`](docs/DEPLOY.md).

Start a job by pasting the creative name — it carries the id, week, concept and
producer, and suggests the vertical — picking the target vertical, dropping the
reference video, and writing a brief. Then: the stage track, plates and clips with their QA verdicts,
the draft player (scrubbable), the analysis and prompts the model wrote, and —
at every gate — what the next stage will cost **before** you approve it, with a
confirmation that names the amount. Revise any single scene with a note that steers the
regeneration. Jobs advance on one background queue, so nothing overlaps.

At **GATE_CLIPS** (the shots, before they are cut together) and again at
**GATE_DRAFT** (the cut itself) there is an editor: drag a shot to move it in the
running order, drag it to the tray to take it out of the cut (or drag it back
in), pick the music bed, set the subtitle colour and size or turn them off. Applying re-cuts the draft — ffmpeg only, nothing is bought
again. That is why the bed is no longer a question the brief asks: it is judged
against the cut, not imagined before it.

### Dubbing

**Dub** takes a finished creative — one of yours, produced anywhere — and ships
it in another language. This is a port of how the reference tool has done it for
a long time, not a redesign of it:

- the whole video is dubbed once, so the mix, the music and every transition
  survive exactly as approved;
- a blurred band covers the old burnt-in subtitles;
- new subtitles are burned from the dub's own word timings.

Because the video was produced elsewhere, nothing here knows where the old
subtitles sit — so you place the band, starting from their defaults (78% down,
15% tall). The still preview costs nothing and the dub does not, so check the
band actually covers the old line before pressing Dub. Strength 100 clears a
hard white-on-dark subtitle that the default 80 can leave as a faint ghost.

The dubbed file keeps the original's name plus a language token
(`…_w-34_l-es_s-1080x1350.mp4`), so the two sort together. Dubbing a file that
is already a dub is refused. If the dub comes back without a transcript, the cut
still gets the band but no new subtitles, and the dashboard says so rather than
shipping a silent-looking cut as if it were finished.

## Commands

| | |
|---|---|
| `new <vertical> <reference> --week N --concept C [--producer XX] [--run]` | create a job |
| `run <id>` | advance to the next gate (this is also *resume*) |
| `approve <id>` / `revise <id> <what> [--scene N]` | pass or bounce a gate |
| `retry <id>` | resume a failed job from the stage that errored |
| `waive <id> --scene N --note "why"` | ship a scene whose QA verdict blocks it — the verdict stays, the reason travels into the manifest |
| `reassemble <id>` | re-cut from existing clips — costs nothing |
| `derive <id> <name> [--from assembly\|clips\|plates\|prompts]` | a variation of a finished job |
| `status <id>` / `list` | look |
| `config` | the resolved config, keys redacted |

## Layout

```
config/pipeline.yaml   QA, gates, analysis depth, delivery formats
config/models.yaml     which backend + model serves each kind
config/auth.yaml       keys — gitignored, never printed unredacted
jobs/<ID>/job.json     the single source of truth for a run
jobs/<ID>/review/      what the producer sees at each gate
config/verticals.yaml  id prefix + delivery folder per vertical
config/delivery.yaml   the week-folder root and the filename convention
```

Finals ship into the existing tree, under the existing names:

```
VIDEO/MENOPAUSE YOGA/34 week/n-MENY072_ch-fb_t-video_c-canu_pr-lp_ds-nano_w-34_s-1080x1920.mp4
```

Both sizes, every time. Delivery never hard-deletes — a replaced file moves to
`_to_delete/`. Ids are allocated against the week folders too, so one that has
already shipped is never reused.

## Tests

```bash
./.venv/bin/python -m pytest -q
```

445 tests. They execute the pipeline; none of them pass by reading source.

## Docs

- [`docs/DEPLOY.md`](docs/DEPLOY.md) — running it on a machine that is not the one it was built on
- [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md) — the design record and the rules that must not be reverted
- [`docs/PROVIDER_FACTS.md`](docs/PROVIDER_FACTS.md) — API facts that cost credits to learn
- [`docs/PORTING_NOTES.md`](docs/PORTING_NOTES.md) — what came across, what is left

## Status

The pipeline runs end to end, and two backends are live: **KIE** for images and
video, **Gemini** for analysis, prompt writing, media QA and TTS. Both were
contract-probed against the real APIs without generating anything.

Assembly is real ffmpeg: clips are joined, the packshot from `assets/packshots`
is appended last, shots dissolve into each other, an optional music bed ducks
under the speech, word-by-word subtitles are burned from a Whisper transcript of
the cut, and the approved disclaimer and "Created with AI" overlays go on top —
both sizes, every time. The first creative, **LIPIL025**, shipped on
2026-08-18 for 987.2 credits.

`fal`, `openai`, `anthropic`, `elevenlabs` and `higgsfield` are declared and
routable but not implemented; asking for one fails loudly by design.

Set `providers: {…: mock}` in `config/models.yaml` (or `FJOR_STUDIO_BACKEND=mock`)
to walk the whole pipeline for zero credits.
