# fjor-studio — blueprint

**Written 2026-08-18, milestone 1.** This is the design record: what was decided,
and why. Read it before changing the pipeline shape.

---

## 1. What this is

The colleague's tool (`creative_pipeline.html`, kept outside this repo) is a
45,460-line single-file browser app with an excellent, battle-tested generation
pipeline and no engineering underneath it: `localStorage` for a few toggles,
IndexedDB for media, **no job model, no resume, no ledger, no cost accounting**.
Close the tab mid-run and the work is gone.

`fjor-studio` keeps their pipeline and puts a real job engine in front of it.

It is a **clean-room rebuild** (owner's call, 2026-08-18). `fjor-video` is read as
a reference and is otherwise untouched; no code was copied from it. Where this
repo differs from either source, §3 says why.

---

## 2. The pipeline

Their six UI steps map onto our states one-for-one:

| Their step | Our state | Spends |
|---|---|---|
| 1 Upload reference video | `intake` | — |
| 2 Gemini analysis | `analysis` | text/vision tokens |
| 3 Creative prompts | `prompts` | text tokens |
| (`pauseBeforePhotos`) | **`GATE_PLAN`** | — |
| 4 Plates | `plates` | **images** |
| (`pauseBeforeVideos`) | **`GATE_PLATES`** | — |
| 5 Image-to-video | `clips` | **video — the expensive one** |
| — | `voiceovers` | speech, for shots with no visible speaker |
| 6a Cut the draft | `assembly` | — (ffmpeg) |
| — | **`GATE_DRAFT`** | — |
| 6b Clean masters | `finalize` | — (ffmpeg) |
| — | `preflight` | — |
| — | `delivery` | — |

Terminal: `done`, `failed`, `cancelled`. Revisions run as `revising_<stage>` and
then continue **forward**, so a revision always comes back to the gate it left.

Invariants:

- every transition appends an event and saves the job, so **resume is `load` + `run`**
- stages are re-runnable; work already on disk is reused, never re-bought
- `GATE_PLATES` and `GATE_DRAFT` can never be skipped, by any config

---

## 3. Decisions, and what they cost to learn

### 3.1 Four gates, two of them skippable

Their tool has two optional pause points and both ship defaulting to OFF, because
plates are cheap. Ours keeps all four as real states, and `gates.skip` accepts
**only `GATE_PLAN` and `GATE_CLIPS`** — the two where skipping costs nothing but
a look. Listing `GATE_PLATES` or `GATE_DRAFT` raises at startup rather than being
ignored — a silently-honoured bad config would read as if it had worked. See
`engine/pipeline.py:skippable_gates`.

### 3.2 The draft is cut *before* the gate that reviews it

`assembly` sits before `GATE_DRAFT`, `finalize` after. A gate showing raw clips
cannot tell a producer whether the edit works, and it makes the cheap revisions
(caption size, hold length, the bed — all ffmpeg) impossible to request without
rewinding into paid stages. This was caught by a test asserting that every
revision target rewinds rather than jumps forward.

**Amended 2026-08-21 — `GATE_CLIPS`, which does not revert this.** The owner
asked for a stop between the shots and the cut: a shot can come back wrong, and
assembling around it is work spent on a cut that will be re-made. So there is now
a gate on the *material* as well as the one on the *cut* — the draft is still
built before `GATE_DRAFT`, which is still unskippable, and every cheap revision
still lands on `assembly`. `GATE_CLIPS` is skippable precisely because it guards
nothing but attention; everything after it until `finalize` is ffmpeg.

### 3.2b The edit belongs to a gate, not to the brief

Deleting a shot, reordering, the bed, the caption colour: all of it is ffmpeg, so
all of it is answerable *after* seeing the material, as many times as the
producer likes. It lives in `job.meta["edit"]` — read by `stages/steps.py:edit_of`
and `cut_scenes`, written only through `engine.set_edit`, which refuses anything
but a gate and validates before it saves. Owner, 2026-08-21: the music bed was a
question the brief asked before anyone had heard the cut, so the brief stopped
asking. `intake.music` still *seeds* the edit — the CLI's `--music`, a variation
inheriting its parent's bed, a job made before the editor existed — but the gate
always wins.

Two things this must keep doing:

- **A dropped shot is dropped from the CUT, not deleted.** The clip is paid for
  and stays on disk; the editor puts it back in story order.
- **The subtitle signature follows the cut.** Word timings are positions on a
  timeline (§3.11), and dropping a shot moves every position after it. The
  signature is built from the scenes *in the cut*, so a re-cut re-transcribes
  rather than replaying stale timings — and `finalize` still refuses to deliver
  against a signature that does not match.

**The strip is dragged, and the drag is pointer events.** The first version gave
each shot ↑ ↓ buttons; the producer reported them as doing nothing. They worked —
but five near-identical boxes swapping places is not a visible event, the player
above kept the old cut with no explanation, and a disabled end arrow at 40%
opacity looks exactly like an enabled one. So: plate thumbnails on every chip, a
flash on the shot that moved, a banner on the cut saying it is out of date, and
the gesture itself changed to dragging. **Not HTML5 drag-and-drop** — that API
cannot be driven by synthetic input, so a strip built on it cannot be verified
end to end, which is how a dead-looking control ships in the first place. Pointer
events also cover trackpad and touch. The strip is never re-rendered mid-drag:
replacing the element under the pointer ends the gesture, so a ghost follows the
pointer and the landing place is drawn on the neighbour with a class.

An edit that repeats a shot is refused rather than allowed: the same clip twice
would be transcribed once and subtitled over both, which is a defect nobody
would think to look for.

### 3.3 Generation is `submit` then `poll`, never one call

**KIE has no cancel endpoint.** `/jobs/cancelTask` and `/jobs/cancel` both 404.
The moment `createTask` returns a taskId the credits are committed, whatever
happens next. So `stages/paid.py:run_generation` writes the task id to `job.json`
**between** submit and poll, and a crash after that point loses no money: the
retry collects the existing task instead of buying another
(`tests/test_resume.py`).

Nothing outside `run_generation` may call `backend.submit`.

### 3.4 Forecasts are per-second, and admit what they cannot price

Seedance on KIE bills **24.8 credits/second at 720p** — measured, linear
(4s → 99.2, 15s → 372.0). A flat per-clip estimate under-quoted `fjor-video`'s
frames gate roughly five-fold. `costs.py` holds only rates traced to a real
invoice line; anything else is reported as **unpriced**, and a forecast
containing one says `complete: false` and logs `forecast_incomplete` rather than
presenting a partial total as the price.

`creditsConsumed` on KIE's `recordInfo` is the truth. The ledger records what was
actually charged, which is allowed to disagree with the forecast.

### 3.4b A provider's limits are enforced where the plan is read

The writer is *told* the video model cannot make a clip shorter than four
seconds. LIPIL050 came back with 2s, 1s and 2s shots anyway — it had mirrored
the reference's cut rate — and the job died inside `clips`, after five plates
had been paid for. The guard in `gen/kie.py` worked exactly as designed and
still cost 90 credits, because it fires at the moment of spending.

A model instruction is a request. A provider's range is a fact. Durations are
now clamped in `_parse_scene_plan`, and every clamp is recorded as a
`plan_adjusted` event — stretching a 1s cut to 4s changes the pacing the writer
intended, so it must not happen silently. The bounds live in `pipeline.yaml`
under `prompts.duration_s`; KIE's own check stays as the backstop it was.

The general rule: **anything a paid stage will refuse should be refused, or
repaired, before that stage starts.**

### 3.4c Identity is carried by a picture, not by words

Every plate used to be generated independently from text, so nothing tied one
shot to the next. A five-shot podcast ad came back as three different women in
the same navy top: the description was identical, and the model invented a new
face each time. The writer's own prompts made it worse — LIPIL050 said "dark
hair" in one shot and "the same blonde woman" in the next.

The plan now declares a **cast**: everyone who appears in more than one shot,
with an id and a description. One portrait is generated per cast member before
any scene, and attached to every shot that names them, under an identity block
that states plainly that **the image outranks the text** — the words govern only
wardrobe, setting, pose, expression and light.

Measured on real generations: a portrait plus two anchored scene plates came
back unmistakably the same person, where the unanchored originals of the same
two prompts were two different women.

**A variation is consistent; WHO it stars is a question (2026-08-25).** `derive`
inherited the prompts without the cast, so a child kept naming `host` in every
shot with nobody to be: `anchors_for` found no portrait, each plate invented a
face, and LME109 came back as five different women — 90 credits spent, with
1,215 of video behind the approve button.

The cast now travels whenever the prompts do. Whether the **portraits** travel
with it is `recast`, and it is asked rather than assumed — the first fix carried
them unconditionally, and the owner's next variation came back as the same woman
as its parent, which was not what "variation" meant. Both answers are real: a
second cut of one creative wants the same host, a new test of the same script
usually wants a different one. What is never wanted is the third outcome, a
different face per shot. `cast_descriptions` rewrites who a character is, because
another draw of the same words is another woman of the same description. A
rewrite (`from="prompts"`) always declares its own cast.

The dashboard asks only when the plates are actually re-bought: inherit them and
the face is already fixed.

And the plates stage now REFUSES to spend when a name on screen has no cast
entry to anchor it, before the first charge. Anchoring failing silently is the
same class of defect as a QA check that could not look (§3.5): the run completes,
every file is present, and the money is gone.

Anchors are capped at two per shot. Beyond that the references compete and the
result drifts toward an average of them. Portraits cost one plate each (18 cr),
they are counted in the `GATE_PLAN` forecast, and `characters.enabled: false`
restores the old text-only behaviour exactly.

### 3.4d A voice with no visible speaker must not come from the video model

BPW026 was refused three times with *"the output audio may be related to
copyright restrictions"*. The same prompt and the same plate passed immediately
with `generate_audio: false`. The wording was never the problem: asking the
video model for a disembodied voice makes it invent a soundtrack, and the
soundtrack is what gets refused.

So the plan declares a `voice` per shot:

- `on_camera` — the speaker is in frame; the model renders speech with picture
  and the lips match.
- `vo` — a voice is heard, nobody on screen says it. The clip is generated
  **silent**, the line is spoken by the TTS backend in the `voiceovers` stage,
  and `assemble.normalise` lays it over that segment.
- `silent` — room tone only.

The line is kept out of `video_prompt` for a `vo` shot: telling the model to say
something while asking it for no audio is the contradiction that started this.

Two details from getting it wrong first:

- The voiceover is **padded, not mixed**. `amix` against a silence source let the
  shortest input win, so a 2.5s line cut a 4s shot down to 2.5s. `apad` runs the
  voice then silence, and `-shortest` trims to the picture.
- A refusal is **terminal**, and used to be recorded as still-running. That made
  every retry re-poll a dead task, so a job could never get past a refused
  generation. `ProviderBusy` means alive and collectable; anything else means
  finished and refused, and the retry buys a new one.

Refusals are free — BPW026 was refused four times and the ledger never moved —
so diagnosing one costs time, not credits.

### 3.5 Three things a QA verdict is not

Ported from their `runPerGenQa` / `runPerPhotoQa`, which is the highest-value
thing in their tool and the part with the most scar tissue.

- **A QA call that could not run is not a defect.** A 503, a timeout or an
  unparseable reply becomes `technical=True`: never triggers a paid regeneration,
  never blocks assembly. Their tool learned this as `severity: 'error'` vs
  `'critical'`.
- **Silence is not a defect when silence is the plan.** Under an external voice
  track the clip is *meant* to have no speech, so a "the actor does not speak"
  verdict is the plan working. Without this guard, one such verdict both burned
  paid regenerations and blocked the whole unattended run (their r85/r87).
- **A disabled check is not a passing check.** QA that is switched off stores
  **no verdict at all**, not an `ok` one. A stored "ok" from a check that never
  looked is a guard structurally incapable of failing, and everything downstream
  would read it as evidence. `preflight` reports `could_not_look` separately from
  `failed` for the same reason.

`is_speech_only()` returns **False** for an empty issue list on purpose: a
verdict that failed while naming nothing is not evidence of anything.

### 3.4e Movement comes from ONE place: the driver, or the two frames

Two of their v4 features put motion somewhere other than the words, and they
cannot be combined. A **motion driver** carries the movement, timing and camera
of someone else's clip onto our photograph; a **transformation** hands the model
two photographs of one frame and morphs between them. A shot asking for both
describes nothing the API can make, and is refused before the clips are bought.

What each one costs elsewhere:

- A driven shot's PLATE is a starting frame, not a model shot. The driver's
  opening frame goes in as a geometry template — same angle, shot size, hands,
  and the same KIND of contact surface, because a body that starts from a bed
  where the driver had a mat animates wrongly. Everything else is ours; the room
  is rebuilt, never copied, and the actor is a different individual of the same
  type even when nobody asked for a casting change.
- A driven shot's PROMPT is 300-600 characters and says nothing about motion.
  The video carries the movement and the photo carries the person; writing them
  out again competes with them, and when a word disagrees with a pixel the shot
  comes out wrong. Speech is the exception, always in full: neither asset
  carries it.
- A driven shot is generated SILENT and its line is spoken in `voiceovers`. The
  driver carries a stranger talking, and Motion Control gives us no say over the
  soundtrack.
- A transformation's END frame is generated FROM the start frame, and judged
  like any other plate. It is the same photograph after the change — anything
  else that differs will be seen moving. The gate prices BOTH photographs.
- Motion Control runs exactly as long as its driver and is given no duration at
  all, so attaching one retimes the shot and the plan's 4-15s clamp does not
  apply to it. Their tool decided length while writing prompts, which is how a
  23-second driver became a 15-second clip.

### 3.4f A text card copies the manner, never the words

Their "text in the reference's style": read HOW the reference sets its type --
typeface character, weight, case, fill and outline, the plate behind the words,
the block layout down the frame -- and set OUR offer that way. The manner is
copied; the words are ours.

Three things make it work rather than merely run:

- **Keyed as an IMAGE, not as video.** A flat digital colour keys far more
  cleanly than a filmed one, and the halo the letters pick up is despilled
  properly. Green, or magenta when the reference's own lettering has greens in
  it and would key away with the background.
- **Laid on full-frame, 1:1.** The card is generated at the frame's own shape,
  so every block is already where it belongs; cropping it to its ink would move
  all of them.
- **The bottom band is CHECKED.** The disclaimer and the badge live there and
  are approved compliance assets, so the card is keyed and its alpha read before
  it is accepted. A card that reaches into that band is regenerated, and after
  the attempts run out the job stops rather than shipping over a disclaimer.
  Discovering it at assembly means discovering it after the clips are paid for.

The analysis is only asked about typography when a card was asked for, and it is
told never to describe the reference's own disclaimer or small print: ours goes
on separately as an approved asset, and copying theirs is the one thing this
must never feed forward.

### 3.4g A banner is an asset, not a draft

Their "Оживить баннер" takes a finished, client-approved banner, expands it to
9:16, and animates it. Everything printed on it -- the offer, the button, the
logo -- is a thing somebody signed off. An expansion that redraws a letter,
shifts a button or shades a colour has not blemished the asset; it has destroyed
it. So the mode is built around one question, asked mechanically.

- **The canvas is built HERE.** Of their three expansion engines we took the
  canvas one, and not because it is cheapest: it is the only one we can check.
  We composite the banner onto a 1080x1920 marker frame in ffmpeg, so the
  banner's own pixels are still the banner's own pixels when the model is
  called, and afterwards we crop that same rectangle back out and compare it
  with what went in. A model handed a bare image and asked to be careful leaves
  nothing to compare against.
- **Two questions, two statistics, and neither is the other's.** AW025
  (2026-09-01) asked for a 1080x1920 canvas and got 768x1376 back, twice,
  identically -- an image model answers with its own resolution bucket whatever
  the prompt says. Nothing pixel-exact can be asked of a rescaled frame. So the
  raw return is asked only the coarse question, at 32x32: IS THIS THE SAME
  PICTURE? Then our own banner is composited back over its rectangle, and the
  strict pixel check is asked of THAT -- where it works, and where it now proves
  the restoration rather than hoping for it. The mean is right for the first
  question and wrong for the second; that is not a contradiction, it is two
  questions.
- **A description handed to an editing model is an invitation to draw.** The
  same job sent the four-question playbook -- 2,361 characters of scene
  description -- along with the canvas, and both attempts came back with the
  banner's photograph replaced. Their tool keeps two engines apart on purpose:
  the canvas gets a short fixed "replace only the magenta" instruction that
  describes no content at all, because the canvas already SHOWS the model
  everything the description was trying to say. The playbook belongs to the
  bare-image engine, which we do not have.
- **The double must answer in ITS size, not ours.** Three paid failures on one
  banner came of a mock that echoed images back at exactly the size it was
  handed. Every fix looked green and then failed on real money, because no test
  ever ran the stage against a provider that answers in its own resolution --
  which every real one does. `write_replies(echo_size=...)` exists for that, and
  the banner stage is walked end to end with it returning 1536x2752.
- **A lesson learned at one call site is not learned.** The expansion was fixed
  for the resolution bucket and the small-print pass, four lines below it in the
  same function, was not -- and cost another paid run. Both calls now go through
  the same shape: judge the picture, restore what was not licensed to change,
  then verify.
- **The check COUNTS changed pixels; it does not average them.** The mean was
  the first thing tried, and a recoloured headline, a button nudged six pixels
  and a deleted legal line all passed it -- a local edit is diluted across a
  million pixels, under a tolerance codec noise already reaches. Rule 4 again,
  arrived at from a third direction.
- **The one licensed edit is a separate pass.** The legal small print always
  goes, and erasing it is an edit INSIDE the banner. Folding it into the
  expansion would mean the check could no longer tell a removed disclaimer from
  a redrawn headline, so it runs afterwards, over a band named in advance, with
  everything outside that band still held to zero. The band is deliberately
  mean: a generous one licences the CTA button just above it.
- **A licensed pass that changed nothing did not run.** It is otherwise
  indistinguishable from a clean result, which is how a silently skipped step
  reaches delivery.
- **Never name a colour.** Their hardest-won prompt rule: a named shade makes
  the model paint that shade instead of continuing the real edge pixels, and the
  result is a seam band across the frame. Name the material. This is checked
  mechanically rather than left to the writer's discipline -- quoted text is
  exempt, which is what makes it safe to enforce, because a headline reading
  "Black Friday" is printed on the banner and must be named exactly.
- **The writer answers; we assemble.** Their tool asked a model to write the
  prompt in prose and then searched the result for unfilled `[brackets]` and
  bloat. Ours asks the four analysis questions and builds the prompt from the
  answers, which cannot leave a bracket unfilled. The same holds for animation:
  two of their nine rules are marked "include this line verbatim", and a rule
  that depends on a model reproducing a sentence word for word holds until the
  day it does not. Ours are inserted.
- **At least one thing moves in the central 4:5 zone.** The 4:5 final is cropped
  from the middle of the 9:16 and ships beside it. A clip whose only movement
  lives in the expanded margins delivers one live video and one still.
- **The mode runs the same states and stops at the same gates**, but three
  stages do nothing: there is no reference to analyse, no cast to anchor, and no
  line to speak. Their v4 gave banner mode its own compact brain deliberately --
  the video instruction, the niche, the voice and the reference analysis are all
  kept out, because none of them describes a banner and each competes with the
  one asset that does. Subtitles are off for the same reason a banner clip is
  silent, and burning them would cover the client's own approved copy anyway.
- **QA gets a different checklist, not an exception clause.** Our media QA calls
  readable text in frame a critical defect and a visible brand logo a legal
  risk; on a banner both are the creative. An override appended to those rules
  would be a prompt arguing with itself, so banner mode has its own prompts,
  which ask instead whether the type survived, whether there is a seam, and
  whether anything moves in the middle.

### 3.4h A look is carried by a picture, and so is a body

AW024 was a stylised 3D cartoon reference. The analysis said so, every image
prompt opened with "3D cartoon animation style", and the creative came back
photoreal and uncanny. The words were right and the words were not enough --
which is 3.4c again, about style instead of identity.

- **The producer declares the kind at INTAKE.** Their tool asks twice: what the
  source is, and how to treat a video one (`UGC с людьми` / `Точная копия
  кадра`). Ours infers the source from the file and asks the second question.
  Their third source, `universal`, is a pipeline we do not have and is not
  offered: a control that changes nothing is worse than no control.
- **`replica` attaches STILLS, not adjectives.** Three frames are cut from the
  reference itself and go to every plate above the prompt, saying that where the
  words and the frames disagree about how this LOOKS, the frames win. They cost
  nothing -- the file is already in the job -- and they are cut once and reused.
  Spread across the reference, never from its opening, which is often a title
  card or a hard cut.
- **Body type is carried by the reference too**, and that rule is ported out of
  their per-niche templates because the failure is not vertical-specific: a
  plus-size woman in the reference is a plus-size woman in ours, at the same
  level. AW024 drifted its lead slimmer in two plates and lost the "before" of
  its own before-and-after. The drift is SILENT -- a slightly slimmer shot reads
  as fine alone and breaks the story only when the two ends are seen together --
  which is why it needs a rule rather than an eye.
- **A QA prompt must ask for the shape the parser reads.** The banner prompts
  asked for a `verdict` key while the parser reads `severity`, so every banner
  verdict came back `unclear`, which means "could not look" and passes silently.
  AW025's first live plate was never judged. Rule 4, from a fourth direction: a
  check nobody can read is a check that cannot fail.

### 3.5c A stop must leave the producer somewhere they can decide

AW024 failed at preflight on three blocking clip verdicts, and its own error
told the producer to run `revise ... clip --scene N`. `revise` accepts only a job
sitting at a gate, and a failed job is not at one. The tool named a command it
would refuse, at the moment 2,114 credits were riding on the answer.

- **Blocked is not failed.** A stage whose remedy lives at an earlier gate
  raises `Blocked(gate, why)`, and the job is put back at that gate with the
  reason recorded. Every route the message names -- revise, waive, approve again
  -- is then reachable. Only a gate the config cannot skip may be used as the
  landing point, or the run would bounce straight back and loop.
- **A defect in the STILL is not repaired by re-buying the animation.** The
  video model animates the plate it is given. `GATE_CLIPS` and `GATE_DRAFT`
  offered only `clip`, so the one honest fix for AW024's drifted body type was
  unreachable and the reachable one would have bought the same fault again at
  five times the price. Both gates now rewind to `plates`, which stops at
  `GATE_PLATES` so the new still is seen before the clip is bought.
- **Every route in an error message must exist where the message appears.** The
  dashboard had no `waive` at all: the accept route lived only in the CLI, so a
  producer on the page had no way past a block except to take the files off disk
  by hand. Both routes are on the page now.

### 3.5b A blocking verdict can be accepted, never erased

Preflight stops a delivery on a critical clip verdict, and sometimes the right
answer is to ship anyway: LME109's scene 0 held up four fingers on the word
"three" and scene 2 under-performed its leg swing, and re-buying both was 446
credits against flaws the owner judged smaller than that.

The two ways a person reaches for that outcome unaided — turning QA off, or
editing the verdict — both destroy the finding, and the creative then looks
clean to whoever opens the week folder next year. So there is `waive`: the
verdict stays exactly as written, the check keeps reporting that it failed and
which scenes, and the acceptance is recorded beside it. It is per-scene, it
needs a reason, and there is no blanket form. The waiver travels into the build
manifest that ships next to the file, which is why waiving rewinds to `finalize`
rather than straight to `delivery` — the manifest is part of the deliverable,
and one written before the decision would describe a creative that does not
exist.

### 3.6 Clips do not auto-regenerate by default; plates do

A clip re-roll costs real money and frequently returns the *same* artifact —
these failures are largely deterministic. Plates are cheap and a re-roll usually
helps. Defaults: plates `auto_regen: true, max_attempts: 2`; clips
`auto_regen: false, max_attempts: 1`.

### 3.7 The mock is a producer tool, not just a test double

`FJOR_STUDIO_BACKEND=mock`, or `providers: {…: mock}`, walks the entire pipeline
— every gate, every review file, every forecast — for zero credits. It is
deterministic, so a resume test can prove a paid generation was *collected*
rather than re-bought. `costs.MOCK_RATES` mirrors the mock's own charging
exactly, so a dry run's forecast is accurate about the dry run.

### 3.8 Delivery matches an existing convention exactly

Owner's call, 2026-08-18. Finals land in the live tree, not a folder of our own:

```
<root>/<VERTICAL FOLDER>/<N> week/n-{id}_ch-{ch}_t-{type}_c-{concept}_pr-{producer}_ds-{source}_w-{week}_s-{W}x{H}.mp4
/…/VIDEO/MENOPAUSE YOGA/34 week/n-MENY072_ch-fb_t-video_c-canu_pr-lp_ds-nano_w-34_s-1080x1920.mp4
```

None of this is ours to design — files in this shape already sit in every week
folder, and the manifests and the ad platform read them. Four consequences:

- **`pr-` is the PRODUCER'S INITIALS**, not the funnel. The vendored `naming.md`
  says funnel; the owner corrected that on 2026-08-03. `ds-nano` means
  "AI-generated", whichever model made it — the client calls all of it nano.
- **Vertical folder names and id prefixes come from `verticals.yaml`**, never
  from the vertical's name. `yoga` is `Y` and `yoga_men` is `YM`; no derivation
  rule produces those. Folder names are exact, spaces included, because they are
  existing directories.
- **An unknown vertical is refused at INTAKE and never at delivery.** At intake
  nothing has been paid for. By delivery the creative is built, preflighted and
  paid for, so the lookup is non-strict and falls back to the raw name rather
  than stranding finished files.
- **Ids are allocated against the delivery tree as well as the local jobs
  directory.** Those week folders hold work from more than one tool, and two
  creatives under one id in the ad platform is not fixable by renaming a file
  afterwards. A missing or offline root yields an empty set rather than an error.

Preflight checks finals by **the name the week folder will receive**, and
delivery **never hard-deletes**: a stale file of the same name moves to
`_to_delete/<timestamp>_<name>`, so a redelivery is always undoable.

### 3.8b A finished job is the start of the next one

Most variations change one thing. Running a fresh job would re-analyse the same
reference, rewrite the same prompts and re-buy the same plates to arrive at the
same place — and make the producer upload the reference again to get there.

`derive.py` takes a completed job and inherits everything up to the point where
the variation actually differs:

| start from | keeps | costs |
|---|---|---|
| `assembly` | analysis, prompts, plates, clips | nothing — it is ffmpeg |
| `clips` | analysis, prompts, plates | clips |
| `plates` | analysis, prompts | plates + clips |
| `prompts` | analysis | prompts + plates + clips |

The dialog prices all four before anything is created. Three rules hold:

- **The reference always comes across.** Re-uploading the same file to vary it
  is the friction this exists to remove.
- **Inherited credits are recorded, never claimed.** The ledger answers "what
  did *this* job spend", and for a re-cut the honest answer is nothing;
  `meta.inherited` says what it was handed.
- **Submissions do not travel.** They describe what the parent paid for, and
  carrying them would make the child look able to collect generations it never
  made.

The producer's note is appended to the brief rather than stored beside it — a
variation with no instruction is a copy, so the note has to reach the writer and
the regenerators, which is where the brief already goes.

### 3.8c Finals are watchable on the page

They were delivered to the week folder and listed by name, which meant opening
Finder to see what had been made. Both sizes now play in the job view, labelled
with format, dimensions, duration and subtitle count, with a download link.

### 3.9 Subtitles are the colleague's mechanics, not a reimplementation

Their subtitle path is the most-iterated code in their tool, and each detail is
load-bearing:

- **`\an5\pos(x,y)` on every dialogue line.** Anchoring by absolute centre is
  what stops libass drifting the text between frames.
- **Chain-link end times** — a word holds until the NEXT word starts, not until
  its own end. Without the overlap libass stacks lines on top of each other.
- **A hard right clamp at the packshot.** Otherwise the last line's tail draws
  over the end card.
- **A cap on the hold (`MAX_HOLD_S`, 2026-08-21).** Chain-linking is right where
  there is speech and wrong across a pause: on LME108 the last word of scene 0
  was 25 seconds from the next one, so "UP" sat over three silent scenes and
  shipped that way into the draft. A word now holds until the next one starts or
  0.8s past its own end, whichever comes first — normal inter-word gaps are far
  shorter, so the mechanic the chain-link protects is untouched.
- **No lead shift.** Whisper does put word starts slightly late; the colleague
  tried compensating 0.20s and reverted it because it looked worse. `lead_s`
  is 0 by decision, not by omission.
- **A lexicon pass**, because Whisper mangles exactly the words these ads are
  about. Note this is the OPPOSITE direction to the phonetic dictionary the
  owner dropped: that changed what the model *says*, this fixes what the
  transcriber *hears*.

Two things that differ per machine: the `ffmpeg` on PATH may have neither libass
nor drawtext — Homebrew's `ffmpeg` formula ships without them and keeps the
complete build keg-only — so `ffmpeg_with_libass()` searches PATH, the usual
install locations on macOS and Linux, and `$FJOR_STUDIO_FFMPEG`; and **Inter is
not installed** on most machines — `fc-match Inter` returns Verdana — so the
font ships in `assets/fonts/` and libass is pointed at it with `fontsdir`.
Without that the subtitles render in the wrong face and nothing reports an
error. All three prerequisites are checked at **intake**, because subtitles are
burned in `assembly`, after the clips are paid for.

### 3.10 The dashboard is stdlib, and the worker runs one job at a time

No web framework: this is a single-user tool bound to localhost, and a
dependency-free server is one less thing to install on the next machine. The
page is one file with no build step.

Jobs advance on a **single** background queue. A generation stage blocks for
minutes on a provider, and running several concurrently multiplies the ways a
crash can strand a paid task id. The queue is the honest model of the tool.

The media route serves only `plates/ clips/ draft/ finals/ review/ ref/ audio/`
inside a job directory, and resolves the path before checking it is still under
that root. `config/auth.yaml` holds live keys; the dashboard must not be a file
browser, and there are tests that try to make it one.

It also **serves byte ranges**, which is not optional for video. A response
declaring `Accept-Ranges: none` is one Chrome will not seek even after buffering
the whole file — measured on the draft player, a seek to 4s left `currentTime`
at 0 — so the gate whose job is reviewing the cut could only play it straight
through. Files are streamed in chunks rather than read into memory.

**Approving a money gate asks first.** One click at `GATE_PLATES` commits the
whole video budget and KIE has no cancel endpoint, so the confirmation names the
amount on the button itself. A gate with nothing to spend says so instead.

**Polling does not fight the person using the page.** The page rebuilt itself
every four seconds whether or not anything had moved, which destroyed the draft
`<video>` element — so the cut restarted from zero on every poll and could not
be watched through. A gate is exactly when a producer sits and watches, and
exactly when the job is *not* changing, so a poll that finds no change now
renders nothing at all. When a render is genuinely warranted, the draft player
is re-parented rather than re-emitted, and open panels are restored — verified
in a browser: a forced re-render left playback at 20.0s on the same element.

**An action that fails without changing job state is shown.** Approving off a
gate, or a bad revise target, is recorded by the worker and was previously
rendered nowhere — it looked like nothing had happened.

**A job starts from a pasted creative name and a dropped file.** The name
carries the id, week, concept and producer — four fields a producer would
otherwise retype from a sheet they already have open. The `s-` token is read but
never acted on: both sizes are always built, so it only says which one they
happened to copy.

**The target vertical stays an explicit field.** Its prefix suggests one and the
dialog selects it, but deriving is not the same as choosing: it is the largest
single input to the writer, and an adaptation can legitimately target a vertical
other than the one its id came from. A hand-picked choice survives re-typing the
name, and a mismatch is flagged rather than blocked — the id comes from the name
and the delivery folder from the vertical, so the file would land somewhere its
own name does not suggest.

The reference is dropped, not typed. A browser will not hand over a dropped
file's path — there isn't one to give — so the bytes are uploaded, streamed to
disk, and **probed before being accepted**: a file with no video stream fails in
the dialog rather than three stages into a paid run.

**Scene count is not asked for.** A producer does not sit and count shots, and
the analysis already lists the reference's. Absent an explicit override the
writer is told to follow the reference's own shot list. The producer's brief is
passed to the writer and flagged as outranking the house guidance where they
disagree — a brief collected and ignored would be worse than not asking.

### 3.11 Subtitle timings belong to an EDIT, not to a job

Word timings are positions on a timeline, and the timeline moves whenever the
cut changes. Adding a 0.5s crossfade across five joins pulled the last shot 2.5
seconds earlier on LIPIL025, and the cached transcript replayed the old timings
over the new cut — drifting further with every transition, silently. The cache
is keyed on a signature of the edit (clips, crossfade, demo, packshot), and
`finalize` refuses to deliver when the signature does not match the cut it is
about to build.

Verified by re-transcribing the delivered file and comparing: 78 of 78 words,
zero drift.

### 3.12 Secrets

The colleague's kit export carries **live plaintext API keys**. `auth.yaml` is
gitignored, and `Config.redacted()` is the only representation that may be
printed. `fjor-studio config` uses it.

---

### 3.4i Niche knowledge is ported, never invented

The pipeline knew a vertical's PREFIX and FOLDER and nothing else. Everything
that decides whether a creative is right for its niche -- the mechanic, the words
that must appear, the words that break it, the objections kept verbatim, who may
be on camera -- lived in documents beside the work and reached a creative only if
a producer retyped some of it into a brief.

- **Ported, and the provenance is the value.** Ten entries come from
  fjor-video, which carries them from the client's own meta-templates; two more
  are distilled from the colleague's `NICHE_TEMPLATES`. A plausible invention
  here outranks both the reference and the producer's note, and nobody
  downstream can tell an invented rule from a client one. A drift test compares
  every ported field against its source, because a stale niche rule is worse
  than none: it reads as current.
- **The negatives are appended by the CODE, not asked of the writer.** The
  source templates call that list mandatory for every generation, and a list a
  language model is asked to reproduce is a list that drifts. The niche's own
  hero props travel with it as `keep_out_of_negatives` -- a mat in back pain,
  walking shoes in apostolic -- so the exclusion cannot remove the subject.
- **Lore does not outrank the reference**, and the block says so where the
  writer reads it: mirror the reference, change only what breaks the niche.
- **A registered vertical may have no lore**; it simply gets none. Lore for a
  vertical nobody registered is REFUSED at config load, because it would never
  be read, and a silent no-op is how a producer comes to believe a niche is
  configured when it is not.
- **A diet vertical forbids the time lexicon an activity vertical requires.**
  "Just five minutes a day" IS the offer in back pain and apostolic walking; the
  identical phrase in Mediterranean or Cortisol makes a food product sound like
  an exercise ad and is categorically banned, with frequency replacing it. Both
  halves are held by one test, because that is the rule that erodes when someone
  edits one family thinking about the other.
- **Three entries carry their source's own warning** and it is preserved:
  `lipedema_pilates`, `yoga_men` and `bp_walking` are house-pattern
  extrapolation rather than client knowledge. Their mechanics and safety blocks
  are the parts to trust.

### 3.5d A tool must open before it is configured

A shipped zip, unpacked and asked what a fresh deploy sees, could not render its
dashboard at all: backends were constructed when a studio was OPENED, so a
machine with no keys threw before the page existed -- and the controls that LOAD
the keys and set the delivery folder are both on that page. The first hour of
every deployment would have been spent on a traceback.

- **A key is needed to RUN a job, not to look at one.** Backends are built
  lazily, on first use.
- **The protection that eagerness gave is kept, at the same moment.** Building
  early was what guaranteed a missing key surfaced before money was spent, so
  `check_all()` does it at INTAKE, beside the delivery-root check. Same
  guarantee, without holding the whole tool hostage to it.
- **Laziness is scoped to where there is something to look at.** The DASHBOARD
  opens with no keys; the CLI proves its routing up front, because every command
  it offers either spends money or resumes something that did, and a job created
  only to fail is litter.
- **Configuration a deployment needs is a CONTROL, not an error message.** No
  delivery root is a setting at the top of the page with a live preview of where
  finals will land -- not a refusal three clicks later naming a YAML file. The
  refusal stays underneath it, at intake, because a run that discovers it at the
  end has already been paid for.

## 4. Module map

```
fjor_studio/
  app.py               open_studio / new_job -- the one way in
  ids.py               id allocation against the delivery tree
  engine/pipeline.py   states, gates, revision map          (~120 loc)
  engine/job.py        Job / Scene / Submission, ledger
  engine/store.py      one dir per job, atomic job.json
  engine/engine.py     run / approve / revise / retry / reassemble / cancel
  gen/base.py          Backend ABC, GenResult, error taxonomy
  gen/registry.py      CAPABILITIES map, routing validation, Router
  gen/http.py          retrying HTTP + the KIE `code`-in-a-200 envelope guard
  gen/mock.py          deterministic backend, scriptable replies
  qa/verdict.py        verdict parsing; technical vs real failure
  qa/policy.py         speech-only guard, regeneration policy
  gen/kie.py           images + video; the per-model reference-field table
  gen/gemini.py        analysis, prompt writing, media QA, TTS
  assemble.py          ffmpeg: normalise, concat, packshot, subtitles, overlays
  subtitles.py         transcribe, repair, ASS, burn
  dashboard/server.py  stdlib HTTP: state, actions, media
  dashboard/worker.py  one background queue, one job at a time
  dashboard/page.py    the single page
  qa/prompts.py        the plate and clip QA system prompts, UGC and banner
  naming.py            the final-filename convention: build and parse
  derive.py            a finished job as the start of the next one
  costs.py             measured rates, forecasts that admit ignorance
  banner.py            the canvas, the survival check, the two playbooks
  refkind.py           ugc or replica: what a reference IS, and its style frames
  kit.py               keys the producer brings, held in memory, never written
  lore.py              what a vertical IS, in the writer's hands
  drivers.py           motion drivers: engine, length, the writer's rules
  stages/paid.py       THE path through which money is spent
  stages/steps.py      one handler per state
  stages/banner_steps.py  the four stages banner mode does differently
  stages/registry.py   pipeline state -> handler
  preflight.py         checks that report whether they were able to look
  config.py            pipeline.yaml / models.yaml / auth.yaml
  cli.py               new / run / approve / revise / retry / status / config
```

551 tests, all of which execute the code rather than inspecting it.

---

## 5. State of play

**Working now:** the whole pipeline end to end on the mock backend, all three
gates, revisions, QA-driven plate regeneration, crash recovery around a paid
generation, per-second forecasting, delivery into the live week-folder
convention with correct filenames and collision-safe ids, the CLI, key
redaction.

**First real creative: LIPIL025**, delivered 2026-08-18 — a 39s lipedema-pilates
adaptation of a 42s reference, 987.2 credits, into
`VIDEO/LIPEDEMA PILATES/34 week/`. What it proved, beyond the happy path:

- the clip forecast at `GATE_PLATES` (843.2 cr) matched the charge to the credit
- QA had no system prompt, so every verdict came back `unclear` — it was running,
  costing time, and checking nothing
- `revise --scene` was recorded and ignored by every stage
- the disclaimer overlay tracked for 34 seconds and stopped dead at the packshot
  boundary, so the end card shipped without it. A single-frame PNG needs
  `-loop 1`; the file looked correct everywhere anyone had thought to look

**Live backends:** **KIE** (images + video) and **Gemini** (analysis, prompt
writing, media QA, TTS). Both were contract-probed against the real APIs without
generating anything — every probe held the *same* field invalid, which is the
only thing separating a probe from a paid job. Gemini's text, vision and
QA-verdict paths are additionally verified against real responses.

**Still declared but not implemented:** fal, openai, anthropic, elevenlabs,
higgsfield. Routing to one fails with "declared but not yet implemented".
`registry.build()` also cross-checks the declared `CAPABILITIES` map against
what a backend's own `capabilities()` actually serves, so routing into that gap
fails at startup rather than mid-run after earlier stages have been paid for.

**Measured rates.** `nano-banana-pro` is 18.0 cr/plate at 1K and Seedance is
24.8 cr/s at 720p — both from real charges on LIPIL025, both matching the gate's
forecast exactly. Kling, seedance-mini and seedance-2 are still unpriced and say
so.

See `PORTING_NOTES.md` for what remains in their tool, and `PROVIDER_FACTS.md`
for the API facts that were expensive to learn.

---

## 6. Rules that must not be silently reverted

1. `GATE_PLATES` and `GATE_DRAFT` are unskippable. Any config that tries fails
   loudly. `GATE_PLAN` and `GATE_CLIPS` may be skipped: neither guards money.
2. `run_generation` is the only caller of `backend.submit`, and it persists the
   task id before polling.
3. A rate goes in `costs.RATES` only if it is traced to a real charge. Unpriced is
   an honest answer; an invented number is not.
4. A check that could not look never reports all-clear.
5. `auth.yaml` is never committed and never printed unredacted, and no object
   holding keys may rely on a default repr: `Config` redacts itself in every
   rendering, because a repr is not asked for, it happens. Keys are better
   supplied as a KIT the producer brings, held in memory and never written.
6. Delivery never hard-deletes; a replaced file goes to `_to_delete/`.
7. Ids are allocated against the delivery tree as well as the local jobs
   directory, and the filename convention is matched exactly.
8. Every URL that reaches an exception, a log or `job.json` goes through
   `http.safe_url()`. Gemini takes its key in the query string, so an
   unredacted URL in an error message is a leaked credential on disk.
9. Contract probes keep the SAME field invalid in every request. A probe made
   "more realistic" is a paid job.
10. The disclaimer PNGs in `assets/disclaimers/` are approved compliance assets.
    They are overlaid, never regenerated or re-typeset — and every overlay input
    is read with `-loop 1`, or it silently stops partway through the video.
11. Anything a paid stage needs is validated at intake. A prerequisite
    discovered in `assembly` fails a job that has already spent its budget.
12. A crossfaded cut's length is MEASURED, never summed — every transition eats
    its own duration, and the subtitle clamp reads that number.
13. The dashboard's media route serves job media only, never config or job.json.
14. The edit is written only through `engine.set_edit`, only at a gate, and only
    after validation. A dropped shot is dropped from the cut, never deleted.
15. Every encode is pinned to `assemble.PIX_FMT` (4:2:0). An RGBA overlay or the
    `ass` filter will otherwise negotiate the chain up to 4:4:4, which libx264
    encodes happily and no browser decodes.
16. A subtitle word holds until the next word or `MAX_HOLD_S`, whichever is
    sooner. Chain-linking across a silence leaves a word on screen for as long
    as the silence lasts.
17. Movement has one source per shot. A driver and a transformation in the
    same shot is refused before the clips are bought.
18. A QA verdict is accepted, never erased. `waive` is per-scene, needs a
    reason, and leaves the finding in the report and the shipped manifest.
19. Whatever a derived job inherits, it inherits WHOLE. The cast travels with
    the prompts that name it, or the child is unanchored and every plate
    invents a face. Nothing unanchorable is ever paid for. Whether the FACE
    travels is the producer's call, not a default.
20. Register-and-attach is one action. A driver registered without shots is a
    video copied into the job that changes nothing, and a plan gate approved
    with the shots not yet retimed to the driver's length.
21. A stop leaves the producer somewhere they can decide. A stage whose remedy
    lives at a gate raises `Blocked` and the job lands there; every route an
    error names is reachable from where the producer is standing, and offered
    wherever that error is shown.
22. The banner is RESTORED, not merely guarded. The model's return is judged
    for being the same picture, our own banner is composited back over its
    rectangle, and the strict pixel check then proves it. Nothing inside the
    banner changes. The expansion is held to zero changed
    pixels there; the one edit that is allowed -- the legal small print -- is a
    separate pass over a band named in advance, and a licensed pass that changed
    nothing in its band is reported as not having run.
