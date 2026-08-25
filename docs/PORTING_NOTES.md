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
