# Porting notes — what came across, what did not, what is left

Inventory of the colleague's `creative_pipeline.html` (45,460
lines, 841 functions) against this repo. Read `BLUEPRINT.md` first.

Their comments are in Russian and are the best documentation that exists — many
record a bug and its fix. Read the comment before assuming a line is arbitrary.
Navigate the file with `grep -n` and targeted `sed -n`, never top to bottom.

---

## Ported (milestones 1-2)

| Theirs | Ours |
|---|---|
| The 6-step pipeline shape | `engine/pipeline.py` |
| `pauseBeforePhotos` / `pauseBeforeVideos` | `GATE_PLAN` / `GATE_PLATES` |
| `perGenQaEnabled`, `autoRegenOnQaFail` | `qa.clips.*` |
| `perPhotoQaEnabled`, `photoQaAutoRegenEnabled` | `qa.plates.*` |
| `disableMediaQa` (master switch) | `qa.enabled` |
| `analysisDepth: default\|deep\|bulletproof` | `analysis.depth` |
| `refKind: ugc\|replica` | `analysis.ref_kind` |
| `copywriterSelfAudit` | `prompts.self_audit` |
| `_qaFailIsSpeechOnly` (r85/r87) | `qa/policy.py:is_speech_only` |
| technical error ≠ critical defect | `qa/verdict.py:technical_failure` |
| `providerPreference` routing matrix | `gen/registry.py:CAPABILITIES` |
| KIE `code`-in-a-200 handling | `gen/http.py:envelope` |
| Seedance per-second pricing | `costs.py` |
| `step6Defaults` (formats, subs, CTA) | `pipeline.yaml delivery` (partial) |
| `kieUploadBlob` + `kieImageTask` + `generateSeedanceKie` | `gen/kie.py` |
| Gemini analysis / prompt / QA calls | `gen/gemini.py` |
| Their delivery naming + week folders | `naming.py`, `config/delivery.yaml` |
| `generateAss` bold-pop, chain-link, clamp | `subtitles.py` |
| `SUBS_LEXICON` + niche vocabulary repair | `subtitles.py` LEXICON / VOCABULARY |
| `whisperTranscribe` word timings | `subtitles.py:transcribe` |
| `crossfade` 0.5s default, xfade + acrossfade | `assemble.py:crossfade` |
| music bed + `sidechaincompress` ducking | `assemble.py:mix_music` |

**Note:** `deepAnalysisPass` and `triplePassAnalysis` are marked LEGACY /
deprecated in their state and are read on migration only — the live field is
`analysisDepth`. The 2026-08-18 handoff lists the two old flags; use
`analysisDepth`.

---

## Dropped on the owner's call

- **`phoneticForSeedance()` and its dictionary** (their line 7750) — the
  respelling trick that rewrites words Seedance mispronounces inside quoted
  dialogue. **Owner, 2026-08-18: "this dictionary doesn't work in practice."**
  Not ported, and not to be reintroduced as a clever idea later. If Seedance
  mispronunciation needs solving, it needs a different solution — note that
  their own QA prompt still lists mispronunciation as a critical dialogue
  failure, so the *detection* half is worth keeping when the QA prompts land.

## Deliberately different

- **QA output language.** Their `SYSTEM_PER_GEN_QA` demands `issues` and
  `summary` **in Russian**. Ours parses either but the prompts we write will ask
  for English — the producer here reads English.
- **Their QA severity floor.** Their prompt is explicit that regeneration costs
  $2.50–3.50 and that false-positive criticals waste money, so it defaults to
  `minor`, with three named exceptions that stay critical however subtle: **body-type
  mismatch**, **visible brand logo**, **exercise activity in a diet niche**. That
  economics reasoning must survive into our prompt text verbatim when the QA
  prompts land.
- **`assembly` before the draft gate** (BLUEPRINT §3.2).
- **Two-phase `submit`/`poll`** (BLUEPRINT §3.3).

---

## Not yet ported — roughly in value order

1. **The QA system prompts themselves.** `SYSTEM_PER_GEN_QA` (7 rules, line
   ~18155) and `SYSTEM_PER_PHOTO_QA` (line ~18048), plus
   `systemPerGenQaForRefKind()` which swaps them per `refKind`. Our QA plumbing
   is built and tested; these are the payload.
2. **FAL**, as the standing reserve for everything KIE does. A key exists (from
   the kit export). Not urgent while KIE works.
3. **OpenAI images / Anthropic text**, if either is ever wanted. Both have keys;
   neither is routed.
4. **The rest of ffmpeg assembly.** The other subtitle styles (`highlight`,
   `karaoke`), the CTA library as distinct from the packshot, and `source45`
   inversion (master 4:5, 9:16 derived) for references shot 4:5. Concat,
   crossfade, packshot, music bed with ducking, bold-pop subtitles, disclaimer
   and badge are done.
5. **`runValidation` / `runAIAudit` / `runFinalReview`** — the prompt-level QA
   passes, distinct from media QA.
6. **`runIteration` / `runIterationBatch` / `runRegenOnePrompt`** — targeted
   regeneration of a single GEN block.
7. **Banner mode.** `sourceMode: 'banner'` with its own `bannerOverrides` copy-on-
   write settings layer, and a QA note that burnt-in ad text is *intended* there.
8. **`runDub`**, **`runReframe`**, the timeline audio builder.
9. **Style-ref library.** Their kit export carries 20 `style_refs`, 6
   `gen_videos`, 3 `images` in IndexedDB — still unmined. We have no
   style-reference concept.
10. **Niche templates.** `NICHE_TEMPLATES` auto-injects vertical adaptations into
    the prompt writer (mediterranean, cortisol, religion, fasting, yoga, pilates,
    lymph, military, …).

---

## Settled

- **Their tool is a separate thing** (owner, 2026-08-18). This is our own
  version, not a co-owned pipeline. No naming treaty is needed with it — but see
  the id note below, which is about the *week folders*, not about their tool.
- **Delivery matches the existing week-folder convention** (owner, 2026-08-18):
  `<root>/<VERTICAL>/<N> week/` with the token filename. Done — BLUEPRINT §3.8.
  Because those folders already hold work from more than one tool, id allocation
  reads them and never reuses an id that has shipped.

## Open questions for the owner

- **Which of their extras actually matter here** — Kling, Soul, dubbing, the
  timeline audio builder, the iteration batch? Nothing below the first three
  items in the list above has been scoped.
- **Concept tokens.** The `c-` value is free text today (`ugc`, `canu`,
  `julia-week`, `bootcamp`, `morph`…). If there is a fixed vocabulary, it should
  live in `delivery.yaml` and be validated at intake.

---

# The v4 port (their r170–r234), started 2026-08-31

Source: `~/Downloads/Тула_для_команды/creative_pipeline.html` (58,525 lines, up
from the 45,460 inventoried above) and the release notes beside it. The two that
matter: `ЧТО_НОВОГО_4_КРАТКО.md` for this release, and `ЧТО_НОВОГО_3.md`, which
carries the whole "Оживить баннер" playbook.

All of it is on branch **`tool-v4-port`**. `main` is untouched. The tag
**`before-tool-v4-port`** is the last commit before any of it:

    git reset --hard before-tool-v4-port      # add `git clean -fd` for new files

## Done

| | |
|---|---|
| 720p on every video model | Their Pro/2.5/Motion Control billed ~2x for a 1080p source the final never used. |
| Back Pain Relief, Apostolic Walking | BPR was already shipping into that folder; the prefix had to match. |
| KIE Motion Control + morph call shapes | See PROVIDER_FACTS: KIE proxies MC onto fal, `background_source` is fatal, MC takes no duration. |
| Motion drivers, end to end | Engine and length settled ON the driver; driven shots silent with the line spoken by us; plate as a start frame; 300-600 char prompts. |
| Transformation (morph) | Two photographs of one frame; end frame generated FROM the start frame; both priced. |
| Text card in the reference's style | Typography read on demand, card keyed as an image, bottom band checked before assembly. |

## Not done, in the agreed order

1. **Static → video, "Оживить баннер".** DONE, end to end on the mock —
   `fjor_studio/banner.py`, `fjor_studio/stages/banner_steps.py`,
   `tests/test_banner.py`, `tests/test_banner_mode.py`. Not yet run on a live
   model or a real client banner.

   Done:

   - **The CANVAS expansion engine**, of their three the only verifiable one.
     `build_canvas` composites the banner at true size on a 1080x1920 marker
     frame in ffmpeg, so the model is asked to replace the marker and nothing
     else; `banner_survived` crops the banner's own rectangle back out and
     compares it with what went in. Verified against three edits their QA calls
     critical: a recoloured headline, a button nudged 6px, the legal line
     painted out.

     NOTE the lesson in that check: it first AVERAGED the difference and all
     three edits passed, because a local change is diluted across a million
     pixels. It counts changed pixels over a threshold now (24; honest expansion
     produces exactly zero). Do not "simplify" it back to a mean.

   - **The licensed band.** The legal small print always goes, and that is an
     edit INSIDE the banner — so it is a SECOND pass, over a band named in
     advance (`SMALL_PRINT_BAND`, deliberately mean so it does not licence the
     CTA button above it), with everything outside the band still held to zero.
     A licensed pass that changed nothing in its band reports
     `edit_applied: False`, because a skipped pass is otherwise identical to a
     clean one. See BLUEPRINT §3.4g and rule 20.

   - **The expansion prompt playbook**, adapted to the canvas. Half of their
     playbook exists to stop a model re-laying-out a bare image (PRESERVE,
     LAYOUT LOCK, "~420px each side"); on a canvas the geometry is settled in
     ffmpeg before the model is called. What does not come free is the analysis,
     so the division of labour changed: **the writer answers the four questions
     (`ANALYSIS_QUESTIONS`), `expansion_prompt` builds the prompt.** A prompt
     assembled from answers cannot have an unfilled bracket — which was one of
     the two things their tool shouted about. Both tiers survive (short for a
     flat background with nothing cut, full otherwise, FULL when unsure).

   - **`check_prompt`**, which enforces their FIRST iron rule mechanically:
     never name a colour outside quotes. They left it to the writer's
     discipline; it is the rule that actually costs money (a named shade means a
     seam band → critical QA → regeneration) and it is trivially checkable.
     Quoted text is exempt, which is what makes it safe — a headline reading
     "Black Friday" is printed on the banner and must be named exactly. Also
     catches leftover placeholders, bloat, and an expansion prompt that never
     names the marker.

   - **The animation rules.** Same division of labour (`ANIMATION_QUESTIONS` →
     `animation_prompt`). Two of their nine rules are marked "include this line
     verbatim"; ours are INSERTED, not requested. Enforced: 1–2 movers on a
     photograph and 2–4 tiny staggered events on a flat drawn banner (one mover
     on a drawing leaves the clip dead); at least one mover inside the central
     4:5 zone, or the 4:5 final ships frozen; anything carrying printed
     lettering does not move at all; camera locked by default (theirs moved to a
     slight push-in, but our frame has an expansion in it and a push-in
     magnifies the newest pixels); 5–10s; silent; loop-friendly.

   - **The wiring**, as a source mode. A banner job runs the SAME pipeline
     states and stops at the SAME gates; `stages/banner_steps.py` holds the four
     stages that differ and `steps.py` branches into them. Intake takes an
     IMAGE and settles the geometry there (whether there is anything to expand
     at all decides what the job costs, and after the gate is too late).
     `analysis`, `cast_plates` and `voiceovers` do nothing. `plates` builds the
     canvas, expands it, checks survival AND runs a banner-specific QA — two
     checks because they see different things: `banner_survived` is exact but by
     construction blind to everything outside the banner's rectangle, which is
     where a seam or a half-drawn person would be. `clips` is unchanged: an
     expanded frame is a plate like any other.
   - **QA has its own prompts here, not an exception clause.** Our media QA
     calls readable text a critical defect and a brand logo a legal risk; on a
     banner both ARE the creative. An override appended to those numbered rules
     would be a prompt arguing with itself.
   - The mock backend learned `echo_images` — "the model returned its input
     unchanged", which is what an edit-in-place model does. Without it no test
     of a check that COMPARES a result with its input could fail honestly.

   Still to do:

   - **Restyle variations** ("beach / sporty / abstract"): same offer, same
     words, different style and decor, each assembled as its own full final. In
     their tool each variation re-renders the banner; the expansion itself is
     cached once per banner and reused, and their r172 audit found three
     parallel variations paying three times for it.
   - **A dashboard route** for creating a banner job. It is CLI/engine only.
   - Untried on real material: whether a real banner's small print sits inside
     `SMALL_PRINT_BAND`.

   **First live run, AW025, 2026-09-01 — failed at 36 cr, and worth every
   credit.** Two findings:

   1. `resolution: 1K` makes nano-banana-pro answer a 1080x1920 canvas with
      768x1376, the same size both attempts, whatever the prompt asks. Their
      tool sends identical parameters and never compares, so it never noticed.
      We now buy the expansion at 2K (their notes price Banana Pro "$0.09 for
      1-2K", so it is the same money) and, more importantly, no longer need the
      provider to honour a size at all -- see below.
   2. THE PLAYBOOK WAS THE WRONG PROMPT FOR THIS ENGINE. It was assembled into
      2,361 characters of scene description and sent with the canvas, and the
      model drew the scene: both attempts came back with the banner's dusk
      photograph replaced, one by an orange sunset, one by an afternoon sky.
      Their tool keeps the two engines apart deliberately -- the canvas gets a
      short fixed fill instruction describing NO content, because the canvas
      already shows the model what is there. `banner.ANALYSIS_QUESTIONS`,
      `expansion_prompt` and `check_prompt` remain in the module as the ported
      playbook for the bare-image engine we do not have; they are NOT wired.

   What changed as a result: the canvas is sent `fill_prompt()` and nothing
   else; the plan asks only about the animation; `same_picture` judges the raw
   return at 32x32 (measured: honest 1.08-1.76, re-renders 15.66-65.88, limit
   8); `recomposite` puts our own banner back over its rectangle so it is exact
   by construction; and `banner_survived` then PROVES that, which is the only
   job it can still do honestly. A brief edit is refused out loud in this mode,
   because it would be painted and then overwritten.

2. **ElevenLabs voice.** DONE — `gen/elevenlabs.py`. All three clauses of their
   note are mechanised: paid once per text (keyed on line + voice, reused across
   shots), never silently absent (the backend refuses an empty response and the
   stage re-checks the file that landed), and prepared before assembly. Plus two
   of our own: a refusal is never written to disk as audio (the API answers JSON
   when it refuses), and `fjor-studio voices` lists real voice ids, because
   ElevenLabs takes an ID where Gemini takes a NAME. Untested against the live
   API -- no voice id has been configured yet.
3. **Dubbing.** DONE, and ported rather than redesigned.

   The source is an UPLOAD: the owner's own creative, produced elsewhere. An
   earlier draft here dubbed the CLIPS of an in-tool job and re-assembled, which
   avoids the blur band entirely because our clips never carry subtitles. It was
   wrong twice over -- the videos are not made here, and even when they are, a
   cut re-assembled from separately dubbed clips is not the same cut: the mix,
   the bed and every transition get rebuilt, and any of them can drift from the
   English original that was approved. Dubbing the finished file changes the
   speech and nothing else.

   Their geometry is in `dubband.py` and every constant in it is a paid-for fix:
   the blur radius is clamped against the CHROMA plane (in yuv420p the chroma
   planes are half size and take the same radius, and overrunning them killed
   ffmpeg mid-dub), the chroma radius is set explicitly to half, the blurred
   region carries a +/-r margin because boxblur repeats pixels at its edge, and
   every dimension is even. The `geq` alpha ramp is the one part that is not a
   port -- they draw the gradient as a PNG in a canvas -- so it is the part with
   a test that actually runs ffmpeg and measures the edge energy left behind.

   The one thing their producer supplies with a mouse is where the band goes.
   There is no mouse here, so it is a number with their defaults (78% down, 15%
   tall) and a still preview to check it against. Sight was always the point;
   the drag was only how they got it.
4. **Dashboard UI** for drivers, morph, the card and banner mode. DONE.

   **Finer editing (Sept 2026).** Their timeline, ported selectively, per the
   Cut Control design note. Taken: per-shot trim (in/out), per-shot mute and
   mute-all, bed volume and ducking, and the voiceover as a movable, trimmable
   TRACK. Left: split (the owner said trim is enough), text/image overlay
   tracks (overlap the text card), undo/redo, and their browser preview -- it
   exists because their assembly is slow and browser-side; ours re-cuts with
   ffmpeg for free and the draft player shows the real cut.

   The voice was the one change that moved machinery rather than adding to
   it. It had been welded into its shot by `normalise()` and silently cut off
   by `-shortest` when longer than the shot; it is now laid over the assembled
   cut like the bed (`mix_voices`), anchored to its shot by an offset so a
   trim or reorder ahead of it moves the voice with its picture, mixed BEFORE
   the bed so ducking still keys off it, and clamped at `speech_end` so it
   never runs over the packshot. Where a shot starts is the same sum
   `crossfade()` uses -- every join eats one fade -- and a test measures the
   voice landing at 3.0s not 4.0s under a 0.5s crossfade.

   - The New-job drop zone takes an image as well as a video and SAYS which
     pipeline will run — for a banner, how many pixels will be painted above and
     below. Their tool announces the same thing with a toast, because the two
     modes look alike from the outside and mixing them wastes a generation.
   - Transformation and text-card briefs are fields there, hidden (and dropped
     from the request, not merely hidden) when the source is a banner.
   - Drivers get a dialog at GATE_PLAN — the first moment the shot list exists
     and the last before anything is bought. Choosing Motion Control says, where
     it is chosen, that the shot's length is overwritten by the driver's and the
     clip is generated silent.
   - A transformation shows BOTH plates, side by side in a box twice as wide.
     Showing only the first hides half of what was bought, and the half that
     decides whether the morph works is whether they are the same frame.
   - Banner jobs get a card with the survival verdict on it.

   Note: drivers had NO user-facing entry point before this — `add_driver` and
   `attach_driver` were engine methods with no CLI command and no UI. The
   dashboard is now the only way in; a `fjor driver` command would be the
   obvious next convenience.

## Dropped on the owner's call

- **Pronunciation** (curly braces, stressed syllable in caps, the ~120-word
  dictionary). Owner, 2026-08-31: "we don't need it at all, it proved to be
  useless" — consistent with the 2026-08-18 call on the phonetic dictionary.
- **Their UI work** — collapsible panels, download buttons, timeline repeat.
  Our dashboard is a different thing.

## Not yet proven on real material

Everything is tested against synthetic ffmpeg clips. Untried: fal's size limits
on a real driver, first-frame extraction from real footage, and whether a
driver's opening frame is usable as a plate template. Motion Control also has no
measured rate, so a gate with driven shots forecasts them as unpriced — a floor,
not a price. The owner has accepted that for now.

