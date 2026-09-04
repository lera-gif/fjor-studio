"""Drives a job forward. UI-agnostic: a CLI, a dashboard and a test all call
exactly run / approve / revise / retry / cancel -- nothing else mutates state."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .job import Job
from .pipeline import (GATES, PIPELINE, REVISABLE, REVISE_PREFIX, TERMINAL,
                       next_state, skippable_gates)
from .store import JobStore


EDIT_KEYS = {"order", "music", "subtitles", "hook", "insert",
             "mute", "music_volume", "music_duck", "trim", "vo"}
PROMPT_FIELDS = ("image_prompt", "video_prompt", "end_image_prompt")


def _validated_edit(job: Job, edit: Dict[str, Any],
                    assets_dir: Optional[Path] = None,
                    crossfade_s: float = 0.0,
                    job_dir: Optional[Path] = None) -> Dict[str, Any]:
    """A rejected edit is better than a cut that quietly lost a shot."""
    out: Dict[str, Any] = {}
    # The opening hook and the product insert are library clips. Checked here,
    # against the library, because assembly discovering a missing one means a
    # re-cut that fails after the producer walked away.
    for key in ("hook", "insert"):
        if key not in edit:
            continue
        item_id = str(edit[key] or "").strip()
        if item_id and assets_dir is not None:
            from .. import library as library_mod
            if library_mod.item_path(assets_dir, item_id) is None:
                raise TransitionError(
                    f"edit.{key}: '{item_id}' is not in the clip library")
        out[key] = item_id
    if "order" in edit:
        known = [s["idx"] for s in job.scenes]
        try:
            order = [int(i) for i in (edit["order"] or [])]
        except (TypeError, ValueError):
            raise TransitionError("edit.order must be a list of scene numbers")
        unknown = [i for i in order if i not in known]
        if unknown:
            raise TransitionError(
                f"edit.order names scenes that do not exist: {unknown} "
                f"(this job has {known})")
        if len(set(order)) != len(order):
            raise TransitionError(f"edit.order repeats a scene: {order}")
        if not order:
            raise TransitionError("edit.order drops every scene -- a cut needs one")
        out["order"] = order
    if "music" in edit:
        out["music"] = str(edit["music"] or "")
    if "subtitles" in edit:
        subs = edit["subtitles"] or {}
        if not isinstance(subs, dict):
            raise TransitionError("edit.subtitles must be an object")
        allowed = {"enabled", "style", "colour", "color", "size", "font", "lead_s"}
        unknown = sorted(set(subs) - allowed)
        if unknown:
            raise TransitionError(
                f"edit.subtitles: unknown setting(s) {unknown} "
                f"(known: {', '.join(sorted(allowed))})")
        out["subtitles"] = dict(subs)
    if "mute" in edit:
        # Which shots lose their OWN audio. A shot whose line was spoken
        # separately is unaffected -- that voice is a separate asset and gets
        # its own controls; this only silences what the clip itself carries.
        known = [s["idx"] for s in job.scenes]
        try:
            mute = sorted({int(i) for i in (edit["mute"] or [])})
        except (TypeError, ValueError):
            raise TransitionError("edit.mute must be a list of scene numbers")
        unknown_m = [i for i in mute if i not in known]
        if unknown_m:
            raise TransitionError(
                f"edit.mute names scenes that do not exist: {unknown_m} "
                f"(this job has {known})")
        out["mute"] = mute
    if "music_volume" in edit:
        try:
            vol = float(edit["music_volume"])
        except (TypeError, ValueError):
            raise TransitionError("edit.music_volume must be a number")
        if not 0.0 <= vol <= 1.0:
            raise TransitionError(
                f"edit.music_volume is {vol}; it is a fraction, 0 to 1")
        out["music_volume"] = round(vol, 3)
    if "music_duck" in edit:
        out["music_duck"] = bool(edit["music_duck"])
    if "trim" in edit:
        # Per shot: [in, out] in seconds of the CLIP. `out` may be null for
        # "to the end". Checked against the shot's length when it is known,
        # and against the crossfade -- every transition consumes its own
        # duration, so a segment shorter than the fade does not error, it
        # simply vanishes from the cut. A refusal here names both numbers.
        raw = edit["trim"] or {}
        if not isinstance(raw, dict):
            raise TransitionError("edit.trim must map scene numbers to [in, out]")
        by_idx = {s["idx"]: s for s in job.scenes}
        trims: Dict[str, Any] = {}
        for k, v in raw.items():
            try:
                idx = int(k)
            except (TypeError, ValueError):
                raise TransitionError(f"edit.trim: '{k}' is not a scene number")
            if idx not in by_idx:
                raise TransitionError(
                    f"edit.trim names scene {idx}, which does not exist "
                    f"(this job has {sorted(by_idx)})")
            if v in (None, [], {}):
                continue                          # an explicit "no trim"
            try:
                t_in = float(v[0] or 0.0)
                t_out = None if (len(v) < 2 or v[1] in (None, "")) else float(v[1])
            except (TypeError, ValueError, IndexError):
                raise TransitionError(
                    f"edit.trim[{idx}] must be [in, out] in seconds")
            if t_in < 0:
                raise TransitionError(f"edit.trim[{idx}]: in-point {t_in} is before 0")
            length = by_idx[idx].get("duration_s")
            end = t_out if t_out is not None else (float(length) if length else None)
            if t_out is not None and t_out <= t_in:
                raise TransitionError(
                    f"edit.trim[{idx}]: out-point {t_out} is not after in-point {t_in}")
            if length and t_in >= float(length):
                raise TransitionError(
                    f"edit.trim[{idx}]: in-point {t_in}s is past the end of a "
                    f"{length}s shot")
            if length and t_out is not None and t_out > float(length) + 0.05:
                raise TransitionError(
                    f"edit.trim[{idx}]: out-point {t_out}s is past the end of a "
                    f"{length}s shot")
            if end is not None and crossfade_s and (end - t_in) <= crossfade_s:
                raise TransitionError(
                    f"edit.trim[{idx}]: leaves {end - t_in:.2f}s of the shot, "
                    f"but the crossfade is {crossfade_s}s and eats that much "
                    f"at each join -- the shot would vanish from the cut. "
                    f"Keep at least {crossfade_s + 0.25:.2f}s or lower the "
                    f"crossfade.")
            if t_in == 0.0 and t_out is None:
                continue                          # no-op, do not record
            trims[str(idx)] = [round(t_in, 3), None if t_out is None else round(t_out, 3)]
        out["trim"] = trims
    if "vo" in edit:
        # Per shot with a separately spoken line: {offset, in, out}. `offset`
        # is seconds after the shot starts and may exceed the shot -- that is
        # how a line is pushed into the next one on purpose. `in`/`out` trim
        # the RECORDING, checked against its real length.
        raw = edit["vo"] or {}
        if not isinstance(raw, dict):
            raise TransitionError("edit.vo must map scene numbers to {offset, in, out}")
        by_idx = {s["idx"]: s for s in job.scenes}
        vo: Dict[str, Any] = {}
        for k, v in raw.items():
            try:
                idx = int(k)
            except (TypeError, ValueError):
                raise TransitionError(f"edit.vo: '{k}' is not a scene number")
            if idx not in by_idx:
                raise TransitionError(f"edit.vo names scene {idx}, which does not exist")
            if not by_idx[idx].get("vo_track"):
                raise TransitionError(
                    f"edit.vo[{idx}]: that shot has no separately spoken line to move")
            if not v:
                continue
            if not isinstance(v, dict):
                raise TransitionError(f"edit.vo[{idx}] must be an object")
            try:
                off = float(v.get("offset") or 0.0)
                t_in = float(v.get("in") or 0.0)
                t_out = None if v.get("out") in (None, "") else float(v["out"])
            except (TypeError, ValueError):
                raise TransitionError(f"edit.vo[{idx}]: offset, in and out are seconds")
            if off < 0 or t_in < 0:
                raise TransitionError(f"edit.vo[{idx}]: offset and in-point cannot be negative")
            if t_out is not None and t_out <= t_in:
                raise TransitionError(
                    f"edit.vo[{idx}]: out-point {t_out} is not after in-point {t_in}")
            if job_dir is not None:
                try:
                    from ..assemble import duration_of
                    length = float(duration_of(job_dir / by_idx[idx]["vo_track"]))
                except Exception:  # noqa: BLE001 -- unprobeable: skip the bound
                    length = 0.0
                if length and t_in >= length:
                    raise TransitionError(
                        f"edit.vo[{idx}]: in-point {t_in}s is past the end of a "
                        f"{length:.2f}s recording")
                if length and t_out is not None and t_out > length + 0.05:
                    raise TransitionError(
                        f"edit.vo[{idx}]: out-point {t_out}s is past the end of a "
                        f"{length:.2f}s recording")
            if off == 0.0 and t_in == 0.0 and t_out is None:
                continue                          # no-op: where it always sat
            vo[str(idx)] = {"offset": round(off, 3), "in": round(t_in, 3),
                            "out": None if t_out is None else round(t_out, 3)}
        out["vo"] = vo
    unknown = sorted(set(edit) - EDIT_KEYS)
    if unknown:
        raise TransitionError(f"edit: unknown key(s) {unknown}")
    return out


def _describe_edit(job: Job, edit: Dict[str, Any]) -> str:
    bits = []
    order = edit.get("order")
    if order:
        dropped = [s["idx"] for s in job.scenes if s["idx"] not in order]
        bits.append("order " + "-".join(str(i) for i in order)
                    + (f", dropped {dropped}" if dropped else ""))
    if "music" in edit:
        bits.append(f"music {edit['music'] or 'none'}")
    if edit.get("hook"):
        bits.append("hook " + str(edit["hook"]))
    if edit.get("insert"):
        bits.append("insert " + str(edit["insert"]))
    if "subtitles" in edit:
        subs = edit["subtitles"]
        said = ", ".join(f"{k}={v}" for k, v in sorted(subs.items()))
        bits.append("subtitles "
                    + ("off" if subs.get("enabled") is False else said))
    if edit.get("mute"):
        bits.append("muted " + "-".join(str(i) for i in edit["mute"]))
    if edit.get("vo"):
        bits.append("voice " + ", ".join(
            f"{k}: +{v.get('offset', 0)}s"
            + (f" [{v.get('in', 0)}–{'end' if v.get('out') is None else v['out']}]"
               if v.get('in') or v.get('out') is not None else "")
            for k, v in sorted(edit["vo"].items(), key=lambda kv: int(kv[0]))))
    if edit.get("trim"):
        bits.append("trim " + ", ".join(
            f"{k}→{v[0]}–{'end' if v[1] is None else v[1]}s"
            for k, v in sorted(edit["trim"].items(), key=lambda kv: int(kv[0]))))
    if "music_volume" in edit:
        bits.append(f"bed at {int(round(edit['music_volume'] * 100))}%")
    if "music_duck" in edit:
        bits.append("bed ducks under speech" if edit["music_duck"]
                    else "bed does not duck")
    return "edit: " + ("; ".join(bits) if bits else "unchanged")


class TransitionError(Exception):
    pass


class Blocked(Exception):
    """A stage that cannot pass, whose remedy lives at an earlier GATE.

    Failing the job would be honest about the stop and wrong about what to do
    next. AW024 (2026-09-01) failed at preflight on three blocking clip
    verdicts; its own error told the producer to run `revise ... clip --scene N`,
    and `revise` refuses anything that is not at a gate. The tool named a
    command it would not accept, at the moment 2,114 credits were riding on the
    answer.

    So a blocked stage says WHERE the decision belongs, and the job is put back
    there with its reason recorded. Every remedy that gate offers -- revise,
    waive, approve again -- is then reachable."""

    def __init__(self, gate: str, message: str):
        super().__init__(message)
        self.gate = gate


@dataclass
class StageContext:
    job: Job
    job_dir: Path
    config: Any
    store: JobStore
    providers: Any = None

    def dir(self, sub: str) -> Path:
        d = self.job_dir / sub
        d.mkdir(parents=True, exist_ok=True)
        return d


StageFn = Callable[[StageContext], None]


class Engine:
    def __init__(self, store: JobStore, config: Any, stages: Dict[str, StageFn],
                 providers: Any = None):
        self.store = store
        self.config = config
        self.stages = stages
        self.providers = providers
        # validated once, at construction: a config that tries to skip a money
        # gate fails loudly here rather than quietly running past it later
        self.skip_gates = skippable_gates(
            (getattr(config, "pipeline", None) or {}).get("gates", {}).get("skip", []))

    def _ctx(self, job: Job) -> StageContext:
        return StageContext(job=job, job_dir=self.store.job_dir(job.id),
                            config=self.config, store=self.store,
                            providers=self.providers)

    # -- main loop -----------------------------------------------------------
    def run(self, job: Job) -> Job:
        """Advance until a gate, a terminal state, or a failure. Safe to call on
        a job in any state -- that is what resume is."""
        while True:
            if job.state in TERMINAL:
                return job

            if job.state in GATES:
                if not job.gate_ready:
                    if not self._run_stage(job, job.state):
                        return job          # gate prep itself failed
                    job.gate_ready = True
                    job.add_event("gate_ready",
                                  f"{job.state}: review ready, awaiting approval")
                    self.store.save(job)
                if job.state in self.skip_gates:
                    job.add_event("gate_skipped",
                                  f"{job.state} passed through (gates.skip)")
                    job.state = next_state(job.state)
                    job.gate_ready = False
                    self.store.save(job)
                    continue
                return job

            if job.state.startswith(REVISE_PREFIX):
                stage = job.state[len(REVISE_PREFIX):]
                if not self._run_stage(job, stage, event_state=job.state):
                    return job
                # continue FORWARD from the revised stage; later stages re-run
                # against the fresh outputs and the flow stops at the next gate
                job.state = next_state(stage)
                job.revise_return = None
                job.gate_ready = False
                job.add_event("revision_done",
                              f"'{stage}' revised; re-running forward from there")
                self.store.save(job)
                continue

            if not self._run_stage(job, job.state):
                return job
            job.state = next_state(job.state)
            self.store.save(job)

    def _run_stage(self, job: Job, stage: str,
                   event_state: Optional[str] = None) -> bool:
        fn = self.stages.get(stage)
        if fn is None:
            job.error = f"no handler registered for stage '{stage}'"
            job.add_event("error", job.error, failed_stage=stage,
                          failed_state=job.state)
            job.state = "failed"
            self.store.save(job)
            return False
        job.add_event("stage_started",
                      stage if event_state is None else f"{event_state} ({stage})")
        self.store.save(job)
        try:
            fn(self._ctx(job))
        except Blocked as exc:
            # A gate the config skips would send the run straight back here and
            # round again, so a blocked stage that cannot be reviewed is simply
            # a failure. `GATE_DRAFT` is unskippable, which is why it is the one
            # preflight uses.
            if exc.gate in self.skip_gates or exc.gate not in GATES:
                job.error = f"{stage}: {exc}"
                job.add_event("error", job.error, failed_stage=stage,
                              failed_state=job.state)
                job.state = "failed"
            else:
                job.error = f"{stage}: {exc}"
                job.add_event("blocked", job.error, failed_stage=stage,
                              returned_to=exc.gate)
                job.state = exc.gate
                job.gate_ready = False
            self.store.save(job)
            return False
        except Exception as exc:  # noqa: BLE001 -- any stage error fails resumably
            job.error = f"{stage}: {exc}"
            job.add_event("error", job.error, failed_stage=stage,
                          failed_state=job.state)
            job.state = "failed"
            self.store.save(job)
            return False
        job.add_event("stage_completed", stage)
        self.store.save(job)
        return True

    # -- human actions -------------------------------------------------------
    def approve(self, job: Job, note: str = "") -> Job:
        if job.state not in GATES:
            raise TransitionError(f"job {job.id} is in '{job.state}', not at a gate")
        job.add_event("approved", note or f"{job.state} approved")
        job.state = next_state(job.state)
        job.gate_ready = False
        self.store.save(job)
        return self.run(job)

    def revise(self, job: Job, what: str, note: str = "",
               scenes: Optional[List[int]] = None,
               notes: Optional[Dict[Any, str]] = None) -> Job:
        """`note` steers every shot sent back; `notes` is a note per shot,
        keyed by scene, for when each came back wrong in its own way -- one
        note for eight shots would send scene 2's finding to all eight and
        lose the other seven. A shot named in `notes` is sent back."""
        if job.state not in GATES:
            raise TransitionError(f"job {job.id} is in '{job.state}', not at a gate")
        options = REVISABLE[job.state]
        stage = options.get(str(what).strip().lower())
        if stage is None:
            raise TransitionError(
                f"'{what}' is not revisable at {job.state} "
                f"(options: {', '.join(sorted(options))})")
        # `scenes` narrows the redo to the shots the producer commented on --
        # everything else is already paid for and approved
        picked = [int(s) for s in (scenes or [])]
        per_scene: Dict[str, str] = {}
        known = {s["idx"] for s in job.scenes}
        for key, text in (notes or {}).items():
            idx = int(key)
            if idx not in known:
                raise TransitionError(f"job {job.id} has no scene {idx}")
            if str(text or "").strip():
                per_scene[str(idx)] = str(text).strip()
            if idx not in picked:
                picked.append(idx)
        job.revisions.append({"gate": job.state, "what": what, "note": note,
                              "scenes": picked, "notes": per_scene,
                              "at": job.updated_at})
        job.add_event("revision_requested",
                      (f"{what} (scene {', '.join(map(str, picked))})" if picked
                       else what) + (f": {note}" if note else ""))
        job.revise_return = job.state
        job.state = REVISE_PREFIX + stage
        job.gate_ready = False
        self.store.save(job)
        return self.run(job)

    def set_edit(self, job: Job, edit: Dict[str, Any], recut: bool = True) -> Job:
        """Record the producer's edit, and re-cut if there is already a cut.

        Only offered at a gate: the edit decides what `assembly` builds, and
        changing it under a running stage would describe a cut nobody asked for.
        At GATE_CLIPS nothing has been assembled yet, so the edit simply waits
        for the approval that runs assembly; at GATE_DRAFT there IS a cut, so it
        is re-made -- ffmpeg only, no stage that spends anything runs again."""
        if job.state not in GATES:
            raise TransitionError(f"job {job.id} is in '{job.state}', not at a gate")
        merged = dict(job.meta.get("edit") or {})
        merged.update(_validated_edit(job, edit, self._assets_dir(),
                                      crossfade_s=self._crossfade_for(job),
                                      job_dir=self.store.job_dir(job.id)))
        job.meta["edit"] = merged
        job.add_event("edit", _describe_edit(job, merged))
        self.store.save(job)
        if not recut or job.state != "GATE_DRAFT":
            return job
        job.revise_return = job.state
        job.state = REVISE_PREFIX + "assembly"
        job.gate_ready = False
        self.store.save(job)
        return self.run(job)

    def _crossfade_for(self, job: Job) -> float:
        """The same answer assembly will use: the intake's value, else config."""
        edit_cfg = ((getattr(self.config, "pipeline", None) or {}).get("edit") or {})
        try:
            return float(job.intake.get("crossfade_s", edit_cfg.get("crossfade_s", 0.0)))
        except (TypeError, ValueError):
            return 0.0

    def _assets_dir(self) -> Optional[Path]:
        try:
            return Path(self.config.assets_dir)
        except Exception:  # noqa: BLE001 -- a bare config in a test has none
            return None

    def set_prompt(self, job: Job, scene_idx: int, fields: Dict[str, Any]) -> Job:
        """The producer rewrites a scene's prompt by hand.

        Only at a gate, like an edit: a prompt changed under a running stage
        would describe a generation nobody asked for. It changes the TEXT and
        nothing else -- the plate or clip already bought stays until the
        producer sends that scene back, which is what regenerates it from the
        new words. A rewrite (`revise prompts`) still replaces every prompt."""
        if job.state not in GATES:
            raise TransitionError(f"job {job.id} is in '{job.state}', not at a gate")
        raw = next((s for s in job.scenes if s["idx"] == int(scene_idx)), None)
        if raw is None:
            raise TransitionError(f"job {job.id} has no scene {scene_idx}")
        fields = dict(fields or {})
        unknown = sorted(set(fields) - set(PROMPT_FIELDS))
        if unknown:
            raise TransitionError(
                f"prompt: unknown field(s) {unknown} "
                f"(editable: {', '.join(PROMPT_FIELDS)})")
        changed = []
        for key in PROMPT_FIELDS:
            if key not in fields:
                continue
            text = str(fields[key] or "").strip()
            if key != "end_image_prompt" and not text:
                raise TransitionError(f"prompt: {key} cannot be empty")
            if key == "end_image_prompt" and text and not raw.get("end_image_prompt"):
                raise TransitionError(
                    "prompt: this shot does not transform, so it has no end frame "
                    "to describe -- a transformation is asked for in the brief")
            if text != str(raw.get(key) or ""):
                raw[key] = text
                changed.append(key)
        if not changed:
            raise TransitionError("prompt: nothing changed")
        job.add_event("prompt_edited",
                      f"scene {scene_idx}: {', '.join(changed)} rewritten by hand",
                      scene=int(scene_idx), fields=changed)
        self.store.save(job)
        return job

    def reopen(self, job: Job, note: str = "") -> Job:
        """A finished job back at GATE_DRAFT, so a shot can be regenerated or
        the cut changed without starting a new creative.

        Approving it again re-runs finalize, preflight and delivery; delivery
        never hard-deletes, so the shipped files move to `_to_delete/` and
        the new ones take their names."""
        if job.state != "done":
            raise TransitionError(
                f"job {job.id} is in '{job.state}' -- only a finished job is reopened")
        if not all(s.get("clip") for s in job.scenes):
            raise TransitionError(f"job {job.id} has scenes without a clip")
        job.error = None
        job.state = "GATE_DRAFT"
        job.gate_ready = False
        job.add_event("reopened",
                      note or "back at GATE_DRAFT; the delivered files stay until "
                              "this is approved again")
        self.store.save(job)
        return self.run(job)

    def add_driver(self, job: Job, source, engine: str = "seedance",
                   note: str = "") -> Job:
        """Register a motion driver on the job. Costs nothing."""
        from .. import drivers
        entry = drivers.add(job, self.store.job_dir(job.id), source, engine, note)
        job.add_event(
            "driver_added",
            f"driver {entry['id']} ({entry['duration_s']}s, {entry['engine']}) "
            f"from {entry['source']}" + (f": {note}" if note else ""))
        self.store.save(job)
        return job

    def _attachable(self, job: Job, scenes: List[int]) -> List[int]:
        """The shots a driver may be attached to, or a refusal.

        Separate from `attach_driver` so it can be asked BEFORE a driver is
        registered: registering copies a video into the job, and a refusal after
        that leaves a driver attached to nothing and a file nobody asked for."""
        asked = [int(i) for i in (scenes or [])]
        if not asked:
            raise TransitionError("attach needs the scene(s) to put on the driver")
        known = [s["idx"] for s in job.scenes]
        unknown = [i for i in asked if i not in known]
        if unknown:
            raise TransitionError(f"no scene(s) {unknown} on this job (has {known})")
        return asked

    def drive(self, job: Job, source, scenes: List[int],
              engine: str = "seedance", note: str = "") -> Job:
        """Register a driver and put shots on it, or do neither.

        The two halves are one decision. A driver registered and then not
        attached is a video copied into the job that changes nothing, and -- the
        way that actually costs money -- a plan gate approved with the shots'
        durations not yet retimed to the driver's."""
        self._attachable(job, scenes)
        job = self.add_driver(job, source, engine, note)
        from .. import drivers
        return self.attach_driver(job, drivers.all_of(job)[-1]["id"], scenes)

    def attach_driver(self, job: Job, driver_id: str, scenes: List[int]) -> Job:
        """Point shots at a driver. One driver can serve several.

        Motion Control runs for exactly as long as the driver, so the shot's
        duration becomes the driver's -- the plan's 4-15s clamp does not apply
        and must not be allowed to silently shorten it. That is the whole reason
        the engine is chosen on the driver rather than while writing prompts."""
        from .. import drivers
        driver = drivers.find(job, driver_id)
        asked = self._attachable(job, scenes)
        retimed = []
        for idx in asked:
            scene = job.scene(idx)
            if scene.clip:
                raise TransitionError(
                    f"scene {idx} already has a clip -- attaching a driver now "
                    f"would describe a shot that was not the one bought. Revise "
                    f"the clip instead, which re-buys it.")
            scene.driver = driver_id
            if drivers.is_motion_control(driver["engine"]):
                if abs(scene.duration_s - driver["duration_s"]) > 0.05:
                    retimed.append((idx, scene.duration_s, driver["duration_s"]))
                scene.duration_s = driver["duration_s"]
            job.put_scene(scene)
        job.add_event(
            "driver_attached",
            f"scene(s) {asked} animate from driver {driver_id} "
            f"({driver['engine']})"
            + ("; retimed to the driver: "
               + ", ".join(f"{i} {was}s->{now}s" for i, was, now in retimed)
               if retimed else ""),
            scenes=asked)
        self.store.save(job)
        return job

    def waive(self, job: Job, scenes: List[int], note: str = "") -> Job:
        """Accept named blocking clip verdicts and let the job deliver.

        The alternative people reach for is turning QA off or editing the
        verdict, and both destroy the finding. This keeps it: preflight still
        reports the check as having failed, names the scenes, and records that a
        person accepted them. The waiver travels into the build manifest, so the
        delivered creative carries its own known defects rather than looking
        clean to whoever opens the folder next year.

        A waiver is per-scene and deliberate. There is no waive-everything."""
        from ..qa import blocking_scenes
        blocked = blocking_scenes(job.scenes, "clip_qa")
        asked = [int(i) for i in (scenes or [])]
        if not asked:
            raise TransitionError(
                "waive needs the scene(s) to accept -- there is no blanket "
                f"waiver. Blocking right now: {blocked or 'none'}")
        unknown = [i for i in asked if i not in blocked]
        if unknown:
            raise TransitionError(
                f"scene(s) {unknown} are not blocking, so there is nothing to "
                f"waive. Blocking: {blocked or 'none'}")
        if not note.strip():
            raise TransitionError(
                "a waiver needs a reason: it is the only record of why a known "
                "defect shipped")
        job.meta["waived_clip_qa"] = sorted(
            set(job.meta.get("waived_clip_qa") or []) | set(asked))
        job.meta["waiver_note"] = note.strip()
        issues = []
        for idx in asked:
            verdict = job.scene(idx).clip_qa or {}
            issues += [f"scene {idx}: {i}" for i in (verdict.get("issues") or [])]
        job.add_event(
            "qa_waived",
            f"scene(s) {sorted(asked)} shipped with a critical verdict "
            f"accepted by the producer: {note.strip()}",
            scenes=sorted(asked), issues=issues)
        # Back to `finalize`, not straight to `preflight`: the build manifest is
        # part of the deliverable and it was written before the waiver existed.
        # Delivering the old one would put a file in the week folder whose own
        # record says it shipped clean. Costs nothing -- finalize is ffmpeg.
        if job.state in ("failed", "preflight", "delivery"):
            job.state = "finalize"
            job.error = None
            job.gate_ready = False
        self.store.save(job)
        return job

    def retry(self, job: Job) -> Job:
        """Resume a failed job: put it back on the stage that errored and run."""
        if job.state != "failed":
            return self.run(job)
        failed_state = None
        for ev in reversed(job.events):
            if ev["type"] == "error" and (ev.get("data") or {}).get("failed_state"):
                failed_state = ev["data"]["failed_state"]
                break
        if failed_state is None:
            raise TransitionError(f"job {job.id} failed but no failed_state recorded")
        job.error = None
        job.state = failed_state
        job.add_event("retry", f"retrying from '{failed_state}'")
        self.store.save(job)
        return self.run(job)

    def reassemble(self, job: Job, note: str = "") -> Job:
        """Re-run assembly (and preflight, and delivery) on a job that already has
        its clips. Costs nothing -- everything from `assembly` on is ffmpeg.

        Most of what a producer wants to change late (where the copy sits, the
        disclaimer, the end card, the bed) is assembly work, and without this the
        only ways to change it are re-running paid stages or rebuilding the job."""
        if not any(s.get("clip") for s in job.scenes):
            raise TransitionError(f"job {job.id} has no clips to assemble")
        if job.state in GATES or job.state.startswith(REVISE_PREFIX):
            raise TransitionError(
                f"job {job.id} is at '{job.state}' -- approve or revise it instead")
        job.error = None
        job.gate_ready = False
        job.add_event("reassemble", note or "re-assembling from the existing clips")
        job.state = "assembly"
        self.store.save(job)
        return self.run(job)

    def cancel(self, job: Job, note: str = "") -> Job:
        # A FAILED job may be cancelled: abandoning one rather than retrying is a
        # normal decision, and it is exactly the case where orphaned paid
        # submissions need naming before the job is put down.
        if job.state in ("done", "cancelled"):
            raise TransitionError(f"job {job.id} already terminal ('{job.state}')")
        open_subs = job.open_submissions()
        if open_subs:
            # KIE has no cancel endpoint. Saying "cancelled" while paid tasks are
            # still running would be a lie, so the ids are named in the event and
            # left collectable.
            job.add_event("cancel_with_open_spend",
                          f"{len(open_subs)} submitted generation(s) are already "
                          f"paid for and cannot be cancelled upstream",
                          task_ids=[s["task_id"] for s in open_subs])
        job.add_event("cancelled", note)
        job.state = "cancelled"
        self.store.save(job)
        return job
