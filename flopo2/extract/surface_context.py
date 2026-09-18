"""Surface/side-restriction guard for laminar bearers.

``limbe …, glabre en dessus, pubescent en dessous`` states the pilosity of one *surface* of the
lamina.  Asserting ``lamina glabrous`` (or ``pubescent``) for the whole organ contradicts the
other surface, so recovery and re-admission passes keep such values unresolved unless a surface
bearer can carry them.

The guard looks only at the value's own comma member (bounded by ``, ; : .`` and brackets), so a
restriction on a neighbouring value does not block an unrestricted one.  ``on both surfaces`` /
``sur les deux faces`` is also treated as a restriction (conservative: surface-level statement).
"""

from __future__ import annotations

import re

SURFACE_RESTRICTION = re.compile(
    r"(?<![\w-])(?:"
    r"en\s+dessus|en\s+dessous|dessus|dessous|au[- ]dessus|au[- ]dessous|"
    r"faces?\s+(?:sup[ée]rieures?|inf[ée]rieures?|adaxiales?|abaxiales?|interne|externe)|"
    r"(?:sur\s+)?(?:les\s+)?(?:deux|2)\s+faces|"
    r"above|beneath|below|underneath|"
    r"(?:upper|lower|under|adaxial|abaxial|dorsal|ventral|both|either)\s+(?:sides?|surfaces?|faces?)|"
    r"on\s+both\s+(?:sides|surfaces|faces)|adaxial(?:ly)?|abaxial(?:ly)?|"
    r"(?:la|l['’])\s*(?:sup[ée]rieure|inf[ée]rieure)"
    r")(?![\w-])",
    re.IGNORECASE,
)
_MEMBER_LEFT = re.compile(r"[,;:.()\[\]](?!\d)")
_MEMBER_RIGHT = re.compile(r"[,;:()\[\]]|\.(?!\d)")

# Pilosity, colour and texture/surface-sculpture values are surface properties; shape and size are not.
SURFACE_ATTRIBUTE_ROOTS = frozenset({"PATO_0000066", "PATO_0000014", "PATO_0000150"})


def value_member(text: str, start: int, end: int) -> tuple[int, int]:
    """Return the comma member ``[left, right)`` containing ``text[start:end]``."""

    left = 0
    for match in _MEMBER_LEFT.finditer(text, 0, max(0, start)):
        if not (match.group() == "." and match.start() > 0 and text[match.start() - 1].isdigit()):
            left = match.end()
    right_match = _MEMBER_RIGHT.search(text, max(end, start))
    right = right_match.start() if right_match else len(text)
    return left, right


def surface_restriction(text: str, start: int, end: int) -> str:
    """Return the surface-restriction cue in the value's own comma member, else ``""``."""

    left, right = value_member(text, start, end)
    match = SURFACE_RESTRICTION.search(text, left, right)
    return match.group(0) if match else ""


_UPPER = re.compile(
    r"(?<![\w-])(?:en\s+dessus|dessus|au[- ]dessus|above|upper\s+(?:side|surface|face)s?|"
    r"faces?\s+sup[ée]rieures?|adaxial(?:ly)?|(?:la|l['’])\s*sup[ée]rieure)(?![\w-])",
    re.IGNORECASE,
)
_LOWER = re.compile(
    r"(?<![\w-])(?:en\s+dessous|dessous|au[- ]dessous|beneath|below|underneath|"
    r"(?:lower|under)\s+(?:side|surface|face)s?|faces?\s+inf[ée]rieures?|abaxial(?:ly)?|"
    r"(?:la|l['’])\s*inf[ée]rieure)(?![\w-])",
    re.IGNORECASE,
)
_BOTH = re.compile(
    r"(?<![\w-])(?:(?:deux|2)\s+faces|both\s+(?:sides|surfaces|faces)|either\s+(?:side|surface))(?![\w-])",
    re.IGNORECASE,
)

# Whole-organ laminar bearers whose surface-level values must not be asserted for the organ.
LAMINAR_BEARERS = frozenset(
    {
        "PO_0009025",  # leaf
        "PO_0025034",  # leaf (generic)
        "PO_0020039",  # leaf lamina
        "PO_0025060",  # lamina
        "PO_0020049",  # leaflet
        "PO_0009032",  # petal
        "PO_0009031",  # sepal
        "PO_0009033",  # tepal
        "PO_0009055",  # bract
        "PO_0009045",  # involucral bract
        "PO_0020041",  # stipule
        "PO_0006001",  # phyllome
        "FLOPO_0986002",  # leaflet lamina
    }
)
SURFACE_FAMILIES = frozenset({"colour", "pilosity", "texture"})


def single_side_restriction(text: str, start: int, end: int) -> str:
    """Return ``"upper"``/``"lower"`` when the value's member restricts it to one surface.

    ``glabre en dessus`` is upper; ``pubescent above and beneath`` or ``glabre sur les deux
    faces`` hold for the whole organ and return ``""``.
    """

    left, right = value_member(text, start, end)
    member = text[left:right]
    if _BOTH.search(member):
        return ""
    upper, lower = bool(_UPPER.search(member)), bool(_LOWER.search(member))
    if upper and not lower:
        return "upper"
    if lower and not upper:
        return "lower"
    if upper and lower:
        return ""
    return "other" if surface_restriction(text, start, end) else ""


def surface_guarded(po_id: str, family: str, text: str, start: int, end: int) -> bool:
    """True when a colour/pilosity/texture value on a whole laminar organ is one surface's."""

    return (
        po_id in LAMINAR_BEARERS
        and family in SURFACE_FAMILIES
        and bool(single_side_restriction(text, start, end))
    )
