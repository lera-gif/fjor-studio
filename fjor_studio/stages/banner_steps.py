"""Banner mode: the stages that differ from the UGC pipeline.

A banner job runs the SAME pipeline states and stops at the SAME gates -- the
expanded frame is looked at before any video is bought, the animation before it
is cut, the cut before it ships. What changes is what four of those stages do,
and what three of them skip.

    intake     an IMAGE, not a reference video
    analysis   skipped entirely
    prompts    the compact brain: what moves, and for how long
    plates     build the canvas, expand it, check the banner survived, then
               remove the legal small print in a second, licensed pass
    clips      unchanged -- the expanded frame is a plate like any other
    voiceovers skipped: these clips are silent

The skipping is deliberate, not laziness. Their v4 gave this mode its own brain
on purpose: the 90k-character video instruction, the niche, the voice and the
reference analysis are all kept out, because none of them describes a banner and
every one of them competes with the two assets that do.

NOT wired here: restyle variations ("beach / sporty / abstract"), which in their
tool re-render the banner per variation. One banner, one expanded frame, one
animation.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict

from .. import banner
from ..engine.engine import StageContext
from ..engine.job import Scene
from ..gen.base import GenError

BANNER_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def is_banner(job) -> bool:
    """Is this a banner job? Decided by what intake was given.

    Their tool announces which pipeline is about to run before it writes any
    prompt, because mixing the two wastes a whole generation. Ours refuses the
    ambiguity instead: a job carries a reference video or a banner, never both."""
    intake = getattr(job, "intake", None) or {}
    has_banner = bool(str(intake.get("banner") or "").strip())
    has_reference = bool(str(intake.get("reference") or "").strip())
    if has_banner and has_reference:
        raise GenError(
            "this job has both a banner and a reference video. They are two "
            "different pipelines -- a banner is expanded and animated, a "
            "reference is analysed and re-created -- and nothing downstream can "
            "tell which one you meant. Give it one or the other.")
    return has_banner


def _state(job) -> Dict[str, Any]:
    return job.meta.setdefault("banner", {})


# ------------------------------------------------------------------ intake --

def intake(ctx: StageContext) -> None:
    """Take the banner into the job, and settle its geometry now.

    The placement is worked out here rather than at plates because it decides
    whether there is anything to expand at all -- a banner already 9:16 needs no
    expansion, and finding that out before the gate is worth more than finding
    it out after."""
    src = Path(str(ctx.job.intake.get("banner")).strip())
    if not src.exists():
        raise GenError(f"intake: banner not found: {src}")
    if src.suffix.lower() not in BANNER_SUFFIXES:
        raise GenError(
            f"a banner must be an image ({', '.join(sorted(BANNER_SUFFIXES))}), "
            f"not '{src.suffix}' -- for a reference VIDEO use the ordinary "
            f"pipeline, which analyses it")
    dest = ctx.dir("ref") / src.name
    if not dest.exists():
        shutil.copy2(src, dest)
    ctx.job.intake["banner_local"] = f"ref/{dest.name}"
    ctx.job.add_artifact("ref", f"ref/{dest.name}")

    w, h = banner.measure(dest)
    place = banner.placement(w, h)
    _state(ctx.job).update({"source": f"ref/{dest.name}", "width": w,
                            "height": h, "placement": place,
                            "needs_expansion": bool(place["top"] or place["bottom"])})
    ctx.job.add_event(
        "banner_intake",
        f"{w}x{h} banner; " + (
            f"{place['top']}px to paint above and {place['bottom']}px below"
            if place["top"] or place["bottom"]
            else "already vertical -- nothing to expand"))


# ------------------------------------------------------------------- plan ---

# Only the ANIMATION is asked about. The expansion is not: the canvas already
# shows the model the banner and the exact areas to fill, and describing that
# scene in words made it draw the scene instead of filling the gaps (AW025).
# `banner.ANALYSIS_QUESTIONS` belongs to the bare-image engine, which we do not
# have -- see the note above `CANVAS_FILL_PROMPT`.
PLAN_BRIEF = """A finished, client-approved advertising banner is attached. It
has been expanded to vertical 9:16 without being altered, and now has to be
animated.

You are NOT writing the prompt. You are answering questions, and the prompt is
built from your answers. Study the banner first.

{animation}

Return ONE JSON object and nothing else:

{{
  "graphic": true | false,    // is the banner a flat illustration?
  "movers": ["...", "..."],   // 1-2 for a photograph, 2-4 for an illustration
  "central": "...",           // the movement inside the middle 1080x1350
  "frozen": "...",            // anything carrying printed lettering, or ""
  "background": "...",        // one background micro-motion, or ""
  "seconds": 5..10
}}"""


def plan(ctx: StageContext) -> None:
    """The compact brain: one call, and every prompt is assembled from it."""
    src = ctx.job_dir / _state(ctx.job)["source"]
    brief = PLAN_BRIEF.format(animation=banner.ANIMATION_QUESTIONS.strip())
    if str(ctx.job.intake.get("brief") or "").strip():
        # An edit inside the banner would be painted by the expansion and then
        # immediately overwritten when the original is re-composited over its own
        # rectangle. Saying so is the only honest option: a brief silently not
        # applied is worse than one refused.
        ctx.job.add_event(
            "banner_brief_ignored",
            "banner mode applies no brief edits: the banner is re-composited "
            "over the expansion untouched, so anything painted inside it is "
            "overwritten. An edit here needs its own licensed pass, the way the "
            "small print has one.")
    model = ctx.config.model_for("text")
    result = ctx.providers.backend_for("text").generate(
        "text", model, brief, medias=[str(src)])
    if result.credits:
        ctx.job.spend("prompts", "banner plan", result.credits, result.backend)
    answers = _parse_answers(result.text)
    animation = banner.animation_prompt(answers)
    _state(ctx.job).update({"answers": answers,
                            "expansion_prompt": banner.fill_prompt()})
    scene = Scene(idx=0)
    scene.image_prompt = banner.fill_prompt()
    scene.video_prompt = animation["prompt"]
    scene.duration_s = float(animation["seconds"])
    # Silent, and with no line to speak: `voiceovers` then has nothing to do,
    # and the video model is told to generate no audio -- a banner clip that
    # invents a soundtrack is what gets a generation refused for copyright.
    scene.voice = "vo"
    scene.line = ""
    scene.characters = []
    ctx.job.put_scene(scene)
    ctx.job.add_event(
        "banner_plan",
        f"{len(answers.get('movers') or [])} mover(s), {animation['seconds']}s")


def _parse_answers(text: str) -> Dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
    try:
        data = json.loads(cleaned)
    except Exception:  # noqa: BLE001
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end < start:
            raise GenError("the banner analysis returned no JSON object")
        data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, dict):
        raise GenError("the banner analysis returned JSON that is not an object")
    return data


# ----------------------------------------------------------------- plates ---

def expand(ctx: StageContext) -> None:
    """Build the canvas, fill it, and check the banner came back unharmed.

    TWO checks, because they see different things. `banner_survived` looks
    inside the banner's own rectangle and is exact -- it is arithmetic on the
    pixels we put there ourselves. It is also, by construction, blind to
    everything OUTSIDE that rectangle, which is where a seam, a blurred band or
    a person left ending mid-torso would be. That half is a judgement, and it
    goes to the QA model with a checklist written for a banner.

    Regeneration here is not a QA nicety. Their note is blunt about it: the
    generation is probabilistic, two to four attempts on a banner is normal, and
    a bad take is not repaired by rewording the prompt -- it is simply run
    again."""
    # Imported here rather than at module scope: `steps` imports this module to
    # branch into it, so the dependency only closes at call time.
    from .paid import run_generation
    from .steps import _consume, _qa_settings, _run_media_qa, _steer, _targets
    from ..qa import should_regenerate

    state = _state(ctx.job)
    scene = ctx.job.scene(0)
    redo, note = _targets(ctx, "plates")
    if redo:
        # `revise plates` at GATE_PLATES. Without this the finished plate is
        # skipped as already-made and the producer's request does nothing --
        # the CLI would accept a flag that had no effect.
        scene.plate = None
        ctx.job.put_scene(scene)
        ctx.job.add_event("revision_scope",
                          "re-expanding the banner", note=note)
    if scene.plate and (ctx.job_dir / scene.plate).exists():
        return                                  # a re-run does not re-buy

    src = ctx.job_dir / state["source"]
    place = state["placement"]
    model = ctx.config.model_for("image")
    settings = _qa_settings(ctx)
    # Read from the module, not from the job. The fill instruction is FIXED, so
    # a copy stored on the job can only ever go stale -- as AW025's did the
    # moment the prompt changed under it, leaving a retry about to re-send the
    # very text that caused the failure. The scene is corrected too, or the page
    # would show a producer a prompt that is not the one sent.
    prompt = banner.fill_prompt()
    state["expansion_prompt"] = prompt
    if scene.image_prompt != prompt:
        scene.image_prompt = prompt
        ctx.job.put_scene(scene)

    if not state.get("needs_expansion"):
        # Already vertical. There is nothing to paint, so there is nothing to
        # check either -- the frame IS the banner.
        dest = ctx.dir("plates") / "banner_916.png"
        shutil.copy2(src, dest)
        expanded = dest
    else:
        canvas = banner.build_canvas(src, ctx.dir("plates") / "canvas.png")
        ctx.job.add_artifact("plates", "plates/canvas.png")
        expanded, refusal = None, ""
        for attempt in range(1, settings.plates_max_attempts + 1):
            out = ctx.dir("plates") / f"expanded_{attempt:02d}.png"
            if not redo and out.exists() and _usable(src, out, place):
                # Already bought, and good. An attempt that passed the model's
                # half and then fell over on OUR arithmetic must not be paid for
                # twice -- the same rule the rest of the pipeline follows when a
                # stage re-runs over work already on disk.
                ctx.job.add_event(
                    "collecting",
                    f"attempt {attempt}: reusing the expansion already paid for")
                candidate = out
                judged = banner.same_picture(src, candidate, place)
                expanded = banner.recomposite(
                    src, candidate, ctx.dir("plates") / "expanded.png", place)
                ctx.job.add_artifact("plates", "plates/expanded.png")
                survived = banner.banner_survived(src, expanded, place)
                if not survived["intact"]:
                    raise GenError(
                        f"re-compositing did not restore the banner "
                        f"({survived['changed_pixels']} pixels still differ). "
                        f"This is our own arithmetic, not the model's doing.")
                state["survived"], state["judged"] = survived, judged
                break
            result = run_generation(
                ctx, scene, "image", model,
                _steer(prompt, note), out,
                # 2K: at 1K this model answers a 1080x1920 canvas with a
                # 768-wide frame, and the final is exported 1080 wide. Their
                # notes price Banana Pro at "$0.09 for 1-2K", so the wider
                # frame is the same money.
                params={"resolution": "2K"},
                medias=[canvas["file"]], stage="plates",
                label=f"expansion attempt {attempt}")
            candidate = Path(result.files[0])
            ctx.job.add_artifact("plates", f"plates/{candidate.name}")

            try:
                judged = banner.same_picture(src, candidate, place)
            except banner.BannerError as exc:
                # A frame that cannot be compared is a failed attempt, not a
                # crash. The answer to a misshapen return is to run it again.
                refusal = str(exc)
                ctx.job.add_event("banner_damaged",
                                  f"attempt {attempt}: {refusal}")
                continue
            ctx.job.add_event(
                "banner_same_picture" if judged["same"] else "banner_redrawn",
                f"attempt {attempt}: returned {judged['returned'][0]}x"
                f"{judged['returned'][1]}, difference from the banner "
                f"{judged['mean_difference']} (limit {judged['limit']})",
                **judged)
            if not judged["same"]:
                # Not repairable by putting our banner back: a model that
                # redrew the scene also painted MARGINS belonging to that other
                # scene, and those margins are the only thing we keep.
                refusal = (f"the model redrew the banner instead of extending "
                           f"it (difference {judged['mean_difference']}, limit "
                           f"{judged['limit']})")
                continue

            scene = ctx.job.scene(0)
            scene.plate_attempts = attempt
            verdict = _run_media_qa(ctx, scene, "plate", candidate, prompt)
            scene.plate_qa = verdict.as_dict() if verdict else None
            ctx.job.put_scene(scene)
            ctx.store.save(ctx.job)
            if verdict is None or not should_regenerate(
                    verdict, "plate", attempt, settings):
                # The model contributed MARGINS. Everything else it returned is
                # a rescaled approximation of pixels we already have, so ours go
                # back and the banner is exact by construction.
                expanded = banner.recomposite(
                    src, candidate, ctx.dir("plates") / "expanded.png", place)
                ctx.job.add_artifact("plates", "plates/expanded.png")
                # And now PROVE it: both frames are exactly the canvas size, so
                # the strict pixel count applies again and says whether the
                # re-composite really put our banner back. A guarantee by
                # construction that is never checked is a guarantee by hope.
                survived = banner.banner_survived(src, expanded, place)
                if not survived["intact"]:
                    raise GenError(
                        f"re-compositing did not restore the banner "
                        f"({survived['changed_pixels']} pixels still differ). "
                        f"This is our own arithmetic, not the model's doing.")
                ctx.job.add_event(
                    "banner_survived",
                    f"attempt {attempt}: the banner is back exactly "
                    f"({survived['changed_pixels']} changed pixels)", **survived)
                state["survived"] = survived
                state["judged"] = judged
                break
            refusal = f"QA called the expansion critical: {'; '.join(verdict.issues)}"
            ctx.job.add_event("qa_regen", f"attempt {attempt}: {refusal}",
                              issues=verdict.issues)
        if expanded is None:
            raise GenError(
                f"the expansion failed on all {settings.plates_max_attempts} "
                f"attempts -- {refusal}. Everything printed on this banner was "
                f"approved by a client, so shipping a redrawn or seamed one is "
                f"worse than shipping nothing. Look at the attempts in plates/ "
                f"before spending more.")

    cleaned = _remove_small_print(ctx, scene, expanded, src, place, model)
    scene = ctx.job.scene(0)
    scene.plate = f"plates/{cleaned.name}"
    ctx.job.put_scene(scene)
    ctx.job.add_artifact("plates", scene.plate)
    _consume(ctx, "plates")
    ctx.store.save(ctx.job)


def _usable(src: Path, candidate: Path, place: Dict[str, Any]) -> bool:
    """Is an expansion already on disk one we would have accepted?"""
    try:
        return bool(banner.same_picture(src, candidate, place)["same"])
    except banner.BannerError:
        return False


def _remove_small_print(ctx: StageContext, scene, expanded: Path, src: Path,
                        place: Dict[str, int], model: str) -> Path:
    """The one edit inside the banner, in its own pass with its own licence.

    Folded into the expansion it would be indistinguishable from damage: the
    check could no longer tell a removed disclaimer from a redrawn headline."""
    from .paid import run_generation

    if not bool(ctx.job.intake.get("remove_small_print", True)):
        return expanded
    out = ctx.dir("plates") / "cleaned_raw.png"
    result = run_generation(ctx, scene, "image", model,
                            banner.small_print_prompt(), out,
                            params={"resolution": "2K"},
                            medias=[str(expanded)], stage="plates",
                            label="removing the legal small print")
    raw = Path(result.files[0])

    # The same two lessons as the expansion, and they apply here for the same
    # reasons: the model answers in its own resolution bucket, and it may redraw
    # rather than edit. So the picture is judged, and then everything OUTSIDE the
    # licensed band is restored from our own banner -- the band it was licensed
    # for, and not one row more.
    try:
        judged = banner.same_picture(src, raw, place)
    except banner.BannerError as exc:
        judged = {"same": False, "mean_difference": None, "why": str(exc)}
    if not judged["same"]:
        ctx.job.add_event(
            "banner_redrawn",
            "the small-print pass redrew the frame instead of erasing a strip "
            "-- keeping the expansion with its disclaimer, which our own "
            "approved one covers anyway", **judged)
        return expanded

    cleaned = banner.recomposite(src, raw, ctx.dir("plates") / "cleaned.png",
                                 place, keep=banner.SMALL_PRINT_BAND)
    verdict = banner.banner_survived(src, cleaned, place,
                                     licensed=banner.SMALL_PRINT_BAND)
    if not verdict["intact"]:
        raise GenError(
            f"restoring the banner around the small print left "
            f"{verdict['changed_pixels']} pixels changed outside the licensed "
            f"band. This is our own arithmetic, not the model's doing.")
    if not verdict.get("edit_applied"):
        # Indistinguishable from a clean result to every other check here, which
        # is exactly how a silently skipped step reaches delivery.
        ctx.job.add_event(
            "banner_small_print",
            "the small-print pass changed nothing in its band -- the disclaimer "
            "is still on the frame", **verdict)
    else:
        ctx.job.add_event(
            "banner_small_print",
            f"the legal small print is gone; the rest of the banner is "
            f"untouched ({verdict['changed_pixels']} changed pixels outside "
            f"the band)", **verdict)
    ctx.job.add_artifact("plates", f"plates/{cleaned.name}")
    return cleaned
