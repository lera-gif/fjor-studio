"""The clip library: <assets>/library/.

Two kinds of thing live here, and the cut treats them the same way:

- a producer's OWN clip, uploaded once -- a hook that has already performed,
  a product placement showing the app or the table -- and reused across jobs;
- a GENERATION kept from a job, so a shot that came out right is not lost
  when its job is finished and can open or close another creative.

An item is `<id>.<ext>` plus `<id>.json` beside it: the name the producer gave
it, where it came from, and the prompts that made it when it was generated.
Nothing here is ever hard-deleted -- removing an item moves it under
`_to_delete/`, the same rule as the bed library and delivery.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

LIBRARY_DIR = "library"
TRASH = "_to_delete"
CLIP_EXT = (".mp4", ".mov", ".m4v", ".webm")
_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}$")


class LibraryError(Exception):
    pass


def _root(assets_dir: Path) -> Path:
    return Path(assets_dir) / LIBRARY_DIR


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(name or "").lower()).strip("-")
    return s[:40] or "clip"


def valid_id(item_id: str) -> bool:
    return bool(_ID.match(str(item_id or "")))


def list_items(assets_dir: Path) -> List[Dict[str, Any]]:
    """Every item, newest first. An item whose media has gone missing is
    reported with `missing: True` rather than dropped -- a cut that names it
    must be able to say why it cannot be made."""
    root = _root(assets_dir)
    if not root.is_dir():
        return []
    out = []
    for meta_path in root.glob("*.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        item_id = str(meta.get("id") or meta_path.stem)
        if not valid_id(item_id):
            continue
        media = root / str(meta.get("file") or "")
        meta["missing"] = not media.is_file()
        out.append(meta)

    # A clip DROPPED INTO THE FOLDER by hand is adopted on sight, the way the
    # bed library and the packshots are simply scanned. Requiring an upload
    # through the dashboard made the folder lie: the file was plainly there and
    # the picker said "none".
    claimed = {str(m.get("file") or "") for m in out}
    for media in root.iterdir():
        if (media.is_file() and media.suffix.lower() in CLIP_EXT
                and media.name not in claimed):
            adopted = _adopt(root, media)
            if adopted:
                out.append(adopted)

    out.sort(key=lambda m: str(m.get("added_at") or ""), reverse=True)
    return out


def _adopt(root: Path, media: Path) -> Optional[Dict[str, Any]]:
    """Give a hand-dropped clip a sidecar, keeping the name it was given.

    The id is derived from the FILENAME rather than randomly, so it is the same
    on every scan -- a job that stored `insert: <id>` still resolves after a
    restart. Renaming the file in Finder therefore makes a new item and the old
    id reads as missing, which is honest: it is a different clip as far as
    anything that referenced it can tell.

    The file itself is left where the producer put it, under the name they gave
    it. Renaming someone's file to suit our own scheme would lose the only
    handle they have on it."""
    item_id = (f"{_slug(media.stem)}-"
               f"{hashlib.md5(media.name.encode('utf-8')).hexdigest()[:6]}")
    if not valid_id(item_id):
        return None
    meta: Dict[str, Any] = {
        "id": item_id,
        "name": media.stem,
        "file": media.name,
        "kind": "dropped",
    }
    try:
        meta["added_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                         time.gmtime(media.stat().st_mtime))
    except OSError:
        meta["added_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        from .assemble import duration_of, has_audio
        meta["duration_s"] = round(duration_of(media), 2)
        meta["has_audio"] = bool(has_audio(media))
    except Exception:  # noqa: BLE001 -- a probe failure is not a lost clip
        pass
    try:
        (root / f"{item_id}.json").write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass            # a read-only assets dir still lists; it just re-probes
    meta["missing"] = False
    return meta


def get(assets_dir: Path, item_id: str) -> Optional[Dict[str, Any]]:
    if not valid_id(item_id):
        return None
    meta_path = _root(assets_dir) / f"{item_id}.json"
    if not meta_path.is_file():
        # a hand-dropped clip on a read-only assets dir has no sidecar to read,
        # but it is still a real item -- find it the way the listing does
        return next((m for m in list_items(assets_dir)
                     if m.get("id") == item_id), None)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    meta["missing"] = not (_root(assets_dir) / str(meta.get("file") or "")).is_file()
    return meta


def item_path(assets_dir: Path, item_id: str) -> Optional[Path]:
    """The media behind an id, or None when the id is unknown or its file is
    gone. Only ever a file directly under the library: the id is validated and
    the filename comes from the sidecar we wrote, never from the request."""
    meta = get(assets_dir, item_id)
    if not meta or meta.get("missing"):
        return None
    return _root(assets_dir) / str(meta["file"])


def _write(assets_dir: Path, src: Path, name: str, extra: Dict[str, Any],
           move: bool) -> Dict[str, Any]:
    src = Path(src)
    if src.suffix.lower() not in CLIP_EXT:
        raise LibraryError(
            f"'{src.name}' is not a clip ({', '.join(CLIP_EXT)})")
    if not src.is_file():
        raise LibraryError(f"no such file: {src}")
    root = _root(assets_dir)
    root.mkdir(parents=True, exist_ok=True)
    item_id = f"{_slug(name)}-{uuid.uuid4().hex[:6]}"
    dest = root / f"{item_id}{src.suffix.lower()}"
    (shutil.move if move else shutil.copy2)(str(src), str(dest))
    meta: Dict[str, Any] = {
        "id": item_id,
        "name": str(name or "").strip() or src.stem,
        "file": dest.name,
        "added_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    try:
        from .assemble import duration_of, has_audio
        meta["duration_s"] = round(duration_of(dest), 2)
        meta["has_audio"] = bool(has_audio(dest))
    except Exception:  # noqa: BLE001 -- a probe failure is not a lost clip
        pass
    meta.update(extra)
    (root / f"{item_id}.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    meta["missing"] = False
    return meta


def add_upload(assets_dir: Path, src: Path, name: str) -> Dict[str, Any]:
    """A producer's own clip. The upload is MOVED in: it was staged for this."""
    return _write(assets_dir, src, name, {"kind": "upload"}, move=True)


def keep_generation(assets_dir: Path, job, job_dir: Path, scene_idx: int,
                    name: str) -> Dict[str, Any]:
    """Copy one generated shot out of its job, with the prompts that made it.
    The job keeps its own copy: the library is for reuse, not for moving."""
    scene = next((s for s in job.scenes if int(s.get("idx", -1)) == int(scene_idx)),
                 None)
    if scene is None:
        raise LibraryError(f"{job.id} has no scene {scene_idx}")
    if not scene.get("clip"):
        raise LibraryError(f"{job.id} scene {scene_idx} has no clip to keep")
    src = Path(job_dir) / scene["clip"]
    if not src.is_file():
        raise LibraryError(f"{job.id} scene {scene_idx}: clip file is missing")
    return _write(assets_dir, src, name or f"{job.id} scene {scene_idx}", {
        "kind": "generated",
        "from_job": job.id,
        "scene": int(scene_idx),
        "vertical": str(job.intake.get("vertical") or ""),
        "image_prompt": str(scene.get("image_prompt") or ""),
        "video_prompt": str(scene.get("video_prompt") or ""),
        "line": str(scene.get("line") or ""),
    }, move=False)


def remove(assets_dir: Path, item_id: str) -> Dict[str, Any]:
    """Out of the library, not off the disk: both files go under _to_delete/."""
    meta = get(assets_dir, item_id)
    if not meta:
        raise LibraryError(f"no library item '{item_id}'")
    root = _root(assets_dir)
    trash = root / TRASH
    trash.mkdir(parents=True, exist_ok=True)
    stamp = int(time.time())
    for name in (meta.get("file"), f"{item_id}.json"):
        p = root / str(name)
        if p.is_file():
            shutil.move(str(p), str(trash / f"{stamp}_{p.name}"))
    return {"removed": item_id, "to": str(trash)}
