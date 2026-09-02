"""Final filenames.

    n-{id}_ch-{channel}_t-{type}_c-{concept}_pr-{producer}_ds-{source}_w-{week}_s-{W}x{H}.{ext}
    n-MENY069_ch-fb_t-video_c-canu_pr-lp_ds-nano_w-34_s-1080x1920.mp4

This is not our convention to design. Files in this shape already sit in every
week folder, and the manifests, the ad platform and every past creative read
them. `parse()` exists so we can recognise ids that have already shipped.

Two token meanings are easy to get wrong:
- `pr-` is the PRODUCER'S INITIALS, not the funnel. The vendored naming.md says
  funnel; the owner corrected it on 2026-08-03.
- `ds-nano` means "AI-generated", whatever model made it -- the client calls all
  of it nano.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

TEMPLATE = ("n-{id}_ch-{channel}_t-{type}_c-{concept}_pr-{producer}"
            "_ds-{source}_w-{week}{lang}_s-{w}x{h}.{ext}")

# The language token, present ONLY on a dubbed cut. A creative in its original
# language keeps the name it has always had, byte for byte -- hundreds of files
# already carry it and a spreadsheet somewhere reads them. `_l-es` sits between
# the week and the size, so the size stays where every reader expects it: last.
LANG_TOKEN = "_l-{lang}"

EXAMPLE = "n-LIPIL025_ch-fb_t-video_c-test_pr-lp_ds-nano_w-34_s-1080x1350"

FINAL_RE = re.compile(
    r"^n-(?P<id>[A-Za-z0-9]+)"
    r"_ch-(?P<channel>[a-z0-9]+)"
    r"_t-(?P<type>[a-z0-9]+)"
    r"_c-(?P<concept>[a-z0-9-]+)"
    r"_pr-(?P<producer>[a-z0-9-]+)"
    r"_ds-(?P<source>[a-z0-9-]+)"
    r"_w-(?P<week>\d+)"
    r"(?:_l-(?P<lang>[a-z]{2,3}))?"          # dubbed cuts only; absent = original
    r"_s-(?P<w>\d+)x(?P<h>\d+)"
    r"\.(?P<ext>[a-z0-9]+)$")

_SLUG_OK = re.compile(r"[^a-z0-9-]+")


def slug(value: str) -> str:
    """Concept and producer tokens are lowercase, digits and hyphens only --
    an underscore or a space would break the token split on read."""
    out = _SLUG_OK.sub("-", str(value or "").strip().lower()).strip("-")
    return re.sub(r"-{2,}", "-", out)


def build(job_id: str, concept: str, week, width: int, height: int,
          producer: str = "lp", channel: str = "fb", type_: str = "video",
          source: str = "nano", ext: str = "mp4",
          lang: str = "") -> str:
    concept_s, producer_s = slug(concept), slug(producer)
    if not concept_s:
        raise ValueError("a final needs a concept token (the `c-` part)")
    if not producer_s:
        raise ValueError("a final needs a producer token (the `pr-` initials)")
    try:
        week_n = int(week)
    except (TypeError, ValueError):
        raise ValueError(f"week must be a number, got {week!r}")
    lang_s = slug(lang)
    if lang_s and not re.fullmatch(r"[a-z]{2,3}", lang_s):
        raise ValueError(
            f"'{lang}' is not a language code -- the token is two or three "
            f"letters, as in `_l-es`")
    name = TEMPLATE.format(id=job_id, channel=slug(channel), type=slug(type_),
                           concept=concept_s, producer=producer_s,
                           source=slug(source), week=week_n,
                           lang=LANG_TOKEN.format(lang=lang_s) if lang_s else "",
                           w=int(width), h=int(height), ext=ext)
    # build then verify: a token that would not read back is a bug here, not a
    # surprise three weeks later when someone greps the week folder
    if not FINAL_RE.match(name):
        raise ValueError(f"built a filename that does not parse: {name}")
    return name


def parse(filename: str) -> Optional[Dict[str, Any]]:
    m = FINAL_RE.match(str(filename))
    return m.groupdict() if m else None


def parse_name(text: str) -> Dict[str, Any]:
    """Read a creative name a producer pasted in.

    Deliberately more forgiving than `parse`: the extension is optional (nobody
    types `.mp4` when copying a name out of a sheet), surrounding whitespace and
    quotes are ignored, and the size token is accepted but not acted on -- both
    delivery sizes are built from `delivery.formats`, so the `s-` in the pasted
    name says which one they happened to copy, not what to produce.

    Raises ValueError with the expected shape, because this is the one field a
    producer types by hand."""
    raw = str(text or "").strip().strip('"\'').strip()
    if not raw:
        raise ValueError("paste the creative name, e.g. " + EXAMPLE)
    stem = raw
    for suffix in (".mp4", ".mov", ".m4v", ".webm"):
        if stem.lower().endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    m = FINAL_RE.match(stem + ".mp4")
    if not m:
        raise ValueError(
            f"'{raw}' is not a creative name. Expected {EXAMPLE} "
            f"(the .mp4 is optional).")
    d = m.groupdict()
    return {
        "id": d["id"].upper(),
        "concept": d["concept"],
        "producer": d["producer"],
        "week": int(d["week"]),
        "channel": d["channel"],
        "type": d["type"],
        "source": d["source"],
        # recorded so a mismatch is visible, never used to choose formats
        "pasted_size": [int(d["w"]), int(d["h"])],
    }


def id_of(filename: str) -> Optional[str]:
    parsed = parse(filename)
    return parsed["id"] if parsed else None
