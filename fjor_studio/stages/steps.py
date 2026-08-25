"""Stage handlers, one per pipeline state.

Each is re-runnable: a stage interrupted by a crash simply runs again, and work
already on disk (a plate, a paid clip) is reused rather than re-bought.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import costs, naming
from ..assemble import (SIZES, AssembleError, build_final, disclaimer_for,
                        music_for, packshot_for)
from ..engine.engine import StageContext
from ..engine.job import Scene
from ..gen.base import GenError
from ..qa import (QaSettings, Verdict, apply_voice_context, blocking_scenes,
                  parse as parse_verdict, should_regenerate, technical_failure)
from ..qa.prompts import system_for, user_for

# ---------------------------------------------------------------- helpers ---


def _options(ctx: StageContext, key: str) -> Dict[str, Any]:
    """Per-call model knobs from models.yaml `options`."""
    return dict((ctx.config.models.get("options") or {}).get(key) or {})


def _qa_settings(ctx: StageContext) -> QaSettings:
    return QaSettings.from_config((ctx.config.pipeline or {}).get("qa"))


def _voice_is_external(ctx: StageContext) -> bool:
    """True when the voice comes from a separate track, so the clip is MEANT to
    be silent and a 'nobody speaks' QA verdict is the plan, not a defect."""
    src = str(((ctx.config.pipeline or {}).get("voice") or {}).get("source", "seedance"))
    return src.strip().lower() not in ("seedance", "video", "in-model")


def _write_review(ctx: StageContext, name: str, payload: Dict[str, Any]) -> Path:
    path = ctx.dir("review") / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    ctx.job.add_artifact("review", f"review/{name}")
    return path


def _revision(ctx: StageContext, stage: str) -> Dict[str, Any]:
    """The producer's most recent revision request aimed at this stage.

    Without this, `revise --scene 3` recorded the scene and every stage ignored
    it: the redo either re-ran everything or -- because finished work is skipped
    -- nothing at all. The CLI accepted a flag that did nothing."""
    from ..engine.pipeline import REVISABLE
    for rev in reversed(ctx.job.revisions):
        target = (REVISABLE.get(rev.get("gate")) or {}).get(
            str(rev.get("what", "")).lower())
        if target == stage:
            return rev
    return {}


def _targets(ctx: StageContext, stage: str) -> Tuple[List[int], str]:
    """(scene indices to redo, the producer's note). An empty list means the
    stage runs normally and skips whatever is already on disk."""
    rev = _revision(ctx, stage)
    if not rev or rev.get("consumed"):
        return [], ""
    return [int(i) for i in (rev.get("scenes") or [])], str(rev.get("note") or "")


def _consume(ctx: StageContext, stage: str) -> None:
    """Mark the revision done, so a later re-run of this stage does not redo it
    again and pay twice."""
    rev = _revision(ctx, stage)
    if rev:
        rev["consumed"] = True


def _steer(prompt: str, note: str) -> str:
    """A revision note is an instruction to the generator, appended rather than
    replacing -- the rest of the prompt is what the producer already approved."""
    return f"{prompt}\n\nREVISION NOTE (follow this): {note}" if note else prompt


def _run_media_qa(ctx: StageContext, scene, kind: str,
                  media_path: Path, prompt: str) -> Optional[Verdict]:
    """kind is 'plate' or 'clip'. A QA call that cannot run yields a technical
    verdict, which never costs a regeneration.

    Returns None when QA is switched OFF -- deliberately, rather than a passing
    verdict. A disabled check that records "ok" is a guard structurally
    incapable of failing, and everything downstream would read that stored
    verdict as evidence the media was examined."""
    settings = _qa_settings(ctx)
    if not settings.runs_for(kind):
        return None
    model = (ctx.config.models.get("models") or {}).get("qa", "")
    params = _options(ctx, "qa")
    params.update({"qa_kind": kind,
                   "scene": getattr(scene, "idx", getattr(scene, "id", None)),
                   "system": system_for(kind)})
    try:
        result = ctx.providers.backend_for("analysis").generate(
            "analysis", model, user_for(kind, prompt),
            params=params, medias=[str(media_path)])
    except Exception as exc:  # noqa: BLE001
        return technical_failure(str(exc), model)
    verdict = parse_verdict(result.text, model)
    if kind == "clip":
        verdict = apply_voice_context(verdict, _voice_is_external(ctx))
    return verdict


# ----------------------------------------------------------------- stages ---


def _check_delivery_root(ctx: StageContext) -> None:
    """Fail at INTAKE if there is nowhere to deliver to.

    Same reasoning as the subtitle prerequisites below: `delivery` runs after
    everything has been paid for, and a studio checked out on a new machine has
    no root until someone sets one. Discovered here it costs nothing; discovered
    at the end it costs the whole run."""
    from ..config import MissingDeliveryRoot
    try:
        root = ctx.config.delivery_root
    except MissingDeliveryRoot as exc:
        raise GenError(f"intake: {exc}")
    # The root itself may not exist yet -- a new studio creates it on its first
    # delivery. Its PARENT must, though: that is what separates "nothing has
    # shipped yet" from a typo, or a network volume that is not mounted.
    if not root.exists() and not root.parent.exists():
        raise GenError(
            f"intake: neither the delivery root {root} nor the folder that "
            f"would contain it exists. Check `root:` in config/delivery.yaml "
            f"(or $FJOR_STUDIO_DELIVERY_ROOT), and that the volume is mounted.")


def _check_subtitle_prerequisites(ctx: StageContext) -> None:
    """Fail at INTAKE if subtitles cannot possibly be made.

    They are burned in `assembly`, which runs after the clips are paid for. A
    missing key or an ffmpeg without libass discovered there fails a job that
    has already spent its whole budget, and the only way forward is to turn
    subtitles off and re-cut. Checked here, it costs nothing."""
    _style, enabled = _subtitle_settings(ctx)
    if not enabled:
        return
    if not ((ctx.config.auth or {}).get("openai") or {}).get("api_key"):
        raise GenError(
            "subtitles are enabled but auth.yaml has no openai.api_key for "
            "transcription. Add the key, or set subtitles.enabled: false in "
            "pipeline.yaml.")
    from ..assemble import ffmpeg_with_libass
    ffmpeg_with_libass()          # raises with its own remedy if none is found
    font = Path(ctx.config.assets_dir) / "fonts"
    if not any(font.glob("*.tt*")):
        raise GenError(f"subtitles are enabled but {font} has no font file. "
                       f"libass would fall back to another face silently.")


def intake(ctx: StageContext) -> None:
    """Take the reference video into the job so later stages never depend on a
    path outside it."""
    _check_delivery_root(ctx)
    _check_subtitle_prerequisites(ctx)
    src = ctx.job.intake.get("reference")
    if not src:
        raise GenError("intake: no reference video given "
                       "(intake['reference'] is the colleague's Step 1 upload)")
    src_path = Path(src)
    if not src_path.exists():
        raise GenError(f"intake: reference video not found: {src_path}")
    dest = ctx.dir("ref") / src_path.name
    if not dest.exists():
        shutil.copy2(src_path, dest)
    ctx.job.intake["reference_local"] = f"ref/{dest.name}"
    ctx.job.add_artifact("ref", f"ref/{dest.name}")
    for i, shot in enumerate(ctx.job.intake.get("screenshots") or []):
        p = Path(shot)
        if p.exists():
            target = ctx.dir("ref") / f"screenshot_{i:02d}{p.suffix}"
            if not target.exists():
                shutil.copy2(p, target)
            ctx.job.add_artifact("ref", f"ref/{target.name}")


ANALYSIS_BRIEF = """Analyse this reference video ad completely -- picture AND audio.

Report, in plain prose:

1. STRUCTURE -- an ordered shot list. For each shot: approximate start and end
   in seconds, what is on screen, the camera framing, and whether anyone speaks.
2. SPOKEN SCRIPT -- every spoken line, verbatim, in order.
3. ON-SCREEN TEXT -- every caption, headline and burnt-in disclaimer, verbatim.
4. CAST -- for each person: apparent age bracket, build, hair, wardrobe.
5. SETTING -- location, key props, lighting, colour palette.
6. PRODUCT SHOTS -- flag every shot that shows the advertiser's OWN product:
   app screens, packaging, dashboards, progress cards, end cards, CTA screens.
   Give their timestamps explicitly. These will be replaced wholesale, so being
   exact about which shots they are matters more than describing them.
7. WHAT MAKES IT WORK -- the hook, the pacing, the promise, the proof.

Reference kind: {ref_kind}. Pass {n} of {passes}."""


def _analysis_brief(ref_kind: str, n: int, passes: int) -> str:
    return ANALYSIS_BRIEF.format(ref_kind=ref_kind, n=n, passes=passes)


def analysis(ctx: StageContext) -> None:
    """Step 2: whole-file video analysis, picture and audio together."""
    depth = str(((ctx.config.pipeline or {}).get("analysis") or {}).get("depth", "default"))
    ref_kind = str(((ctx.config.pipeline or {}).get("analysis") or {}).get("ref_kind", "ugc"))
    if depth not in ("default", "deep", "bulletproof"):
        raise GenError(f"analysis.depth '{depth}' is not one of "
                       f"default | deep | bulletproof")
    ref = ctx.job_dir / ctx.job.intake["reference_local"]
    passes = {"default": 1, "deep": 2, "bulletproof": 3}[depth]
    model = ctx.config.model_for("analysis")
    texts: List[str] = []
    for n in range(passes):
        params = _options(ctx, "analysis")
        params.update({"pass": n + 1, "ref_kind": ref_kind})
        result = ctx.providers.backend_for("analysis").generate(
            "analysis", model, _analysis_brief(ref_kind, n + 1, passes),
            params=params, medias=[str(ref)])
        texts.append(result.text)
        if result.credits:
            ctx.job.spend("analysis", f"pass {n + 1}", result.credits, result.backend)
    ctx.job.analysis = {"depth": depth, "ref_kind": ref_kind,
                        "passes": texts, "text": texts[-1]}
    path = ctx.dir("analysis") / "analysis.json"
    path.write_text(json.dumps(ctx.job.analysis, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    ctx.job.add_artifact("analysis", "analysis/analysis.json")


def prompts(ctx: StageContext) -> None:
    """Step 3: the text model turns the analysis into one image prompt and one
    video prompt per GEN block."""
    model = ctx.config.model_for("text")
    count = ctx.job.intake.get("scene_count")      # None = the reference decides
    params = _options(ctx, "text")
    params.update({"self_audit": bool(((ctx.config.pipeline or {}).get("prompts") or {})
                                      .get("self_audit", True)),
                   "scene_count": count})
    result = ctx.providers.backend_for("text").generate(
        "text", model, _prompts_brief(ctx, count), params=params)
    if result.credits:
        ctx.job.spend("prompts", "prompt writing", result.credits, result.backend)
    scenes, notes = _parse_scene_plan(result.text, count or 5,
                                      _duration_bounds(ctx))
    cast, cast_notes = _parse_cast(result.text, scenes)
    for note in notes + cast_notes:
        ctx.job.add_event("plan_adjusted", note)
    if _anchoring(ctx):
        ctx.job.cast = cast
        if cast:
            ctx.job.add_event(
                "cast", f"{len(cast)} recurring character(s): "
                        f"{', '.join(c['id'] for c in cast)} — each gets one "
                        f"portrait, attached to every shot they are in")
    # keep anything already generated for a scene that survives a revision
    existing = {s["idx"]: s for s in ctx.job.scenes}
    for spec in scenes:
        prior = existing.get(spec["idx"])
        scene = Scene(**prior) if prior else Scene(idx=spec["idx"])
        scene.image_prompt = spec["image_prompt"]
        scene.video_prompt = spec["video_prompt"]
        scene.characters = list(spec.get("characters") or [])
        scene.voice = str(spec.get("voice", "on_camera"))
        scene.line = str(spec.get("line", ""))
        scene.duration_s = float(spec.get("duration_s", 5))
        ctx.job.put_scene(scene)
    ctx.job.plan = {"scene_count": len(scenes), "text": result.text}
    _consume(ctx, "prompts")


PROMPTS_BRIEF = """You are adapting the reference ad analysed below into a NEW ad
for a different programme. Write the generation prompts for it.

TARGET PROGRAMME: {vertical}

ADAPT, DO NOT COPY. Keep what makes the reference work -- its structure, pacing,
hook shape and shot rhythm. Replace its subject matter with the target programme.

HARD RULES

1. A vertical is a THEME, not an identity. The person on screen is an ordinary
   adult who wants to get fitter -- mostly women, some men. She is NOT a patient,
   NOT a clinician, and NOT a member of any group the programme names. Never
   depict a medical setting, a diagnosis, a symptom, or a treatment.
2. NO product shots. The reference's own app screens, progress cards, dashboards
   and end cards are being replaced by our packshot, which is appended
   automatically at assembly. Do not write a scene for any of them, and do not
   put a phone, an app screen or a UI in any shot.
3. No medical claims. Nothing may diagnose, treat, cure or prevent anything.
   Weight in lbs, never kg.
4. No brand logos, no readable trademarks, no visible text on clothing.
5. Every spoken line goes inside double quotes in the video prompt, so the video
   model speaks it. Keep lines short enough to say in the shot's duration at
   roughly 2.5 words per second.
6. Vertical 9:16 framing throughout. No on-screen captions or burnt-in text --
   the disclaimer is overlaid separately at assembly.
7. SAY WHO IS SPEAKING AND HOW, with the `voice` field:
   - "on_camera" — the person in the shot speaks the line. The video model
     renders the speech with the picture and the lips match.
   - "vo" — a voice is heard but nobody on screen is speaking. The clip is
     generated SILENT and the line is spoken separately, then laid over it.
   - "silent" — nothing is heard but the room.
   This is not a stylistic choice. Measured on BPW026: an on-camera studio line
   generated fine, while the same B-roll shot with a voiceover was REFUSED three
   times for copyright, and passed immediately once the audio was switched off.
   A voice with no visible speaker makes the model invent a soundtrack, and that
   is what gets the whole generation rejected.
   Put the spoken words in `line`, and keep them out of video_prompt for a "vo"
   shot -- the model must not be told to say something it is generating silent.

{brief_block}FIRST, THE CAST. List everyone who appears in more than one shot. Each gets an
`id` (short, lowercase, e.g. "host", "runner") and a `description` detailed
enough to generate a portrait from: apparent age, build, hair, face, wardrobe.
Someone who appears in exactly one shot does NOT need to be in the cast.

Then WRITE {count_line} For each:
- image_prompt: the still that opens the shot -- the literal FIRST FRAME the
  video is animated from. Describe the person, wardrobe, setting, framing and
  light, and CRUCIALLY the starting body position of whatever happens next: if
  the shot is a side-lying leg lift, the frame shows her already lying on her
  side; if it is a kickback on hands and knees, she is already on hands and
  knees. A frame showing someone standing when the shot begins on the floor
  forces the video model to invent the transition, and it does it badly.
  Be consistent across scenes -- same person, same room, same wardrobe -- unless
  the reference cuts away.
- video_prompt: what happens in the shot, including any spoken line in quotes.
- voice: "on_camera", "vo" or "silent" (see rule 7).
- line: the words spoken over this shot, or "" for a silent one.
- characters: the cast ids visible in this shot, in order of prominence. This is
  what keeps the same person looking like the same person: a portrait is
  generated once per cast member and attached to every shot they are in. Leave
  it empty only for a shot with nobody in it.
- duration_s: between 4 and 15. This is a HARD limit of the video model, not a
  preference: it cannot make a clip shorter than 4 seconds. If the reference
  cuts faster than that, do NOT copy the cut rate -- give the shot at least 4
  seconds and let the edit carry the pace. A shot you would have written as 2
  seconds should either be 4, or be folded into the shot next to it.

Answer ONLY with JSON:
{{"cast":[{{"id":"host","description":"…"}}],
  "scenes":[{{"idx":0,"characters":["host"],"voice":"on_camera","line":"…",
             "image_prompt":"…","video_prompt":"…","duration_s":6}}]}}

=== ANALYSIS OF THE REFERENCE ===

{analysis}"""


def _prompts_brief(ctx: StageContext, count: Optional[int]) -> str:
    vertical = ctx.job.intake.get("vertical_brief") or \
        str(ctx.job.intake.get("vertical", "")).replace("_", " ")
    note = (ctx.job.intake.get("brief") or "").strip()
    # A revision aimed at this stage carries the reason it was sent back. It was
    # being recorded and then ignored -- the same shape as `revise --scene`
    # doing nothing -- so a producer rewrote the plan and got the same plan.
    _redo, revision_note = _targets(ctx, "prompts")
    if revision_note:
        note = (note + "\n\n" + revision_note).strip()
    brief_block = ""
    if note:
        # placed last of the instructions and flagged as outranking them,
        # because a producer's note is the most specific thing in the prompt
        brief_block = (
            "THE PRODUCER'S BRIEF FOR THIS ONE -- it is more specific than the\n"
            "guidance above, so where they conflict, follow this:\n\n"
            f"{note}\n\n")
    # No count given means the reference decides. A producer does not sit and
    # count shots, and the analysis above already lists them.
    count_line = (f"{count} SCENES." if count else
                  "AS MANY SCENES AS THE REFERENCE HAS -- follow its shot list\n"
                  "and its rhythm rather than a number. Typically 4-7.")
    return PROMPTS_BRIEF.format(vertical=vertical, count_line=count_line,
                                brief_block=brief_block,
                                analysis=ctx.job.analysis.get("text") or "")


def _duration_bounds(ctx: StageContext) -> Tuple[float, float]:
    raw = ((ctx.config.pipeline or {}).get("prompts") or {}).get("duration_s") or {}
    return float(raw.get("min", 4)), float(raw.get("max", 15))


def _parse_cast(text: str, scenes: List[Dict[str, Any]]
                ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The declared cast, narrowed to who the scenes actually reference.

    A cast member nobody appears with would cost a plate for nothing, and a
    scene naming someone who was never declared cannot be anchored -- both are
    reported rather than quietly dropped."""
    notes: List[str] = []
    try:
        data = json.loads(text)
        declared = data.get("cast") or [] if isinstance(data, dict) else []
    except Exception:  # noqa: BLE001
        declared = []
    used = {c for s in scenes for c in s.get("characters") or []}
    cast, seen = [], set()
    for entry in declared:
        cid = str((entry or {}).get("id", "")).strip().lower()
        if not cid or cid in seen:
            continue
        seen.add(cid)
        if cid not in used:
            notes.append(f"cast '{cid}' appears in no scene -- no portrait bought")
            continue
        cast.append({"id": cid,
                     "description": str((entry or {}).get("description", "")).strip()})
    for missing in sorted(used - seen):
        notes.append(f"scene(s) reference '{missing}', which the cast does not "
                     f"declare -- those shots go unanchored")
    return cast, notes


def _parse_scene_plan(text: str, fallback_count: int,
                      bounds: Tuple[float, float] = (4.0, 15.0)
                      ) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The text model is asked for JSON. When it answers with something else we
    fall back to a flat plan rather than failing the job -- but the fallback is
    recorded, never silent.

    Durations are CLAMPED here, not merely requested in the prompt. The writer
    is told the legal range and will still sometimes mirror a reference's quick
    cuts -- LIPIL050 came back with 2s, 1s and 2s shots and died inside `clips`,
    after five plates had been bought. A model instruction is a request; the
    provider's 4-15s floor is a fact, and it belongs where the plan is read.

    Returns (scenes, notes) -- every clamp is reported, because silently
    stretching a 1s cut to 4s changes the pacing the writer intended."""
    lo, hi = bounds
    notes: List[str] = []

    def fit(idx: int, value: Any) -> float:
        try:
            d = float(value)
        except (TypeError, ValueError):
            d = lo
            notes.append(f"scene {idx}: duration {value!r} is not a number, using {lo}s")
            return d
        if d < lo:
            notes.append(f"scene {idx}: {d}s is below the {lo}s floor, stretched to {lo}s")
            return lo
        if d > hi:
            notes.append(f"scene {idx}: {d}s is over the {hi}s ceiling, cut to {hi}s")
            return hi
        return d

    try:
        data = json.loads(text)
        raw = data["scenes"] if isinstance(data, dict) else data
        out = []
        for i, s in enumerate(raw):
            idx = int(s.get("idx", i))
            voice = str(s.get("voice", "on_camera")).strip().lower()
            if voice not in ("on_camera", "vo", "silent"):
                notes.append(f"scene {idx}: voice '{voice}' is not one of "
                             f"on_camera/vo/silent, treating it as on_camera")
                voice = "on_camera"
            out.append({"idx": idx,
                        "voice": voice,
                        "line": str(s.get("line", "")).strip(),
                        "characters": [str(c).strip().lower()
                                       for c in (s.get("characters") or [])
                                       if str(c).strip()],
                        "image_prompt": str(s.get("image_prompt", "")),
                        "video_prompt": str(s.get("video_prompt", "")),
                        "duration_s": fit(idx, s.get("duration_s", 5))})
        if out:
            return out, notes
    except Exception:  # noqa: BLE001
        pass
    notes.append("the plan did not parse as JSON -- falling back to a flat plan")
    return ([{"idx": i, "image_prompt": f"[unparsed plan] scene {i} plate",
              "video_prompt": f"[unparsed plan] scene {i} motion",
              "duration_s": max(lo, min(hi, 5.0)), "characters": [],
              "voice": "on_camera", "line": ""}
             for i in range(int(fallback_count or 3))], notes)


def gate_plan(ctx: StageContext) -> None:
    """Prep for the checkpoint before the first plate is bought."""
    image_model = ctx.config.model_for("image")
    backend = ctx.config.routing.get("image", "?")
    # the cast portraits are plates too -- a forecast that leaves them out is
    # the same under-quote §3.4 exists to prevent, just smaller
    lines = [costs.line("plates", backend, image_model, scene=s["idx"],
                        kind="image") for s in ctx.job.scenes]
    lines += [costs.line("plates", backend, image_model, kind="image")
              for _ in ctx.job.cast]
    f = costs.forecast(lines)
    ctx.job.forecasts["plates"] = f.as_dict()
    _write_review(ctx, "plan.json", {
        "cast": [{"id": c["id"], "description": c["description"]}
                 for c in ctx.job.cast],
        "scenes": [{"idx": s["idx"], "characters": s.get("characters") or [],
                    "image_prompt": s["image_prompt"],
                    "video_prompt": s["video_prompt"],
                    "duration_s": s["duration_s"]} for s in ctx.job.scenes],
        "plate_forecast": f.as_dict(),
    })


IDENTITY_ANCHOR = """IDENTITY ANCHOR — THIS OUTRANKS THE DESCRIPTION BELOW.

The attached reference image{plural} show{verb} exactly who to render. Match the
person 1:1. Do not improve, idealise, beautify, slim or rejuvenate them:

- face geometry: jaw, cheekbones, chin, forehead, the whole bone structure
- eyes: colour, shape, eyelid position, spacing, lines and shadows under them
- nose and mouth: shape, width, lip fullness, natural colour
- hair: colour, length, texture, hairline, volume, exactly as shown
- skin: tone, texture, pores, age markers
- build: weight distribution, body fat, muscle tone, proportions
- age: the age in the reference, not a younger version of it
- identity markers: moles, freckles, scars, asymmetry — keep them

Where the description below contradicts the reference image about WHO this
person is, THE IMAGE WINS. The description governs only their wardrobe, the
setting, the pose, the expression and the light.

"""

PORTRAIT_BRIEF = """A neutral identity reference photograph, not a scene.

{description}

Vertical 9:16. Head and upper body, facing camera, relaxed neutral expression,
even soft lighting, plain uncluttered background. Photographic and real: visible
skin texture, natural asymmetry, no retouching, no beauty filter, no stylisation.
No text, no logos, no props. This image exists to fix who this person is, so
every feature must read clearly."""


def _anchoring(ctx: StageContext) -> bool:
    return bool(((ctx.config.pipeline or {}).get("characters") or {})
                .get("enabled", True))


def _anchor_limit(ctx: StageContext) -> int:
    return int(((ctx.config.pipeline or {}).get("characters") or {})
               .get("max_anchors", 2))


def _with_anchor(prompt: str, count: int) -> str:
    if not count:
        return prompt
    return IDENTITY_ANCHOR.format(plural="s" if count > 1 else "",
                                  verb="" if count > 1 else "s") + prompt


def cast_plates(ctx: StageContext) -> None:
    """One portrait per recurring character, before any scene is generated.

    This is what makes the same person the same person. Without it every plate
    invents a face from the same words, and a five-shot podcast ad comes back as
    three different women in the same navy top."""
    if not _anchoring(ctx):
        return
    # Before a single plate is bought: does every person the plan names have
    # someone to be? An unanchorable character is not a warning -- the plates
    # come back as different people and the whole spend is wasted. LME109 found
    # this the expensive way, at the gate, with five faces and five charges.
    declared = {str(c.get("id", "")).strip().lower() for c in ctx.job.cast}
    named = {str(c).strip().lower()
             for sc in ctx.job.scenes for c in (sc.get("characters") or [])}
    orphans = sorted(named - declared)
    if orphans:
        raise GenError(
            f"plates: the plan puts {', '.join(repr(o) for o in orphans)} on "
            f"screen, but the cast does not describe {'them' if len(orphans) > 1 else 'that person'}, "
            f"so nothing can hold the face steady and every plate would invent "
            f"a new one. Derive the job again if it came from another one (the "
            f"cast travels now), revise 'prompts' to declare the cast, or set "
            f"characters.enabled: false to accept text-only plates.")
    if not ctx.job.cast:
        return
    settings = _qa_settings(ctx)
    model = ctx.config.model_for("image")
    for raw in list(ctx.job.cast):
        ch = ctx.job.character(raw["id"])
        if ch.plate and (ctx.job_dir / ch.plate).exists():
            continue
        while True:
            out = ctx.dir("plates") / f"cast_{ch.id}.png"
            result = _paid(ctx, ch, "image", model,
                           PORTRAIT_BRIEF.format(description=ch.description),
                           out, stage="plates", put=ctx.job.put_character,
                           label=f"cast {ch.id}")
            ch = ctx.job.character(ch.id)
            ch.plate = f"plates/{Path(result.files[0]).name}"
            ch.attempts += 1
            verdict = _run_media_qa(ctx, ch, "plate",
                                    ctx.job_dir / ch.plate, ch.description)
            ch.qa = verdict.as_dict() if verdict else None
            ctx.job.put_character(ch)
            ctx.job.add_artifact("plates", ch.plate)
            ctx.store.save(ctx.job)
            if verdict is None or not should_regenerate(
                    verdict, "plate", ch.attempts, settings):
                break
            ctx.job.add_event("qa_regen", f"cast {ch.id}: portrait QA critical, "
                                          f"regenerating", issues=verdict.issues)
            ch.plate = None
            ctx.job.put_character(ch)
            ctx.store.save(ctx.job)


def plates(ctx: StageContext) -> None:
    """Step 4: one plate per scene, with per-photo QA and auto-regeneration.

    Cast portraits are generated first and attached to the scenes their people
    appear in, so identity survives the whole narrative."""
    cast_plates(ctx)
    settings = _qa_settings(ctx)
    model = ctx.config.model_for("image")
    limit = _anchor_limit(ctx)
    redo, note = _targets(ctx, "plates")
    if redo:
        ctx.job.add_event("revision_scope",
                          f"regenerating plates for scene(s) "
                          f"{', '.join(map(str, redo))}; the rest stay as approved",
                          scenes=redo, note=note)
    for raw in list(ctx.job.scenes):
        scene = Scene(**raw)
        if scene.idx in redo:
            scene.plate = None              # the producer asked for this one again
            ctx.job.put_scene(scene)
        if scene.plate and (ctx.job_dir / scene.plate).exists():
            continue                        # already made; a re-run does not re-buy
        while True:
            out = ctx.dir("plates") / f"scene_{scene.idx:02d}.png"
            anchors = ctx.job.anchors_for(scene, limit) if _anchoring(ctx) else []
            prompt = _with_anchor(
                _steer(scene.image_prompt, note if scene.idx in redo else ""),
                len(anchors))
            result = _paid(ctx, scene, "image", model, prompt, out,
                           medias=[str(ctx.job_dir / a) for a in anchors],
                           stage="plates")
            scene = ctx.job.scene(scene.idx)
            scene.plate = f"plates/{Path(result.files[0]).name}"
            scene.plate_attempts += 1
            verdict = _run_media_qa(ctx, scene, "plate",
                                    ctx.job_dir / scene.plate, scene.image_prompt)
            scene.plate_qa = verdict.as_dict() if verdict else None
            ctx.job.put_scene(scene)
            ctx.job.add_artifact("plates", scene.plate)
            ctx.store.save(ctx.job)
            if verdict is None or not should_regenerate(
                    verdict, "plate", scene.plate_attempts, settings):
                break
            ctx.job.add_event("qa_regen",
                              f"scene {scene.idx}: plate QA critical, regenerating "
                              f"(attempt {scene.plate_attempts + 1}/"
                              f"{settings.plates_max_attempts})",
                              scene=scene.idx, issues=verdict.issues)
            scene.plate = None
            ctx.job.put_scene(scene)
            ctx.store.save(ctx.job)
    _consume(ctx, "plates")


def gate_plates(ctx: StageContext) -> None:
    """Prep for the money gate: the plates, plus the FULL video forecast.

    This is the number that was under-quoted five-fold by a flat per-clip
    estimate. It is per-second, and it says so when a model has no measured
    rate rather than quietly leaving it out of the total."""
    video_model = ctx.config.model_for("video")
    backend = ctx.config.routing.get("video", "?")
    lines = [costs.line("clips", backend, video_model,
                        duration_s=float(s["duration_s"]), scene=s["idx"],
                        kind="video") for s in ctx.job.scenes]
    f = costs.forecast(lines)
    ctx.job.forecasts["clips"] = f.as_dict()
    blocked = blocking_scenes(ctx.job.scenes, "plate_qa")
    _write_review(ctx, "plates.json", {
        "plates": [{"idx": s["idx"], "plate": s["plate"], "qa": s["plate_qa"]}
                   for s in ctx.job.scenes],
        "clip_forecast": f.as_dict(),
        "spent_so_far": round(ctx.job.spent, 2),
        "qa_blocking_scenes": blocked,
    })
    if not f.complete:
        ctx.job.add_event(
            "forecast_incomplete",
            "the clip forecast is missing a measured rate for "
            + ", ".join(f"{i.backend}/{i.model}" for i in f.unknown_items)
            + " -- the total shown is a floor, not the price")


def clips(ctx: StageContext) -> None:
    """Step 5: animate each plate, with per-GEN QA and auto-regeneration."""
    settings = _qa_settings(ctx)
    model = ctx.config.model_for("video")
    redo, note = _targets(ctx, "clips")
    if redo:
        ctx.job.add_event("revision_scope",
                          f"regenerating clips for scene(s) "
                          f"{', '.join(map(str, redo))}; the rest stay as approved",
                          scenes=redo, note=note)
    for raw in list(ctx.job.scenes):
        scene = Scene(**raw)
        if scene.idx in redo:
            scene.clip = None
            ctx.job.put_scene(scene)
        if scene.clip and (ctx.job_dir / scene.clip).exists():
            continue
        if not scene.plate:
            raise GenError(f"scene {scene.idx}: no plate to animate")
        while True:
            out = ctx.dir("clips") / f"scene_{scene.idx:02d}.mp4"
            prompt = _steer(scene.video_prompt, note if scene.idx in redo else "")
            result = _paid(ctx, scene, "video", model, prompt, out,
                           params={"duration": scene.duration_s,
                                   # a voice with no visible speaker makes the
                                   # model invent a soundtrack, and that is what
                                   # gets the generation refused for copyright
                                   "generate_audio": scene.voice == "on_camera"},
                           medias=[str(ctx.job_dir / scene.plate)], stage="clips")
            scene = ctx.job.scene(scene.idx)
            scene.clip = f"clips/{Path(result.files[0]).name}"
            scene.clip_attempts += 1
            verdict = _run_media_qa(ctx, scene, "clip",
                                    ctx.job_dir / scene.clip, scene.video_prompt)
            scene.clip_qa = verdict.as_dict() if verdict else None
            ctx.job.put_scene(scene)
            ctx.job.add_artifact("clips", scene.clip)
            ctx.store.save(ctx.job)
            if verdict is None or not should_regenerate(
                    verdict, "clip", scene.clip_attempts, settings):
                break
            ctx.job.add_event("qa_regen",
                              f"scene {scene.idx}: clip QA critical, regenerating "
                              f"(attempt {scene.clip_attempts + 1}/"
                              f"{settings.clips_max_attempts})",
                              scene=scene.idx, issues=verdict.issues)
            scene.clip = None
            ctx.job.put_scene(scene)
            ctx.store.save(ctx.job)


def _paid(ctx: StageContext, scene, kind: str, model: str, prompt: str,
          out: Path, params=None, medias=None, stage: str = "",
          put=None, label: str = ""):
    from .paid import run_generation
    return run_generation(ctx, scene, kind, model, prompt, out,
                          params=params, medias=medias, stage=stage,
                          put=put, label=label)


def voiceovers(ctx: StageContext) -> None:
    """Speak the lines for shots generated silent.

    A "vo" shot has a voice but nobody on screen saying it, so the video model
    is told to make no audio at all -- asking it for a disembodied voice is what
    got BPW026 refused three times. The words are spoken here instead and laid
    over the clip at assembly."""
    pending = [Scene(**r) for r in ctx.job.scenes
               if r.get("voice") == "vo" and (r.get("line") or "").strip()
               and not r.get("vo_track")]
    if not pending:
        return
    try:
        backend = ctx.providers.backend_for("speech")
    except GenError as exc:
        raise GenError(
            f"{len(pending)} shot(s) need a voiceover but no speech backend is "
            f"routed: {exc}")
    model = ctx.config.model_for("speech")
    voice_cfg = ((ctx.config.pipeline or {}).get("voice") or {})
    for scene in pending:
        out = ctx.dir("audio") / f"scene_{scene.idx:02d}_vo.wav"
        result = backend.generate("speech", model, scene.line,
                                  params={"out_path": str(out),
                                          "voice": voice_cfg.get("name", "Kore")})
        scene.vo_track = f"audio/{out.name}"
        ctx.job.put_scene(scene)
        ctx.job.add_artifact("audio", scene.vo_track)
        if result.credits:
            ctx.job.spend("audio", f"scene {scene.idx} voiceover",
                          result.credits, result.backend, scene.idx)
        ctx.store.save(ctx.job)
    ctx.job.add_event("voiceovers", f"{len(pending)} line(s) spoken separately "
                                    f"for shots generated silent")


def gate_clips(ctx: StageContext) -> None:
    """A look at the shots before they are cut together.

    GATE_DRAFT reviews the cut and cannot be skipped; this one reviews the
    material. A shot that came back wrong is a re-buy either way, but seeing it
    here saves assembling around it -- and it is where the edit is set, so a
    scene can be dropped before it is ever in a timeline. Owner, 2026-08-21."""
    blocked = blocking_scenes(ctx.job.scenes, "clip_qa")
    in_cut = {s["idx"] for s in cut_scenes(ctx.job)}
    _write_review(ctx, "clips.json", {
        "clips": [{"idx": s["idx"], "clip": s["clip"], "qa": s["clip_qa"],
                   "duration_s": s.get("duration_s"), "line": s.get("line"),
                   "in_cut": s["idx"] in in_cut}
                  for s in ctx.job.scenes],
        "edit": edit_of(ctx.job),
        "qa_blocking_scenes": blocked,
        "spent": round(ctx.job.spent, 2),
        "spent_by_backend": ctx.job.spent_by_backend(),
    })


def gate_draft(ctx: StageContext) -> None:
    blocked = blocking_scenes(ctx.job.scenes, "clip_qa")
    in_cut = {s["idx"] for s in cut_scenes(ctx.job)}
    _write_review(ctx, "draft.json", {
        "draft": "draft/draft_watermarked.mp4",
        "clips": [{"idx": s["idx"], "clip": s["clip"], "qa": s["clip_qa"],
                   "in_cut": s["idx"] in in_cut}
                  for s in ctx.job.scenes],
        "edit": edit_of(ctx.job),
        "qa_blocking_scenes": blocked,
        "spent": round(ctx.job.spent, 2),
        "spent_by_backend": ctx.job.spent_by_backend(),
    })


def _formats(ctx: StageContext) -> List[str]:
    return list(((ctx.config.pipeline or {}).get("delivery") or {})
                .get("formats", ["9:16"]))


def _subtitle_settings(ctx: StageContext):
    """(style, enabled). pipeline.yaml `subtitles`, overridden by the edit."""
    from ..subtitles import SubtitleStyle
    raw = dict((ctx.config.pipeline or {}).get("subtitles") or {})
    raw.update(edit_of(ctx.job).get("subtitles") or {})
    if not raw.get("enabled", True):
        return None, False
    return SubtitleStyle(
        style=str(raw.get("style", "bold-pop")),
        colour=str(raw.get("colour", raw.get("color", "yellow"))),
        size=str(raw.get("size", "medium")),
        # Whisper does put word starts slightly late, and the colleague tried
        # compensating by 0.20s and reverted it: it looked worse. Left at 0
        # deliberately, not by omission.
        lead_s=float(raw.get("lead_s", 0.0)),
        font=str(raw.get("font", "Inter"))), True


def _edit_signature(ctx: StageContext, inputs: Dict[str, Any]) -> str:
    """What the subtitle timings depend on.

    Word timings are positions on a TIMELINE, and the timeline moves whenever
    the edit changes -- a 0.5s crossfade over five joins pulls the last shot
    2.5 seconds earlier. A cache that ignores this replays the old timings over
    the new cut and drifts further with every transition, silently."""
    import hashlib
    parts = [f"{s['idx']}:{s.get('clip')}" for s in cut_scenes(ctx.job)]
    parts += [f"xfade={inputs.get('crossfade_s')}",
              f"intopack={inputs.get('crossfade_into_packshot')}",
              f"demo={inputs.get('demo')}", f"trim={inputs.get('demo_trim_s')}",
              f"packshot={ctx.job.intake.get('packshot')}"]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def _transcribe_once(ctx: StageContext, video: Path, speech_end_s: float,
                     signature: str = ""):
    """Word timings for the whole cut, transcribed once per EDIT and cached.

    The audio is identical across delivery sizes -- only the ASS geometry
    differs -- so transcribing per size would pay twice for the same answer.
    The cache is keyed on the edit, so changing the cut re-transcribes and
    leaving it alone does not."""
    from ..subtitles import Word, extract_audio, lexicon_fix, transcribe
    cached = ctx.job.meta.get("subtitle_words")
    if cached is not None and ctx.job.meta.get("subtitle_sig") == signature:
        return [Word(**w) for w in cached]
    if cached is not None:
        ctx.job.add_event("transcript_stale",
                          "the edit changed, so the cached subtitle timings no "
                          "longer match the cut -- re-transcribing")
    key = ((ctx.config.auth or {}).get("openai") or {}).get("api_key", "")
    audio = extract_audio(video, ctx.dir("audio") / "speech.mp3")
    vocab = str(((ctx.config.pipeline or {}).get("subtitles") or {})
                .get("vocabulary_hint", "") or "")
    words = lexicon_fix(transcribe(audio, key, prompt=vocab))
    words = [w for w in words if w.start < speech_end_s]
    ctx.job.meta["subtitle_words"] = [w.__dict__ for w in words]
    ctx.job.meta["subtitle_sig"] = signature
    ctx.job.add_event("transcribed",
                      f"{len(words)} words for subtitles, up to {speech_end_s}s")
    return words


def _assembly_inputs(ctx: StageContext, size):
    """The packshot, the demo and the compliance overlays for one size."""
    assets = Path(ctx.config.assets_dir)
    intake = ctx.job.intake
    name = intake.get("packshot")
    packshot = packshot_for(assets, name, size) if name else None
    if name and packshot is None:
        from ..assemble import list_packshots
        raise GenError(f"assembly: no packshot named '{name}' in {assets/'packshots'} "
                       f"(have: {', '.join(list_packshots(assets)) or 'none'})")
    demo_name = intake.get("demo")
    demo = None
    if demo_name:
        matches = sorted((assets / "demos").glob(f"{demo_name}.*"))
        if not matches:
            raise GenError(f"assembly: no demo named '{demo_name}'")
        demo = matches[0]
    encode = (ctx.config.delivery.get("export") or {})
    style, subs_on = _subtitle_settings(ctx)
    edit = (ctx.config.pipeline or {}).get("edit") or {}
    # the producer's choice at a gate, then the config default; the brief no
    # longer asks, because a bed is judged by ear against the cut
    music_name = edit_of(ctx.job).get("music", edit.get("music") or "")
    music = music_for(assets, music_name) if music_name else None
    if music_name and music is None:
        from ..assemble import list_music
        raise GenError(f"assembly: no music bed named '{music_name}' "
                       f"(have: {', '.join(list_music(assets)) or 'none'})")
    return {
        "subtitle_style": style if subs_on else None,
        "fonts_dir": assets / "fonts",
        "crossfade_s": float(intake.get("crossfade_s", edit.get("crossfade_s", 0.0))),
        "crossfade_into_packshot": bool(edit.get("crossfade_into_packshot", True)),
        "music": music,
        "music_volume": float(edit.get("music_volume", 0.25)),
        "music_duck": bool(edit.get("music_duck", True)),
        "packshot": packshot,
        "demo": demo,
        "demo_trim_s": intake.get("demo_trim_s"),
        "crf": int(encode.get("crf", 21)),
        "preset": str(encode.get("preset", "veryfast")),
        # never regenerated or re-typeset: these are approved compliance assets
        "disclaimer": disclaimer_for(assets, size),
        "badge": disclaimer_for(assets, size, badge=True),
    }


def edit_of(job) -> Dict[str, Any]:
    """The producer's edit: which shots the cut contains, in what order, and the
    two choices that used to be made in the brief before anyone had seen a frame.

    It lives on the job rather than in `intake` because it is a decision about
    the CUT, and the cut is re-made for nothing -- so it is answerable at a gate,
    as often as the producer likes, which a brief written days earlier is not.

    `intake` may still SEED the bed -- the CLI's `--music`, a variation
    inheriting its parent's, or a job made before the editor existed. It is read
    only when the edit has not spoken, so re-cutting an old job does not
    silently drop its music, and choosing at a gate always wins."""
    edit = dict(job.meta.get("edit") or {})
    if "music" not in edit and job.intake.get("music"):
        edit["music"] = job.intake["music"]
    return edit


def cut_scenes(job) -> List[Dict[str, Any]]:
    """The scenes in cut order, dropped ones absent. `order` names scene idxs;
    anything it omits is not in the cut. An empty or missing order is every
    scene, in the order the plan wrote them."""
    order = (edit_of(job).get("order")) or []
    if not order:
        return list(job.scenes)
    by_idx = {s["idx"]: s for s in job.scenes}
    return [by_idx[i] for i in order if i in by_idx]


def _clip_paths(ctx: StageContext):
    scenes = cut_scenes(ctx.job)
    if not scenes:
        raise GenError("assembly: the edit drops every scene -- nothing to cut")
    missing = [s["idx"] for s in scenes if not s.get("clip")]
    if missing:
        raise GenError(f"assembly: scenes {missing} have no clip")
    return [ctx.job_dir / s["clip"] for s in scenes]


def _clip_audio(ctx: StageContext):
    """Per-clip replacement audio: the spoken line for a shot generated silent,
    None where the clip already carries its own speech."""
    return [str(ctx.job_dir / s["vo_track"]) if s.get("vo_track") else None
            for s in cut_scenes(ctx.job)]


def assembly(ctx: StageContext) -> None:
    """Step 6, first half: cut the draft the producer reviews at GATE_DRAFT.

    It runs BEFORE the gate on purpose -- a gate showing raw clips cannot tell
    you whether the edit works, and every fix available here (which packshot,
    how long the demo holds, the order) is ffmpeg, so revising it is free.

    The packshot goes last: it is what replaces the reference's own product
    shots, so the ad ends on our product rather than theirs."""
    size = SIZES[_formats(ctx)[0]]
    draft = ctx.dir("draft") / "draft.mp4"
    inputs = _assembly_inputs(ctx, size)
    try:
        if inputs.get("subtitle_style") is not None:
            # a silent first pass establishes the real timeline, so the words are
            # transcribed against the cut they will actually sit on
            probe_cut = build_final(_clip_paths(ctx), ctx.dir("draft") / "_timing.mp4",
                                    size, clip_audio=_clip_audio(ctx),
                                    **dict(inputs, subtitle_style=None,
                                                 disclaimer=None, badge=None,
                                                 crf=34, preset="ultrafast"))
            inputs["words"] = _transcribe_once(
                ctx, ctx.dir("draft") / "_timing.mp4",
                probe_cut["speech_end_s"], _edit_signature(ctx, inputs))
            (ctx.dir("draft") / "_timing.mp4").unlink(missing_ok=True)
        report = build_final(_clip_paths(ctx), draft, size,
                             clip_audio=_clip_audio(ctx), **inputs)
    except AssembleError as exc:
        raise GenError(f"assembly: {exc}")
    (ctx.dir("draft") / "edit_manifest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    ctx.job.add_artifact("draft", "draft/edit_manifest.json")
    ctx.job.add_artifact("draft", "draft/draft.mp4")
    ctx.job.meta["draft"] = report


def finalize(ctx: StageContext) -> None:
    """Step 6, second half: the clean masters, one per delivery format.

    Named for the delivery convention here rather than at delivery time, so
    preflight checks the real filename the week folder will receive.

    Nothing here costs credits, which is why `reassemble` can rewind to
    `assembly` and re-run this at any time without re-buying a clip."""
    intake = ctx.job.intake
    sizes = ctx.config.sizes
    naming_cfg = (ctx.config.delivery.get("naming") or {})
    written = []
    for fmt in _formats(ctx):
        if fmt not in sizes:
            raise GenError(f"delivery format '{fmt}' has no size in "
                           f"delivery.yaml (has: {', '.join(sorted(sizes))})")
        w, h = sizes[fmt]
        name = naming.build(
            ctx.job.id, intake["concept"], intake["week"], w, h,
            producer=intake.get("producer") or naming_cfg.get("default_producer", "lp"),
            channel=naming_cfg.get("channel", "fb"),
            type_=naming_cfg.get("type", "video"),
            source=naming_cfg.get("source", "nano"))
        size = SIZES.get(fmt)
        if size is None:
            raise GenError(f"delivery format '{fmt}' has no assembler size")
        inputs = _assembly_inputs(ctx, size)
        if inputs.get("subtitle_style") is not None:
            from ..subtitles import Word
            if ctx.job.meta.get("subtitle_sig") != _edit_signature(ctx, inputs):
                raise GenError(
                    "finalize: the subtitle transcript does not match this edit. "
                    "Re-cut (assembly) before delivering, or the words will sit "
                    "on a timeline that no longer exists.")
            inputs["words"] = [Word(**w) for w in ctx.job.meta.get("subtitle_words") or []]
        try:
            report = build_final(_clip_paths(ctx), ctx.dir("finals") / name, size,
                                 clip_audio=_clip_audio(ctx), **inputs)
        except AssembleError as exc:
            raise GenError(f"finalize: {exc}")
        ctx.job.add_artifact("finals", f"finals/{name}")
        written.append({"format": fmt, "size": [w, h], "file": name,
                        "duration_s": report["duration_s"],
                        "actual": [report["width"], report["height"]],
                        "has_audio": report["has_audio"],
                        "subtitle_lines": report.get("subtitle_lines", 0),
                        "crossfade_s": report.get("crossfade_s", 0.0),
                        "music": report.get("music"),
                        "segments": report["segments"]})
    manifest = {"id": ctx.job.id, "vertical": intake.get("vertical"),
                "week": intake["week"], "concept": intake["concept"],
                "producer": intake.get("producer"),
                "finals": written,
                "spent": round(ctx.job.spent, 2),
                "spent_by_backend": ctx.job.spent_by_backend(),
                "scenes": [{"idx": s["idx"], "duration_s": s["duration_s"],
                            "clip_qa": s.get("clip_qa")} for s in ctx.job.scenes],
                # shipped with known defects, and saying so: the folder outlives
                # everyone's memory of the decision
                "waived_clip_qa": sorted(ctx.job.meta.get("waived_clip_qa") or []),
                "waiver_note": ctx.job.meta.get("waiver_note") or ""}
    (ctx.dir("finals") / "build_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    ctx.job.meta["finals_manifest"] = written


def preflight(ctx: StageContext) -> None:
    from ..preflight import run_checks
    report = run_checks(ctx)
    _write_review(ctx, "preflight.json", report)
    if report["failed"]:
        # The name of a check is not a fault. "clip QA" told a producer nothing
        # about WHICH scenes, and the obvious next move -- retry -- re-runs the
        # same checks over the same files and fails identically. LME109 did
        # exactly that.
        bad = [c for c in report["checks"] if not c["ok"]]
        raise GenError(
            "preflight failed: "
            + "; ".join(f"{c['name']} ({c['detail']})" for c in bad)
            + ". Retrying cannot help -- these checks read the files that are "
              "already on disk. A blocking clip verdict means buying that shot "
              "again: `revise <id> clip --scene N` with a note saying what was "
              "wrong, which re-cuts and re-checks everything after it.")


def delivery(ctx: StageContext) -> None:
    """Into the existing week folder: <root>/<VERTICAL>/<N> week/.

    The vertical lookup here is NON-strict on purpose. Intake already refused an
    unknown vertical; by now the creative is built, preflighted and paid for, and
    failing on a config lookup would strand finished files.

    Nothing is ever hard-deleted. A stale file with the same name is moved to
    `_to_delete/` with a timestamp, so a redelivery can always be undone."""
    job = ctx.job
    week_dir = ctx.config.week_dir(job.intake.get("vertical", ""), job.intake["week"])
    week_dir.mkdir(parents=True, exist_ok=True)
    trash = week_dir / ctx.config.delivery.get("trash_subfolder", "_to_delete")
    delivered, replaced = [], []
    for f in sorted(ctx.dir("finals").glob("n-*")):
        dest = week_dir / f.name
        if dest.exists():
            trash.mkdir(exist_ok=True)
            stale = trash / f"{int(time.time())}_{f.name}"
            shutil.move(str(dest), str(stale))
            replaced.append(str(stale))
        shutil.copy2(f, dest)
        delivered.append(str(dest))
    if not delivered:
        raise GenError(f"delivery: no finals matched the naming convention in "
                       f"{ctx.dir('finals')} -- nothing was delivered")
    manifest = ctx.dir("finals") / "build_manifest.json"
    if manifest.exists():
        shutil.copy2(manifest, week_dir / f"{job.id}_manifest.json")
    job.meta["delivered_to"] = delivered
    job.meta["week_dir"] = str(week_dir)
    if replaced:
        job.meta["replaced"] = replaced
        job.add_event("delivery_replaced",
                      f"{len(replaced)} stale file(s) moved to {trash}")
    job.add_event("delivered", f"{len(delivered)} finals -> {week_dir}")
