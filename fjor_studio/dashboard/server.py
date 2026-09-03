"""The producer dashboard: one page, stdlib only.

No web framework on purpose -- this is a single-user tool bound to localhost,
and a dependency-free server is one less thing to install on the next machine.

The UI principle, taken from the Factory: the producer sees the whole pipeline,
is shown the cost BEFORE approving it, and can revise a single scene without
redoing the job.
"""
from __future__ import annotations

import hmac
import json
import mimetypes
import os
import posixpath
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..app import new_job, open_studio
from ..engine.job import utcnow
from ..assemble import list_music, list_packshots, music_for
from .. import kit as kit_mod
from .. import library as library_mod
from ..library import LibraryError
from ..kit import KitError
from ..gen.base import GenError
from ..qa import blocking_scenes
from ..refkind import KINDS as REF_KINDS
from ..stages.dub_steps import LANGUAGES as DUB_LANGUAGES
from .. import dubband
from ..subtitles import COLOURS as SUB_COLOURS
from ..config import UnknownVertical
from ..derive import FROM_STAGES, DeriveError, derive
from ..derive import plan as derive_plan
from ..engine import GATES, PIPELINE, REVISABLE, TERMINAL, TransitionError
from .page import PAGE
from .worker import Worker

SAFE_MEDIA = re.compile(r"^[A-Za-z0-9._/ +-]+$")
MEDIA_DIRS = ("plates", "clips", "draft", "finals", "review", "ref", "audio")
CHUNK = 256 * 1024
# A reference ad is seconds long, not a feature film. The cap is generous rather
# than tight, but it exists: without one a mis-drop streams until the disk fills.
MAX_UPLOAD = 2 * 1024 * 1024 * 1024
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv", ".mpg", ".mpeg"}

# Distinct from None, which means "no Range header at all". A malformed or
# unsatisfiable range must answer 416, not quietly send the whole file.
INVALID_RANGE = object()

_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def parse_range(header: Optional[str], size: int):
    """`bytes=start-end`, `bytes=start-`, `bytes=-suffix`. Returns None when
    there is no range to honour, INVALID_RANGE when the client asked for one
    that cannot be satisfied, else an inclusive (start, end)."""
    if not header:
        return None
    m = _RANGE.match(header.strip())
    if not m:
        return INVALID_RANGE
    raw_start, raw_end = m.group(1), m.group(2)
    if not raw_start and not raw_end:
        return INVALID_RANGE
    if size == 0:
        return INVALID_RANGE
    if not raw_start:                      # bytes=-500 -> the last 500 bytes
        suffix = int(raw_end)
        if suffix == 0:
            return INVALID_RANGE
        return (max(0, size - suffix), size - 1)
    start = int(raw_start)
    if start >= size:
        return INVALID_RANGE
    end = int(raw_end) if raw_end else size - 1
    end = min(end, size - 1)
    if end < start:
        return INVALID_RANGE
    return (start, end)


class Studio:
    """Everything the HTTP layer is allowed to touch."""

    def __init__(self, home: Optional[Path] = None):
        self.home = Path(home) if home else None
        self._lock = threading.Lock()
        self.worker = Worker(self._run_action)
        self._dub_lock = threading.Lock()

    def open(self):
        # rebuilt per request: config, routing and the asset library are all
        # editable while the server runs, and a producer who fixes a config
        # should not have to restart to see it take
        return open_studio(self.home)

    # -- actions -------------------------------------------------------------
    def _run_action(self, job_id: str, action: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            _cfg, store, engine = self.open()
            if action == "dub_upload":
                # the "job_id" here is the upload's token: there is no job. The
                # source was produced elsewhere and dropped on the dashboard.
                return self._dub_upload(job_id, payload)
            job = store.load(job_id)
            if action == "run":
                engine.run(job)
            elif action == "approve":
                engine.approve(job, payload.get("note", ""))
            elif action == "revise":
                engine.revise(job, payload["what"], payload.get("note", ""),
                              payload.get("scenes") or None)
            elif action == "retry":
                engine.retry(job)
            elif action == "edit":
                engine.set_edit(job, payload.get("edit") or {},
                                recut=bool(payload.get("recut", True)))
            elif action == "reassemble":
                engine.reassemble(job, payload.get("note", ""))
            elif action == "cancel":
                engine.cancel(job, payload.get("note", ""))
            elif action == "waive":
                engine.waive(job, payload.get("scenes") or [],
                             (payload.get("note") or "").strip())
            elif action == "prompt":
                engine.set_prompt(job, int(payload.get("scene", -1)),
                                  payload.get("fields") or {})
            elif action == "reopen":
                engine.reopen(job, (payload.get("note") or "").strip())
            elif action == "driver":
                engine.drive(job, payload["source"], payload.get("scenes") or [],
                             payload.get("engine") or "seedance",
                             (payload.get("note") or "").strip())
            else:
                raise ValueError(f"unknown action '{action}'")

    # -- reads ---------------------------------------------------------------
    def overview(self) -> Dict[str, Any]:
        cfg, store, _engine = self.open()
        jobs = []
        for job in store.load_all():
            jobs.append({
                "id": job.id, "state": job.state, "spent": round(job.spent, 1),
                "gate_ready": job.gate_ready, "error": job.error,
                "vertical": job.intake.get("vertical"),
                "week": job.intake.get("week"),
                "concept": job.intake.get("concept"),
                "updated_at": job.updated_at,
                "scenes": len(job.scenes),
                "busy": self.worker.queued_for(job.id),
            })
        jobs.sort(key=lambda j: j["updated_at"], reverse=True)
        assets = cfg.assets_dir
        return {
            "jobs": jobs,
            "pipeline": PIPELINE,
            "gates": sorted(GATES),
            "terminal": sorted(TERMINAL),
            "busy": self.worker.busy_with(),
            "activity": self.worker.activity(),
            "options": {
                "verticals": sorted((cfg.verticals.get("verticals") or {})),
                "prefix_map": {str(e.get("prefix", "")).upper(): k for k, e
                               in (cfg.verticals.get("verticals") or {}).items()},
                "packshots": list_packshots(assets),
                "delivery": self.delivery_status(),
                # NAMES only. A value never reaches the page, and the page
                # never asks: the whole point of a kit is that the keys stop
                # existing anywhere they can be copied from.
                "keys": {"source": kit_mod.source() or
                                   ("config/auth.yaml" if cfg.auth else ""),
                         "providers": sorted(
                             k for k, v in (cfg.auth or {}).items()
                             if isinstance(v, dict)
                             and str(v.get("api_key") or "").strip())},
                "ref_kinds": sorted(REF_KINDS),
                "dub_languages": sorted(DUB_LANGUAGES.items()),
                "dub_defaults": {"y_pct": dubband.BAND_Y_PCT,
                                 "h_pct": dubband.BAND_H_PCT,
                                 "feather": dubband.FEATHER_DEFAULT,
                                 "strength": dubband.STRENGTH_DEFAULT},
                "ref_kind_default": str(((cfg.pipeline or {}).get("analysis")
                                         or {}).get("ref_kind", "ugc")),
                "music": list_music(assets),
                "library": library_mod.list_items(assets),
                "formats": list(((cfg.pipeline or {}).get("delivery") or {})
                                .get("formats", [])),
                "providers": cfg.routing,
                "models": (cfg.models.get("models") or {}),
                "delivery_root": str(cfg.delivery.get("root")),
            },
        }

    def detail(self, job_id: str) -> Dict[str, Any]:
        cfg, store, _engine = self.open()
        job = store.load(job_id)
        forecast_key = {"GATE_PLAN": "plates", "GATE_PLATES": "clips"}.get(job.state)
        return {
            "id": job.id, "state": job.state, "gate_ready": job.gate_ready,
            "error": job.error, "intake": job.intake, "meta": job.meta,
            "spent": round(job.spent, 1),
            "spent_by_backend": {k: round(v, 1)
                                 for k, v in job.spent_by_backend().items()},
            "scenes": job.scenes,
            "ledger": job.ledger[-60:],
            "events": job.events[-40:][::-1],
            "revisions": job.revisions,
            "forecasts": job.forecasts,
            "next_forecast": job.forecasts.get(forecast_key) if forecast_key else None,
            "artifacts": job.artifacts,
            "revisable": sorted(REVISABLE.get(job.state, {})),
            # Which shots are stopping the delivery, decided by the same policy
            # preflight uses -- a speech-only verdict under an external voice is
            # not blocking, and a waived one no longer is.
            "blocking": blocking_scenes(job.scenes, "clip_qa"),
            "open_submissions": job.open_submissions(),
            "busy": self.worker.queued_for(job.id),
            "analysis": (job.analysis.get("text") or "")[:4000],
            "week_dir": job.meta.get("week_dir"),
            "finals": self._finals(job),
            "cast": [{"id": c["id"], "description": c.get("description", ""),
                      "plate": c.get("plate"), "qa": c.get("qa")}
                     for c in (job.cast or [])],
            "derive": self._derive_options(cfg, job),
            "derived_from": job.meta.get("derived_from"),
            "derivatives": job.meta.get("derivatives") or [],
            "edit": self._edit(cfg, job),
            "next_id": self._next_id(cfg, store, job),
            "derive_name": self._suggested_name(cfg, store, job),
        }

    def _edit(self, cfg, job) -> Dict[str, Any]:
        """The editor bar's state and the libraries it offers from.

        Offered only at a gate that has clips to arrange: before them there is
        nothing to order, and after GATE_DRAFT the cut is approved."""
        from ..assemble import list_music
        from ..stages.steps import cut_scenes, edit_of
        from pathlib import Path as _P
        assets = _P(cfg.assets_dir)
        current = edit_of(job)
        subs = dict((cfg.pipeline or {}).get("subtitles") or {})
        subs.update(current.get("subtitles") or {})
        return {
            "open": job.state in ("GATE_CLIPS", "GATE_DRAFT")
                    and bool(job.scenes) and all(s.get("clip") for s in job.scenes),
            "order": [s["idx"] for s in cut_scenes(job)],
            "dropped": [s["idx"] for s in job.scenes
                        if s["idx"] not in {c["idx"] for c in cut_scenes(job)}],
            "music": current.get("music", ""),
            "music_library": list_music(assets),
            "hook": current.get("hook", ""),
            "insert": current.get("insert", ""),
            "library": library_mod.list_items(assets),
            "subtitles": {"enabled": bool(subs.get("enabled", True)),
                          "style": subs.get("style", "bold-pop"),
                          "colour": subs.get("colour", subs.get("color", "yellow")),
                          "size": subs.get("size", "medium")},
            # `bold-pop` is the only style the renderer implements -- `highlight`
            # and `karaoke` are still unported (PORTING_NOTES 4). Offering them
            # in a dropdown would be a control that silently does nothing, so
            # what is offered here is what actually changes the cut.
            "subtitle_colours": sorted(SUB_COLOURS),
            "subtitle_sizes": ["small", "medium", "large"],
            # a re-cut is ffmpeg only; saying so where the button is stops the
            # producer treating an edit as something that might cost credits
            "recut_costs": 0.0,
        }

    def _finals(self, job) -> List[Dict[str, Any]]:
        """Watchable on the page, not only present in the week folder."""
        out = []
        manifest = {f["file"]: f for f in (job.meta.get("finals_manifest") or [])}
        for rel in sorted(job.artifacts.get("finals") or []):
            name = rel.split("/")[-1]
            if not name.startswith("n-"):
                continue
            entry = {"file": name, "rel": rel}
            entry.update({k: v for k, v in (manifest.get(name) or {}).items()
                          if k in ("format", "duration_s", "actual",
                                   "subtitle_lines", "has_audio")})
            out.append(entry)
        return out

    def _derive_options(self, cfg, job) -> List[Dict[str, Any]]:
        """What each starting point would cost, before anything is created."""
        if job.state != "done" or not job.scenes:
            return []
        from .. import costs
        opts = []
        for stage in FROM_STAGES:
            try:
                p = derive_plan(job, stage)
            except DeriveError:
                continue
            lines = []
            if "plates" in p["rebuys"]:
                lines += [costs.line("plates", cfg.routing.get("image", "?"),
                                     cfg.model_for("image"), scene=s["idx"],
                                     kind="image") for s in job.scenes]
            if "clips" in p["rebuys"]:
                lines += [costs.line("clips", cfg.routing.get("video", "?"),
                                     cfg.model_for("video"),
                                     duration_s=float(s["duration_s"]),
                                     scene=s["idx"], kind="video")
                          for s in job.scenes]
            f = costs.forecast(lines)
            opts.append(dict(p, cost=f.total, cost_complete=f.complete))
        return opts

    def _suggested_name(self, cfg, store, job) -> Optional[str]:
        """A ready-made name for the variation.

        BUILT rather than copied: jobs made before the creative-name field, or
        from the CLI without --name, have nothing to copy, and an empty box is
        the one thing the producer would then have to retype by hand."""
        from .. import naming
        nxt = self._next_id(cfg, store, job)
        if not nxt or not job.intake.get("concept"):
            return None
        sizes = cfg.sizes
        w, h = sizes.get("4:5") or next(iter(sizes.values()), (1080, 1350))
        cfg_naming = cfg.delivery.get("naming") or {}
        try:
            return naming.build(
                nxt, job.intake["concept"], job.intake["week"], w, h,
                producer=job.intake.get("producer")
                or cfg_naming.get("default_producer", "lp"),
                channel=cfg_naming.get("channel", "fb"),
                type_=cfg_naming.get("type", "video"),
                source=cfg_naming.get("source", "nano"))[:-4]
        except (KeyError, ValueError):
            return None

    def _next_id(self, cfg, store, job) -> Optional[str]:
        from ..ids import delivered_ids, next_id, parse as parse_id
        try:
            prefix, _n = parse_id(job.id)
        except ValueError:
            return None
        taken = set(store.list_ids()) | delivered_ids(cfg.delivery.get("root"))
        return next_id(prefix, taken)

    def create(self, form: Dict[str, Any]) -> str:
        """Built from a pasted creative name.

        The name already carries the id, week, concept and producer, and its
        prefix says which vertical -- so it replaces four fields the producer
        would otherwise retype from a sheet they already have open."""
        from ..ids import parse as parse_id
        from ..naming import parse_name
        cfg, store, _engine = self.open()
        parsed = parse_name(form.get("creative_name", ""))
        prefix, _n = parse_id(parsed["id"])
        vertical = form.get("vertical") or cfg.vertical_for_prefix(prefix)
        if not vertical:
            known = ", ".join(
                f"{e.get('prefix')}={k}"
                for k, e in (cfg.verticals.get("verticals") or {}).items())
            raise ValueError(
                f"no vertical uses the id prefix '{prefix}'. Known: {known}")
        from ..stages.banner_steps import BANNER_SUFFIXES
        source = form.get("reference") or form.get("banner") or ""
        # Same rule as the CLI: the suffix decides which pipeline. A job
        # carrying both keys is refused at intake before anything is paid for.
        key = ("banner" if Path(str(source)).suffix.lower() in BANNER_SUFFIXES
               else "reference")
        intake = {
            key: source,
            "week": parsed["week"],
            "concept": parsed["concept"],
            "producer": parsed["producer"],
            "brief": (form.get("brief") or "").strip(),
            "packshot": form.get("packshot") or None,
            "music": form.get("music") or None,
            "creative_name": form["creative_name"].strip(),
        }
        for field in ("morph", "text_card", "ref_kind", "banner_engine"):
            if (form.get(field) or "").strip():
                intake[field] = form[field].strip()
        if form.get("scenes") not in (None, ""):
            intake["scene_count"] = int(form["scenes"])
        if form.get("crossfade_s") not in (None, ""):
            intake["crossfade_s"] = float(form["crossfade_s"])
        job = new_job(store, cfg, vertical, intake, job_id=parsed["id"])
        return job.id

    def delete_job(self, job_id: str) -> Dict[str, Any]:
        """Retire a job and free its creative id.

        `store.delete` moves it into `_deleted/` rather than unlinking, so a
        mis-click costs nothing and paid media stays recoverable. Refused only
        while the worker holds it: deleting a directory out from under a running
        stage would lose a generation that has already been paid for."""
        if self.worker.queued_for(job_id):
            raise ValueError(
                f"{job_id} is running. Cancel it first, then delete -- removing "
                f"a job mid-stage loses a generation that may already be paid "
                f"for.")
        cfg, store, _engine = self.open()
        job = store.load(job_id)
        moved = store.delete(job_id)
        return {"id": job_id, "moved_to": str(moved), "state": job.state,
                "spent": round(job.spent, 1)}

    def delivery_status(self) -> Dict[str, Any]:
        """Where finals will land, and whether that can work.

        Reported whether or not it is set: a producer on a new machine should
        meet this as a setting to fill in, not as a refusal three clicks later."""
        from ..config import MissingDeliveryRoot
        cfg, _store, _engine = self.open()
        week_folder = str(cfg.delivery.get("week_folder", "{week} week"))
        try:
            root = cfg.delivery_root
        except MissingDeliveryRoot:
            return {"root": "", "set": False, "week_folder": week_folder,
                    "example": "", "problem": ""}
        # An example is worth more than a description: a team whose folders are
        # arranged differently can see the shape and say so before a job runs.
        try:
            vertical = sorted(cfg.verticals.get("verticals") or {})[0]
            example = str(cfg.week_dir(vertical, 34))
        except Exception:  # noqa: BLE001
            example = str(root)
        problem = ""
        if not root.parent.exists():
            problem = (f"{root.parent} does not exist. If that is a network "
                       f"volume, mount it; if it is a typo, fix it -- the root "
                       f"itself may be missing and will be created, but its "
                       f"parent must be there.")
        elif root.exists() and not os.access(root, os.W_OK):
            problem = f"{root} is not writable by this user."
        return {"root": str(root), "set": True, "week_folder": week_folder,
                "example": example, "problem": problem}

    def set_delivery(self, root: str, week_folder: str = "") -> Dict[str, Any]:
        """Write the root into config/delivery.yaml, by LINE.

        A whole-file rewrite through a YAML dumper would throw away every
        comment in that file, and those comments are the only explanation of
        the naming template a deployer gets."""
        import re as _re
        root = str(root or "").strip()
        if not root:
            raise ValueError("give a folder for the finals to be delivered into")
        path = Path(root).expanduser()
        if not path.parent.exists():
            raise ValueError(
                f"{path.parent} does not exist, so {path} cannot be created "
                f"there. Mount the volume, or check the path.")
        cfg, _store, _engine = self.open()
        target = cfg.home / "config" / "delivery.yaml"
        text = target.read_text()
        new, count = _re.subn(r'^root:.*$', f'root: "{path}"', text,
                              count=1, flags=_re.M)
        if not count:
            raise ValueError(
                f"{target} has no `root:` line to set -- edit it by hand.")
        if week_folder.strip():
            if "{week}" not in week_folder:
                raise ValueError(
                    "the week folder must contain {week}, or every week of "
                    "every vertical would deliver into one directory.")
            new = _re.subn(r'^week_folder:.*$',
                           f'week_folder: "{week_folder.strip()}"', new,
                           count=1, flags=_re.M)[0]
        target.write_text(new)
        return self.delivery_status()

    # -- verticals -----------------------------------------------------------
    def add_vertical(self, form: Dict[str, Any]) -> Dict[str, Any]:
        """Register a vertical from the dashboard: an id prefix and a delivery
        folder, appended to config/verticals.yaml.

        Appended as TEXT rather than re-dumped: the file carries the owner's
        notes on why each prefix is what it is, and a dump would erase them.
        The file is then re-read to prove the entry took, and the append is
        undone if it did not -- a config that no longer parses would stop
        every job, not only this one."""
        cfg, _store, _engine = self.open()
        # the same normalisation the page applies as the name is typed, so a
        # name pasted straight into the API lands in the same shape
        name = re.sub(r"[^a-z0-9]+", "_", str(form.get("name") or "").lower()).strip("_")
        prefix = str(form.get("prefix") or "").strip().upper()
        folder = str(form.get("folder") or "").strip()
        if not re.match(r"^[a-z][a-z0-9_]{1,40}$", name):
            raise ValueError("the name is lowercase letters, digits and underscores, "
                             "like `strong_legs`")
        if not re.match(r"^[A-Z]{1,5}$", prefix):
            raise ValueError("the id prefix is 1-5 capital letters, like `SL` -- "
                             "it opens every creative id (SL001)")
        if not folder or len(folder) > 60 or "/" in folder or "\\" in folder \
                or ".." in folder or folder.startswith("."):
            raise ValueError("the delivery folder is a single folder name, like "
                             "`STRONG LEGS` -- it is created under the delivery root")
        existing = cfg.verticals.get("verticals") or {}
        if name in existing:
            raise ValueError(f"'{name}' is already a vertical")
        for k, e in existing.items():
            if str(e.get("prefix", "")).upper() == prefix:
                raise ValueError(f"prefix {prefix} already belongs to {k} -- an id "
                                 f"has to say which vertical it is for")
            if str(e.get("folder", "")).strip().lower() == folder.lower():
                raise ValueError(f"folder '{folder}' already belongs to {k}")
        target = cfg.home / "config" / "verticals.yaml"
        before = target.read_text(encoding="utf-8") if target.exists() else "verticals:\n"
        if "verticals:" not in before:
            before = before.rstrip("\n") + "\nverticals:\n"
        folder_yaml = json.dumps(folder, ensure_ascii=False)
        line = (f"  # Added from the dashboard {time.strftime('%Y-%m-%d')}.\n"
                f"  {name}: {{prefix: {json.dumps(prefix)}, folder: {folder_yaml}}}\n")
        after = before if before.endswith("\n") else before + "\n"
        target.write_text(after + line, encoding="utf-8")
        try:
            check = self.open()[0].verticals.get("verticals") or {}
            entry = check.get(name)
            if not entry or str(entry.get("prefix")) != prefix \
                    or str(entry.get("folder")) != folder:
                raise ValueError("the entry did not read back as written")
        except Exception as exc:  # noqa: BLE001
            target.write_text(before, encoding="utf-8")
            raise ValueError(f"could not add the vertical: {exc}")
        return {"name": name, "prefix": prefix, "folder": folder}

    # -- the clip library ----------------------------------------------------
    def library_items(self) -> Dict[str, Any]:
        cfg, _store, _engine = self.open()
        return {"items": library_mod.list_items(cfg.assets_dir)}

    def library_add(self, form: Dict[str, Any]) -> Dict[str, Any]:
        """An upload (already staged by /api/uploads) into the library."""
        cfg, _store, _engine = self.open()
        src = Path(str(form.get("path") or ""))
        staged = (cfg.home / "uploads").resolve()
        if not src.is_file() or not str(src.resolve()).startswith(str(staged) + os.sep):
            raise ValueError("drop the clip first -- only a staged upload goes in")
        item = library_mod.add_upload(cfg.assets_dir, src,
                                      str(form.get("name") or src.stem))
        # the upload's own directory is empty now that its file has moved
        try:
            src.parent.rmdir()
        except OSError:
            pass
        return item

    def library_remove(self, item_id: str) -> Dict[str, Any]:
        cfg, _store, _engine = self.open()
        return library_mod.remove(cfg.assets_dir, item_id)

    def keep_clip(self, job_id: str, form: Dict[str, Any]) -> Dict[str, Any]:
        cfg, store, _engine = self.open()
        job = store.load(job_id)
        return library_mod.keep_generation(
            cfg.assets_dir, job, store.job_dir(job.id),
            int(form.get("scene", -1)), str(form.get("name") or ""))

    def library_path(self, item_id: str) -> Path:
        cfg, _store, _engine = self.open()
        path = library_mod.item_path(cfg.assets_dir, item_id)
        if path is None:
            raise FileNotFoundError(item_id)
        return path

    def music_path(self, name: str) -> Path:
        """A bed, by the name the picker shows. Resolved through the library
        listing, so only a file the picker would offer is ever served."""
        cfg, _store, _engine = self.open()
        if ".." in str(name):
            raise ValueError("bad bed name")
        path = music_for(cfg.assets_dir, name)
        if path is None:
            raise FileNotFoundError(name)
        return path

    def receive_upload(self, filename: str, stream, length: int) -> Dict[str, Any]:
        """Take a dropped file and put it somewhere a job can reference.

        The browser will not tell us where the file came from -- a dropped File
        has no path, by design -- so the bytes themselves have to travel. They
        are streamed to disk rather than read into memory, and probed before
        being accepted: a reference with no video stream fails here, in a dialog,
        instead of three stages later inside a paid run."""
        from ..stages.banner_steps import BANNER_SUFFIXES
        cfg, _store, _engine = self.open()
        safe = safe_filename(filename)
        suffix = Path(safe).suffix.lower()
        # An image is a finished banner to expand and animate; a video is a
        # reference to analyse and re-create. Two different pipelines, decided
        # here so the dialog can SAY which one before anything is created --
        # their tool announces it with a toast for the same reason.
        kind = ("banner" if suffix in BANNER_SUFFIXES
                else "reference" if suffix in VIDEO_SUFFIXES else "")
        if not kind:
            raise ValueError(
                f"'{safe}' is neither a reference video "
                f"({', '.join(sorted(VIDEO_SUFFIXES))}) nor a banner image "
                f"({', '.join(sorted(BANNER_SUFFIXES))})")
        if length <= 0:
            raise ValueError("empty upload")
        if length > MAX_UPLOAD:
            raise ValueError(f"{length / 1e9:.1f} GB is over the "
                             f"{MAX_UPLOAD / 1e9:.0f} GB upload cap")
        import uuid
        dest_dir = cfg.home / "uploads" / uuid.uuid4().hex[:12]
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / safe
        written = 0
        try:
            with open(dest, "wb") as f:
                while written < length:
                    chunk = stream.read(min(CHUNK, length - written))
                    if not chunk:
                        break
                    f.write(chunk)
                    written += len(chunk)
            if written != length:
                raise ValueError(f"upload truncated at {written} of {length} bytes")
            from ..assemble import probe
            info = probe(dest)
            video = next((st for st in info.get("streams") or []
                          if st.get("codec_type") == "video"), None)
            if video is None:
                raise ValueError(
                    f"'{safe}' has no {'image' if kind == 'banner' else 'video'} "
                    f"stream -- the file is named like one but is not one")
            out = {
                "path": str(dest), "name": safe, "size": written, "kind": kind,
                # the upload's own directory name: how a dub refers back to it
                # without the browser ever handling a filesystem path
                "token": dest_dir.name,
                "width": int(video.get("width") or 0),
                "height": int(video.get("height") or 0),
            }
            if kind == "banner":
                # What the expansion will have to paint, in pixels, before the
                # producer commits to it. A banner already vertical needs none.
                from .. import banner as banner_mod
                place = banner_mod.placement(out["width"], out["height"])
                out["expansion"] = {"top": place["top"], "bottom": place["bottom"]}
            else:
                out["duration_s"] = round(float((info.get("format") or {})
                                                .get("duration") or 0), 2)
                out["has_audio"] = any(st.get("codec_type") == "audio"
                                       for st in info.get("streams") or [])
        except Exception:
            import shutil as _sh
            _sh.rmtree(dest_dir, ignore_errors=True)
            raise
        return out

    def derive(self, source_id: str, form: Dict[str, Any]) -> str:
        from ..ids import parse as parse_id
        from ..naming import parse_name
        cfg, store, _engine = self.open()
        parsed = parse_name(form.get("creative_name", ""))
        overrides: Dict[str, Any] = {
            "week": parsed["week"], "concept": parsed["concept"],
            "producer": parsed["producer"],
            "creative_name": form["creative_name"].strip(),
        }
        for key in ("packshot", "music"):
            if key in form and form[key] != "":
                overrides[key] = form[key]
        if form.get("crossfade_s") not in (None, ""):
            overrides["crossfade_s"] = float(form["crossfade_s"])
        if form.get("vertical"):
            vert = cfg.vertical(form["vertical"], strict=True)
            overrides["vertical"] = form["vertical"]
            overrides["folder"] = vert["folder"]
        job = derive(store, source_id, parsed["id"],
                     form.get("from", "assembly"), overrides,
                     (form.get("note") or "").strip(),
                     recast=bool(form.get("recast")),
                     cast_descriptions=form.get("cast_descriptions") or None)
        return job.id

    # -- dubbing -------------------------------------------------------------
    #
    # The source is an UPLOAD -- the owner's own creative, produced elsewhere.
    # So the old burnt-in subtitles are pixels of unknown position, and where
    # the band goes is the producer's call. Their tool has a mouse for it; this
    # has a still frame, which is the part that actually matters.

    def _dub_dir(self, token: str) -> Path:
        cfg, _store, _engine = self.open()
        if not re.fullmatch(r"[A-Za-z0-9]{4,40}", token or ""):
            raise ValueError("bad dub token")
        return cfg.home / "dubs" / token

    def _dub_source(self, token: str) -> Path:
        cfg, _store, _engine = self.open()
        if not re.fullmatch(r"[A-Za-z0-9]{4,40}", token or ""):
            raise ValueError("bad upload token")
        up = cfg.home / "uploads" / token
        videos = [f for f in sorted(up.glob("*"))
                  if f.is_file() and f.suffix.lower() in VIDEO_SUFFIXES]
        if not videos:
            raise FileNotFoundError(f"no uploaded video under {token}")
        return videos[0]

    def _band_from(self, payload: Dict[str, Any], width: int,
                   height: int) -> Dict[str, Any]:
        from ..stages import dub_steps
        from .. import dubband
        def num(key, default):
            try:
                return float(payload.get(key, default))
            except (TypeError, ValueError):
                return default
        return dub_steps.band(
            width, height, y_pct=num("y_pct", dubband.BAND_Y_PCT),
            h_pct=num("h_pct", dubband.BAND_H_PCT),
            feather=num("feather", dubband.FEATHER_DEFAULT),
            strength=num("strength", dubband.STRENGTH_DEFAULT))

    def dub_preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """One still with the band on it. Costs nothing; a dub does not."""
        from ..assemble import ffmpeg_with_libass, probe
        from ..stages import dub_steps
        token = str(payload.get("token") or "")
        source = self._dub_source(token)
        info = probe(source)
        stream = next((st for st in info.get("streams") or []
                       if st.get("codec_type") == "video"), {})
        width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
        if not width or not height:
            raise ValueError(f"{source.name} has no readable video size")
        geom = self._band_from(payload, width, height)
        try:
            at = max(0.0, float(payload.get("at", 0)))
        except (TypeError, ValueError):
            at = 0.0
        out = self._dub_dir(token)
        dest = dub_steps.preview(source, out / "preview.png", geom,
                                 ffmpeg_with_libass(), at_seconds=at)
        duration = round(float((info.get("format") or {}).get("duration") or 0), 2)
        return {"token": token, "name": source.name, "width": width,
                "height": height, "duration_s": duration,
                "band": {k: geom[k] for k in ("BY", "BH", "r", "F")},
                "url": f"/dubmedia/{token}/{dest.name}?t={int(time.time())}",
                "forecast": dub_steps.forecast(source)}

    def dub_start(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Check everything checkable BEFORE the money: the file, the language,
        the key, and that this is not already a dub."""
        from ..stages import dub_steps
        token = str(payload.get("token") or "")
        source = self._dub_source(token)
        lang = str(payload.get("lang") or "").strip().lower()
        dub_steps.language_name(lang)
        dub_steps.dubbed_name(source.name, lang)     # refuses a dub of a dub
        cfg, _store, _engine = self.open()
        if not ((cfg.auth or {}).get("elevenlabs") or {}).get("api_key"):
            raise ValueError(
                "dubbing needs an ElevenLabs key -- upload a kit above, or set "
                "elevenlabs.api_key in config/auth.yaml")
        if self.worker.queued_for(token):
            raise ValueError(f"{source.name} is already being dubbed")
        self.worker.submit(token, "dub_upload", dict(payload, lang=lang))
        return {"token": token, "lang": lang, "queued": True,
                "forecast": dub_steps.forecast(source)}

    def _dub_upload(self, token: str, payload: Dict[str, Any]) -> None:
        from ..assemble import probe
        from ..stages import dub_steps
        cfg, _store, _engine = self.open()
        source = self._dub_source(token)
        lang = str(payload.get("lang") or "").strip().lower()
        out = self._dub_dir(token) / lang
        state = self._dub_dir(token) / "state.json"

        info = probe(source)
        stream = next((st for st in info.get("streams") or []
                       if st.get("codec_type") == "video"), {})
        geom = self._band_from(payload, int(stream.get("width") or 1080),
                               int(stream.get("height") or 1920))
        key = ((cfg.auth or {}).get("elevenlabs") or {}).get("api_key", "")

        def note(kind, msg, **data):
            """The dubbing id, on disk, the moment it is accepted -- it is paid
            from that instant and an id nobody wrote down cannot be collected."""
            self._dub_write(state, lang, {"stage": msg, **data})

        self._dub_write(state, lang, {"stage": "starting", "source": source.name})
        try:
            got = dub_steps.dub_video(source, out, lang, key, geom=geom,
                                      on_progress=lambda m: self._dub_write(
                                          state, lang, {"stage": m}),
                                      record=note)
        except Exception as exc:  # noqa: BLE001
            self._dub_write(state, lang,
                            {"stage": "failed", "error": f"{type(exc).__name__}: {exc}"})
            raise
        named = got["video"].parent / dub_steps.dubbed_name(source.name, lang)
        got["video"].replace(named)
        self._dub_write(state, lang, {
            "stage": "done", "file": named.name, "words": got["words"],
            "subtitles": got["subtitles"], "note": got["note"],
            "dubbing_id": got["dubbing_id"], "source": source.name,
            "url": f"/dubmedia/{token}/{lang}/{named.name}"})

    def _dub_write(self, state_path: Path, lang: str,
                   patch: Dict[str, Any]) -> None:
        with self._dub_lock:
            try:
                data = json.loads(state_path.read_text())
            except Exception:  # noqa: BLE001
                data = {}
            entry = data.setdefault(lang, {})
            entry.update(patch)
            entry["at"] = utcnow()
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(data, indent=2))

    def dubs(self) -> List[Dict[str, Any]]:
        """Every dub this studio has bought, so a producer can find one back."""
        cfg, _store, _engine = self.open()
        root = cfg.home / "dubs"
        out: List[Dict[str, Any]] = []
        if not root.is_dir():
            return out
        for d in sorted(root.iterdir(), reverse=True):
            try:
                data = json.loads((d / "state.json").read_text())
            except Exception:  # noqa: BLE001
                continue
            for lang, entry in sorted(data.items()):
                out.append(dict(entry, token=d.name, lang=lang,
                                busy=self.worker.queued_for(d.name)))
        return out

    def dub_media(self, token: str, rel: str) -> Path:
        if not SAFE_MEDIA.match(rel) or ".." in rel:
            raise ValueError("bad media path")
        root = self._dub_dir(token).resolve()
        path = (root / rel).resolve()
        if not str(path).startswith(str(root) + os.sep):
            raise ValueError("path escapes the dub directory")
        if not path.is_file():
            raise FileNotFoundError(rel)
        return path

    def media_path(self, job_id: str, rel: str) -> Path:
        _cfg, store, _engine = self.open()
        if not SAFE_MEDIA.match(rel) or ".." in rel:
            raise ValueError("bad media path")
        top = rel.split("/", 1)[0]
        if top not in MEDIA_DIRS:
            raise ValueError(f"'{top}' is not a servable directory")
        root = store.job_dir(job_id).resolve()
        path = (root / rel).resolve()
        if not str(path).startswith(str(root) + os.sep):
            raise ValueError("path escapes the job directory")
        if not path.is_file():
            raise FileNotFoundError(rel)
        return path


def safe_filename(name: str) -> str:
    """Whatever the browser sends, only a bare filename comes out. A dropped
    file's name is attacker-controlled in principle and a path in practice on
    some platforms."""
    base = str(name or "").replace("\\", "/").split("/")[-1].strip()
    base = re.sub(r"[^A-Za-z0-9._ +-]", "_", base).lstrip(".")
    if not base:
        return "reference.mp4"
    # truncate the STEM, never the suffix -- the extension is what the video
    # check reads, so trimming it turns a long filename into a rejected one
    stem, dot, suffix = base.rpartition(".")
    if dot and len(suffix) <= 5:
        return (stem[:110] + "." + suffix) if stem else base[:120]
    return base[:120]


LOOPBACK = {"127.0.0.1", "::1", "localhost", ""}
COOKIE = "fjor_token"


def is_loopback(host: str) -> bool:
    return str(host).strip().lower() in LOOPBACK


def resolve_token(cfg, explicit: Optional[str] = None) -> str:
    """$FJOR_STUDIO_TOKEN, then auth.yaml `dashboard.token`. Never generated:
    a token this process invents would be printed once and then differ on every
    restart, which teaches people to ignore it."""
    if explicit:
        return str(explicit)
    env = os.environ.get("FJOR_STUDIO_TOKEN")
    if env:
        return env
    return str(((getattr(cfg, "auth", None) or {}).get("dashboard") or {})
               .get("token") or "")


def make_handler(studio: Studio, token: str = ""):
    class Handler(BaseHTTPRequestHandler):
        server_version = "fjor-studio"

        def log_message(self, fmt, *args):  # quieter console
            pass

        # -- access ----------------------------------------------------------
        # Every button on this page spends money -- approving GATE_PLATES on
        # LIPIL025 committed 843 credits in one click -- and the media routes
        # serve unreleased client work. With no token configured the server is
        # loopback-only and behaves as it always has; `serve()` refuses to bind
        # anywhere else without one.
        def _token_offered(self) -> str:
            sent = self.headers.get("X-Studio-Token")
            if sent:
                return sent
            cookie = self.headers.get("Cookie") or ""
            for part in cookie.split(";"):
                name, _, value = part.strip().partition("=")
                if name == COOKIE:
                    return value
            return ""

        def _authorised(self) -> bool:
            if not token:
                return True
            return hmac.compare_digest(self._token_offered(), token)

        def _claim_from_query(self) -> bool:
            """A link with ?token=... is how a person gets in the first time.
            It is exchanged for a cookie and redirected away immediately, so the
            token stops travelling in URLs (and out of the address bar)."""
            if not token:
                return False
            parsed = urllib.parse.urlparse(self.path)
            offered = urllib.parse.parse_qs(parsed.query).get("token", [""])[0]
            if not offered or not hmac.compare_digest(offered, token):
                return False
            self.send_response(302)
            self.send_header("Location", parsed.path or "/")
            self.send_header(
                "Set-Cookie",
                f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return True

        def _deny(self) -> None:
            body = (b"FJOR Studio: a token is required.\n"
                    b"Open the dashboard with ?token=... once, or send it as "
                    b"X-Studio-Token.\n")
            self.send_response(401)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        # -- helpers ---------------------------------------------------------
        def _json(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self) -> Dict[str, Any]:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

        # -- GET -------------------------------------------------------------
        def do_GET(self) -> None:  # noqa: N802
            if not self._authorised():
                if self._claim_from_query():
                    return
                return self._deny()
            parsed = urllib.parse.urlparse(self.path)
            path = posixpath.normpath(urllib.parse.unquote(parsed.path))
            try:
                if path == "/":
                    body = PAGE.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/api/state":
                    return self._json(studio.overview())
                m = re.match(r"^/api/jobs/([A-Za-z0-9]+)$", path)
                if m:
                    return self._json(studio.detail(m.group(1)))
                if path == "/api/dubs":
                    return self._json({"dubs": studio.dubs()})
                if path == "/api/library":
                    return self._json(studio.library_items())
                m = re.match(r"^/media/([A-Za-z0-9]+)/(.+)$", path)
                if m:
                    return self._serve_media(m.group(1), m.group(2))
                m = re.match(r"^/library/([a-z0-9_-]+)$", path)
                if m:
                    return self._serve_ranged(studio.library_path(m.group(1)))
                m = re.match(r"^/music/(.+)$", path)
                if m:
                    return self._serve_ranged(studio.music_path(m.group(1)))
                m = re.match(r"^/dubmedia/([A-Za-z0-9]+)/(.+)$", path)
                if m:
                    return self._serve_file(
                        studio.dub_media(m.group(1), m.group(2)))
                self._json({"error": "not found"}, 404)
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, 404)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

        def _serve_file(self, path: Path) -> None:
            """A still or a finished dub. No ranges: a PNG does not need them,
            and a dubbed cut is downloaded rather than scrubbed."""
            body = path.read_bytes()
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _serve_media(self, job_id: str, rel: str) -> None:
            return self._serve_ranged(studio.media_path(job_id, rel))

        def _serve_ranged(self, path: Path) -> None:
            """Serves byte ranges, which is not optional for video -- or for a
            bed the producer scrubs through to hear the chorus.

            A response that declares `Accept-Ranges: none` is one Chrome will
            not seek, even after it has buffered the whole file -- the draft
            player could be watched start to finish and nothing else, which is
            useless at a gate whose job is reviewing the cut. Streamed in
            chunks too, so a 30 MB final is not read into memory to be sent."""
            size = path.stat().st_size
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            rng = parse_range(self.headers.get("Range"), size)

            if rng is INVALID_RANGE:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            if rng is None:
                start, end, status = 0, size - 1, 200
            else:
                start, end, status = rng[0], rng[1], 206
            length = end - start + 1

            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(length))
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            if self.command == "HEAD":
                return
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(CHUNK, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)

        def do_HEAD(self) -> None:  # noqa: N802
            if not self._authorised():
                if self._claim_from_query():
                    return
                return self._deny()
            """Media only. Delegating every route to do_GET would answer HEAD
            on the JSON endpoints with a body, which is a protocol violation --
            and the only client that sends HEAD here is a video element asking
            how big a file is."""
            path = posixpath.normpath(
                urllib.parse.unquote(urllib.parse.urlparse(self.path).path))
            if re.match(r"^/media/[A-Za-z0-9]+/.+$", path) \
                    or re.match(r"^/library/[a-z0-9_-]+$", path) \
                    or re.match(r"^/music/.+$", path):
                return self.do_GET()
            self.send_response(405)
            self.send_header("Allow", "GET, POST")
            self.send_header("Content-Length", "0")
            self.end_headers()

        # -- POST ------------------------------------------------------------
        def do_POST(self) -> None:  # noqa: N802
            if not self._authorised():
                if self._claim_from_query():
                    return
                return self._deny()
            parsed = urllib.parse.urlparse(self.path)
            path = posixpath.normpath(urllib.parse.unquote(parsed.path))
            try:
                payload = {} if path == "/api/uploads" else self._read_json()
                if path == "/api/delivery":
                    return self._json(studio.set_delivery(
                        payload.get("root", ""), payload.get("week_folder", "")))
                if path == "/api/kit":
                    # The body is already parsed above. Straight into memory
                    # from there: it is never written to disk, and the response
                    # says only which providers arrived, never a value.
                    return self._json(
                        {"providers": kit_mod.use(kit_mod.parse(payload))})
                if path == "/api/dub/preview":
                    return self._json(studio.dub_preview(payload))
                if path == "/api/dub":
                    return self._json(studio.dub_start(payload))
                if path == "/api/uploads":
                    return self._json(studio.receive_upload(
                        self.headers.get("X-Filename", ""), self.rfile,
                        int(self.headers.get("Content-Length") or 0)))
                if path == "/api/verticals":
                    return self._json(studio.add_vertical(payload))
                if path == "/api/library":
                    return self._json(studio.library_add(payload))
                m = re.match(r"^/api/library/([a-z0-9_-]+)/delete$", path)
                if m:
                    return self._json(studio.library_remove(m.group(1)))
                m = re.match(r"^/api/jobs/([A-Za-z0-9]+)/keep$", path)
                if m:
                    return self._json(studio.keep_clip(m.group(1), payload))
                if path == "/api/jobs":
                    job_id = studio.create(payload)
                    if payload.get("run"):
                        studio.worker.submit(job_id, "run")
                    return self._json({"id": job_id})
                m = re.match(r"^/api/jobs/([A-Za-z0-9]+)/derive$", path)
                if m:
                    new_id = studio.derive(m.group(1), payload)
                    if payload.get("run"):
                        studio.worker.submit(new_id, "run")
                    return self._json({"id": new_id})
                m = re.match(r"^/api/jobs/([A-Za-z0-9]+)/delete$", path)
                if m:
                    return self._json(studio.delete_job(m.group(1)))
                m = re.match(r"^/api/jobs/([A-Za-z0-9]+)/([a-z]+)$", path)
                if m:
                    job_id, action = m.group(1), m.group(2)
                    if action not in ("run", "approve", "revise", "retry",
                                      "reassemble", "cancel", "edit", "driver",
                                      "waive", "prompt", "reopen"):
                        return self._json({"error": f"unknown action {action}"}, 400)
                    studio.worker.submit(job_id, action, payload)
                    return self._json({"queued": action, "id": job_id})
                self._json({"error": "not found"}, 404)
            except UnknownVertical as exc:
                self._json({"error": str(exc)}, 400)
            except FileNotFoundError as exc:
                self._json({"error": str(exc)}, 404)
            except (TransitionError, DeriveError, KitError, GenError,
                    LibraryError, ValueError, KeyError) as exc:
                # a refusal is the answer, not a crash: the page shows it, and
                # "Internal Server Error" would tell the producer nothing
                self._json({"error": f"{type(exc).__name__}: {exc}"}, 400)
            except Exception as exc:  # noqa: BLE001
                self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    return Handler


def serve(home: Optional[Path] = None, host: str = "127.0.0.1",
          port: int = 8422, token: Optional[str] = None) -> None:
    # The token is resolved from config FIRST, before any backend is built. A
    # deployment that has not filled in auth.yaml yet must still be told it is
    # about to publish a spend button -- not handed a missing-key error from a
    # provider it has not reached.
    from ..config import load as _load_config
    token = resolve_token(_load_config(home), token)
    if not is_loopback(host) and not token:
        # Refusing is the whole point. Binding wider than loopback publishes an
        # approve button that spends real credits, and a producer's unreleased
        # work, to everything that can reach the port.
        raise SystemExit(
            f"refusing to serve on {host} with no token.\n"
            f"Set FJOR_STUDIO_TOKEN (or dashboard.token in config/auth.yaml) to "
            f"a long random string, or leave the host at 127.0.0.1.\n"
            f"The dashboard has no other authentication: every gate it shows "
            f"can be approved, and approving one spends credits.")
    studio = Studio(home)
    server = ThreadingHTTPServer((host, port), make_handler(studio, token))
    print(f"FJOR Studio dashboard  ->  http://{host}:{port}"
          + (f"/?token={token}" if token else ""))
    print("(localhost only; ctrl-c to stop)" if is_loopback(host)
          else "(token required; put TLS in front of it; ctrl-c to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.server_close()
