"""fjor-studio command line. Thin: it only calls Engine.run/approve/revise/
retry/cancel and prints."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import config as config_mod
from .app import new_job, open_studio
from .engine import JobStore
from .config import UnknownVertical
from .engine import GATES, TERMINAL


def _fmt_money(n: float) -> str:
    return f"{n:,.1f} cr"


def _print_job(job, verbose: bool = False) -> None:
    print(f"{job.id}  {job.state}"
          + ("  [gate ready]" if job.gate_ready else "")
          + f"  spent {_fmt_money(job.spent)}")
    if job.error:
        print(f"  error: {job.error}")
    if job.meta.get("week_dir"):
        print(f"  delivered to: {job.meta['week_dir']}")
    if job.state in GATES:
        key = {"GATE_PLAN": "plates", "GATE_PLATES": "clips"}.get(job.state)
        f = job.forecasts.get(key) if key else None
        if f:
            note = "" if f.get("complete") else \
                f"  (INCOMPLETE -- unpriced: {', '.join(f.get('unpriced') or [])})"
            print(f"  next stage forecast: {_fmt_money(f['total'])}{note}")
    if verbose:
        for s in job.scenes:
            print(f"  scene {s['idx']}: plate={s['plate'] or '-'} "
                  f"clip={s['clip'] or '-'} "
                  f"plateQA={(s.get('plate_qa') or {}).get('severity', '-')} "
                  f"clipQA={(s.get('clip_qa') or {}).get('severity', '-')}")
        for ev in job.events[-12:]:
            print(f"  {ev['ts']}  {ev['type']:<20} {ev['msg']}")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="fjor-studio")
    p.add_argument("--home", type=Path, default=None,
                   help="studio root (default: $FJOR_STUDIO_HOME or cwd)")
    sub = p.add_subparsers(dest="cmd", required=True)

    n = sub.add_parser("new", help="create a job")
    n.add_argument("vertical", nargs="?", default=None,
                   help="a key from verticals.yaml; omit when using --name")
    n.add_argument("reference", help="path to the reference video")
    n.add_argument("--name", default=None,
                   help="the whole creative name -- carries id, week, concept "
                        "and producer, and its prefix picks the vertical")
    n.add_argument("--brief", default="",
                   help="what the pipeline should know about this one")
    n.add_argument("--week", type=int, default=None,
                   help="delivery week number -- the '34' in '34 week'")
    n.add_argument("--concept", default=None,
                   help="concept token, the c- part: ugc, podcast, morph, …")
    n.add_argument("--producer", default=None,
                   help="producer initials, the pr- part (default from delivery.yaml)")
    n.add_argument("--packshot", default=None,
                   help="product shot from assets/packshots (stem before _916)")
    n.add_argument("--demo", default=None, help="clip from assets/demos")
    n.add_argument("--music", default=None, help="bed from assets/music bed")
    n.add_argument("--crossfade-s", type=float, default=None,
                   help="dissolve between shots, seconds (0 = hard cuts)")
    n.add_argument("--demo-trim-s", type=float, default=None)
    n.add_argument("--id", default=None)
    n.add_argument("--scenes", type=int, default=None,
                   help="omit and the reference's own shot list decides")
    n.add_argument("--run", action="store_true", help="run it straight away")

    for name, helptext in (("run", "advance a job to the next gate"),
                           ("status", "show a job"),
                           ("retry", "resume a failed job"),
                           ("reassemble", "re-cut from the existing clips")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("job_id")

    a = sub.add_parser("approve", help="pass a gate")
    a.add_argument("job_id")
    a.add_argument("--note", default="")

    r = sub.add_parser("revise", help="send a stage back")
    r.add_argument("job_id")
    r.add_argument("what")
    r.add_argument("--note", default="")
    r.add_argument("--scene", type=int, action="append", dest="scenes")

    dv = sub.add_parser("derive", help="make a variation of a finished job")
    dv.add_argument("job_id")
    dv.add_argument("name", help="the new creative name")
    dv.add_argument("--recast", action="store_true",
                    help="a new face for the variation: the cast descriptions "
                         "come across, the portraits do not")
    dv.add_argument("--from", dest="from_stage", default="assembly",
                    choices=["assembly", "clips", "plates", "prompts"],
                    help="everything earlier than this is inherited")
    dv.add_argument("--note", default="", help="what is different about this one")
    dv.add_argument("--packshot", default=None)
    dv.add_argument("--music", default=None)
    dv.add_argument("--crossfade-s", type=float, default=None)
    dv.add_argument("--run", action="store_true")

    c = sub.add_parser("cancel", help="stop a job")
    c.add_argument("job_id")
    c.add_argument("--note", default="")

    sub.add_parser("list", help="list jobs")
    sub.add_parser("assets", help="what is in the asset library")
    d = sub.add_parser("dashboard", help="open the producer dashboard")
    d.add_argument("--port", type=int, default=8422)
    d.add_argument("--host", default="127.0.0.1",
                   help="anything but 127.0.0.1 requires FJOR_STUDIO_TOKEN")
    d.add_argument("--token", default=None,
                   help="shared token (default: $FJOR_STUDIO_TOKEN, "
                        "then dashboard.token in auth.yaml)")
    sub.add_parser("config", help="show the resolved config (keys redacted)")

    args = p.parse_args(argv)

    # `open_studio` constructs the backends, which is where a missing key is
    # caught -- deliberately, so routing into a gap fails before a stage is paid
    # for rather than in the middle of one (BLUEPRINT 5). But these commands are
    # what a person runs while SETTING UP, before any key exists, and `config`
    # is the one that shows them what is still missing. Refusing to print the
    # configuration until the configuration is complete is a circle.
    if args.cmd in ("config", "assets", "list", "dashboard"):
        cfg = config_mod.load(args.home)
        store = JobStore(cfg.jobs_dir)
        engine = None
    else:
        cfg, store, engine = open_studio(args.home)

    if args.cmd == "dashboard":
        from .dashboard import serve
        serve(cfg.home, args.host, args.port, args.token)
        return 0

    if args.cmd == "config":
        print(json.dumps(cfg.redacted(), indent=2, ensure_ascii=False))
        return 0

    if args.cmd == "assets":
        from .assemble import list_packshots
        a = cfg.assets_dir
        print(f"assets: {a}")
        print("  packshots:", ", ".join(list_packshots(a)) or "none")
        from .assemble import list_music
        print("  music beds:", ", ".join(list_music(a)) or "none")
        for sub_dir in ("demos", "disclaimers", "fonts"):
            files = sorted(p.name for p in (a / sub_dir).glob("*")
                           if p.is_file() and not p.name.startswith("."))
            print(f"  {sub_dir}:", ", ".join(files) or "none")
        return 0

    if args.cmd == "list":
        jobs = store.load_all()
        if not jobs:
            print("no jobs")
        for j in jobs:
            _print_job(j)
        return 0

    if args.cmd == "new":
        vertical, job_id = args.vertical, args.id
        week, concept, producer = args.week, args.concept, args.producer
        if args.name:
            from .naming import parse_name
            from .ids import parse as parse_id
            try:
                parsed = parse_name(args.name)
            except ValueError as exc:
                print(str(exc))
                return 2
            job_id = job_id or parsed["id"]
            week, concept = parsed["week"], parsed["concept"]
            producer = producer or parsed["producer"]
            vertical = vertical or cfg.vertical_for_prefix(parse_id(parsed["id"])[0])
        missing = [n for n, v in (("vertical", vertical), ("week", week),
                                  ("concept", concept)) if v in (None, "")]
        if missing:
            print(f"missing {', '.join(missing)} — pass --name with the whole "
                  f"creative name, or give them individually")
            return 2
        intake = {"reference": str(args.reference), "week": week,
                  "concept": concept, "producer": producer,
                  "brief": args.brief,
                  "packshot": args.packshot, "demo": args.demo,
                  "demo_trim_s": args.demo_trim_s}
        if args.scenes is not None:
            intake["scene_count"] = args.scenes
        if args.music:
            intake["music"] = args.music
        if args.crossfade_s is not None:
            intake["crossfade_s"] = args.crossfade_s
        try:
            job = new_job(store, cfg, vertical, intake, job_id=job_id)
        except UnknownVertical as exc:
            print(str(exc))
            return 2
        print(f"created {job.id} -> {cfg.week_dir(vertical, week)}")
        if args.run:
            job = engine.run(job)
        _print_job(job, verbose=True)
        return 1 if job.state == "failed" else 0

    if args.cmd == "derive":
        from .derive import DeriveError, derive as do_derive
        from .naming import parse_name
        try:
            parsed = parse_name(args.name)
        except ValueError as exc:
            print(str(exc))
            return 2
        overrides = {"week": parsed["week"], "concept": parsed["concept"],
                     "producer": parsed["producer"],
                     "creative_name": args.name.strip()}
        for key, val in (("packshot", args.packshot), ("music", args.music)):
            if val is not None:
                overrides[key] = val
        if args.crossfade_s is not None:
            overrides["crossfade_s"] = args.crossfade_s
        try:
            job = do_derive(store, args.job_id, parsed["id"], args.from_stage,
                            overrides, args.note, recast=args.recast)
        except DeriveError as exc:
            print(str(exc))
            return 2
        print(f"derived {job.id} from {args.job_id} at '{args.from_stage}'")
        if args.run:
            job = engine.run(job)
        _print_job(job, verbose=True)
        return 1 if job.state == "failed" else 0

    job = store.load(args.job_id)
    if args.cmd == "run":
        job = engine.run(job)
    elif args.cmd == "approve":
        job = engine.approve(job, args.note)
    elif args.cmd == "revise":
        job = engine.revise(job, args.what, args.note, args.scenes)
    elif args.cmd == "retry":
        job = engine.retry(job)
    elif args.cmd == "reassemble":
        job = engine.reassemble(job)
    elif args.cmd == "cancel":
        job = engine.cancel(job, args.note)
    _print_job(job, verbose=args.cmd in ("status", "run"))
    return 1 if job.state == "failed" else 0


def cli(argv=None) -> int:
    """`main` with the expected failures turned into a sentence.

    Every exception below is a person's configuration being wrong, which on a
    new deployment is most of them. A traceback reads as a broken program and
    sends someone to the source; the message alone says what to fix."""
    from .config import MissingDeliveryRoot, UnknownVertical
    from .gen.base import GenError
    from .engine.engine import TransitionError
    try:
        return main(argv)
    except (MissingDeliveryRoot, UnknownVertical, GenError, TransitionError,
            FileNotFoundError) as exc:
        print(f"fjor-studio: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(cli())
