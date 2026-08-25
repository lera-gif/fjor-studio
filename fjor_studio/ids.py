"""Creative ids: a vertical's prefix plus a zero-padded counter -- MENY069,
PIL901, LIPIL021, Y004.

Prefixes come from verticals.yaml, never from the vertical's name: `yoga` is
`Y` and `yoga_men` is `YM`, which no derivation rule would produce.

Allocation looks at BOTH the local jobs directory and the ids already shipped
into the delivery week folders. Those folders hold work from more than one tool,
and an id reused across them puts two different creatives under one name in the
ad platform -- which is not recoverable by renaming a file afterwards.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from .naming import id_of

_ID_RE = re.compile(r"^([A-Z]{1,6})(\d{3,4})$")


def parse(job_id: str) -> Tuple[str, int]:
    m = _ID_RE.match(job_id or "")
    if not m:
        raise ValueError(f"'{job_id}' is not a creative id")
    return m.group(1), int(m.group(2))


def delivered_ids(root: Optional[Path]) -> Set[str]:
    """Every creative id already present in the delivery tree.

    Reads the token filenames rather than the folder listing, so it sees ids
    shipped by any tool that follows the convention. A missing or unreadable
    root yields an empty set -- allocation must not break because a network
    volume is offline, and the local jobs directory still guards against the
    common case."""
    if not root:
        return set()
    root = Path(root)
    if not root.is_dir():
        return set()
    found: Set[str] = set()
    try:
        for path in root.glob("*/* week/*"):
            jid = id_of(path.name)
            if jid:
                found.add(jid)
            elif path.name.endswith("_manifest.json"):
                found.add(path.name[:-len("_manifest.json")])
    except OSError:
        return found
    return found


def next_id(prefix: str, taken: Iterable[str], width: int = 3) -> str:
    """`taken` is every id already in use, from every source."""
    prefix = str(prefix).strip().upper()
    if not prefix or not prefix.isalpha():
        raise ValueError(f"'{prefix}' is not a usable id prefix")
    highest = 0
    for jid in taken:
        try:
            t, n = parse(jid)
        except ValueError:
            continue
        if t == prefix:
            highest = max(highest, n)
    n = highest + 1
    return f"{prefix}{n:0{max(width, len(str(n)))}d}"
