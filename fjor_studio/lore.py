"""What a vertical IS, and what breaks it, in the prompt writer's hands.

Until now the pipeline knew a vertical's PREFIX and FOLDER and nothing else. The
knowledge that decides whether a creative is right for its niche -- the mechanic,
the words that must appear, the words that must not, the objections kept
verbatim, who may be on camera -- lived in documents beside the work and reached
a creative only if a producer retyped some of it into a brief.

It is ported, never invented (see config/lore.yaml). That distinction is the
whole value: a plausible invention here outranks both the reference and the
producer's note, and nobody downstream can tell the difference.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# The order the block is written in, and the label each field gets. Ordered so
# the writer meets the mechanic first and the safety note last -- the same shape
# the source templates use.
FIELDS: List[tuple] = [
    ("mechanic", "WHAT THIS NICHE IS"),
    ("names", "PRODUCT NAMES -- one per creative, in every scene, rotated between"),
    ("forbidden_names", "NAMES THAT BREAK IT"),
    ("power_words", "THE LANGUAGE THAT MAKES A VIEWER SAY 'THAT'S ME'"),
    ("forbidden_lexicon", "LANGUAGE THAT BREAKS IT"),
    ("anchors", "LINES TO KEEP VERBATIM"),
    ("objections", "OBJECTIONS -- and how they resolve"),
    ("hook_note", "THE HOOK"),
    ("cast_lock", "CASTING"),
    ("moves", "WHAT THE MOVEMENT IS"),
    ("locations", "LOCATIONS"),
    ("wardrobe", "WARDROBE"),
    ("prop_language", "PROPS"),
    ("palette", "PALETTE"),
    ("copy_tone", "TONE"),
    ("lipsync_swaps", "SPOKEN-LINE SUBSTITUTIONS"),
    ("content_safety", "SAFETY AND COMPLIANCE"),
]

# Not written into the writer's block: these are for the image and video prompts,
# and `negative_tokens` in particular is a list the writer must not paraphrase.
GEN_FIELDS = ("negative_tokens", "keep_out_of_negatives")


def for_vertical(cfg, vertical: str) -> Dict[str, Any]:
    """The lore for a vertical, or {} when it has none.

    A vertical with no entry is not an error: the registry is the authority on
    what exists, and lore is added as it is written."""
    entries = (getattr(cfg, "lore", None) or {}).get("lore") or {}
    return dict(entries.get(str(vertical or "").strip()) or {})


def _render(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return "\n".join(f"  - {v}" for v in value)
    return str(value).strip()


def writer_block(cfg, vertical: str) -> str:
    """The lore, as the prompt writer reads it. Empty when there is none."""
    entry = for_vertical(cfg, vertical)
    if not entry:
        return ""
    parts = [
        "",
        "=" * 70,
        f"NICHE LORE -- {vertical.replace('_', ' ').upper()}",
        "=" * 70,
        "",
        "This is what the niche IS. It outranks your own sense of the category "
        "and it is not a style suggestion: a creative that breaks it is wrong "
        "for the product even when it is a good ad. It does NOT outrank the "
        "reference's structure -- mirror the reference, and change only what "
        "breaks the niche.",
        "",
    ]
    for key, label in FIELDS:
        if entry.get(key):
            parts.append(f"{label}:")
            parts.append(_render(entry[key]))
            parts.append("")
    return "\n".join(parts)


def negatives(cfg, vertical: str) -> str:
    """Tokens every generated frame of this vertical must exclude."""
    return str(for_vertical(cfg, vertical).get("negative_tokens") or "").strip()


def protected_props(cfg, vertical: str) -> str:
    """Hero props that must NOT be negated -- a mat in back pain, walking shoes
    in apostolic. Adding them to the negatives removes the niche's own subject."""
    return str(for_vertical(cfg, vertical).get("keep_out_of_negatives") or "").strip()
