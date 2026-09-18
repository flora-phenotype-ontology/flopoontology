"""Positional scope, pinned BSPO fillers and indumentum parts (schema extension E3).

Design (curator approval 2026-09-18, PROPOSAL §4): *PO first, then pinned BSPO, never free text.*

* **Substituted bearer.** When PO has the positional part of the named organ (``leaf lamina
  abaxial epidermis`` for "leaves pubescent beneath"), ``po_id`` becomes that PO class and a
  ``bearer_scope`` record (``mode = substituted_bearer``) keeps the outer organ and the verbatim
  cue.  The scope record is provenance only and never enters the FAC signature.
* **Part restriction.** When the outer organ must stay the bearer or PO lacks the part (ovary
  apex), the part is a ``part_restrictions`` filler: a PO class or a pinned BSPO class
  (apical/basal region, margin).  ``bearer_scope.mode = part_restriction``.  The top-level
  quality is then the same value only when the part value entails it for the whole organ
  (hairs at the apex: the ovary is hairy); otherwise it is the value's PATO attribute
  (colour, pilosity), so the class claims nothing beyond the part.
* Leaflets have no PO epidermis class; a leaflet side is a portion of the compound leaf's
  adaxial/abaxial epidermis (PO:0006018/PO:0006019), used as a substituted bearer.
* **Indumentum.** Qualities of the hairs themselves (``stellate-pubescent``, ``white-hairy``)
  are a part restriction on PO:0000282 trichome; the collective covering is FLOPO_0986003
  indumentum.

``beneath/above`` map to abaxial/adaxial only for dorsiventral laminar organs listed in
:data:`SURFACE_SCOPE`; ``inside/outside`` map to adaxial/abaxial only for single perianth
members and bracts.  Everything else stays unresolved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

BSPO_TERMS_PATH = Path("ontology/imports/bspo_terms.txt")
PO_OBO_PATH = Path("ont/plant_ontology.obo")
TRICHOME = "PO_0000282"
INDUMENTUM = "FLOPO_0986003"
HAS_PART = "BFO_0000051"

# BSPO fillers used for regions PO does not provide for an organ.
BSPO_APICAL_REGION = "BSPO_0000073"
BSPO_BASAL_REGION = "BSPO_0000074"
BSPO_MARGIN = "BSPO_0000006"
BSPO_SURFACE = "BSPO_0000005"
BSPO_PROXIMAL_REGION = "BSPO_0000077"
BSPO_DISTAL_REGION = "BSPO_0000078"

# Reviewed position table: (outer bearer, side) -> (scope class, mode).  Every PO scope class is
# defined in PO as the epidermis covering that side of the organ (PO:0000049 "covers the
# abaxial/lower surface of a leaf lamina").  Leaflets have no PO epidermis class; a leaflet side is
# a portion of the compound leaf's adaxial/abaxial epidermis (PO:0006018/PO:0006019), which is
# used as the bearer while bearer_scope keeps the leaflet (PO NTR for leaflet epidermis pending).
_LAMINA_SIDES = {"adaxial": "PO_0000050", "abaxial": "PO_0000049"}
SURFACE_SCOPE: dict[str, dict[str, tuple[str, str]]] = {
    **{
        outer: {side: (scope, "substituted_bearer") for side, scope in _LAMINA_SIDES.items()}
        for outer in ("PO_0020039", "PO_0025034", "PO_0009025")  # leaf lamina, leaf, vascular leaf
    },
    **{
        outer: {
            "adaxial": ("PO_0006018", "substituted_bearer"),
            "abaxial": ("PO_0006019", "substituted_bearer"),
        }
        for outer in ("PO_0020049", "FLOPO_0986002")  # leaflet, leaflet lamina
    },
    "PO_0009031": {"adaxial": ("PO_0006055", "substituted_bearer"),
                   "abaxial": ("PO_0006054", "substituted_bearer")},  # sepal
    "PO_0009032": {"adaxial": ("PO_0006053", "substituted_bearer"),
                   "abaxial": ("PO_0006052", "substituted_bearer")},  # petal
    "PO_0009033": {"adaxial": ("PO_0025193", "substituted_bearer"),
                   "abaxial": ("PO_0025192", "substituted_bearer")},  # tepal
    "PO_0009055": {"adaxial": ("PO_0025160", "substituted_bearer"),
                   "abaxial": ("PO_0025159", "substituted_bearer")},  # bract
    "PO_0020030": {"adaxial": ("PO_0006058", "substituted_bearer"),
                   "abaxial": ("PO_0006057", "substituted_bearer")},  # cotyledon
    "PO_0020038": {"adaxial": ("PO_0008027", "substituted_bearer"),
                   "abaxial": ("PO_0008029", "substituted_bearer")},  # petiole
}
# ``inside``/``outside`` denote adaxial/abaxial only for single perianth members and bracts.
INSIDE_OUTSIDE_BEARERS = frozenset({"PO_0009031", "PO_0009032", "PO_0009033", "PO_0009055"})

_WS = r"\s+"
SURFACE_CUES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "adaxial",
        re.compile(
            r"(?:\babove\b(?!\s+(?:the|a|an|its|middle|base|apex|le|la|les)\b)|\badaxially\b|"
            r"\bon\s+(?:the\s+)?(?:upper|adaxial)\s+(?:surface|side|face)s?\b|"
            r"\b(?:upper|adaxial)\s+(?:surface|side|face)s?\b|"
            r"\ben\s+dessus\b|\bdessus\b|"
            r"(?:\b(?:à|a|sur)\s+la\s+)?\bface\s+(?:sup[ée]rieure|adaxiale)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "abaxial",
        re.compile(
            r"(?:\bbeneath\b(?!\s+(?:the|a|an|its)\b)|\bunderneath\b|\babaxially\b|"
            r"\bbelow\b(?!\s+(?:the|a|an|its|middle|base|apex|le|la|les)\b)|"
            r"\bon\s+(?:the\s+)?(?:lower|under|abaxial)\s*(?:surface|side|face)s?\b|"
            r"\b(?:lower|abaxial)\s+(?:surface|side|face)s?\b|\bunder-?surfaces?\b|"
            r"\ben\s+dessous\b|\bdessous\b|"
            r"(?:\b(?:à|a|sur)\s+la\s+)?\bface\s+(?:inf[ée]rieure|abaxiale)\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "outside",
        re.compile(
            r"(?:\boutside\b|\bexternally\b|\bon\s+the\s+outer\s+(?:surface|side|face)\b|"
            r"\bouter\s+(?:surface|side|face)\b|\b(?:à|a)\s+l['’]ext[ée]rieur\b|"
            r"\bext[ée]rieurement\b|\ben\s+dehors\b|\bface\s+externe\b)",
            re.IGNORECASE,
        ),
    ),
    (
        "inside",
        re.compile(
            r"(?:\binside\b|\binternally\b|\bwithin\b(?!\s+\w)|"
            r"\bon\s+the\s+inner\s+(?:surface|side|face)\b|\binner\s+(?:surface|side|face)\b|"
            r"\b(?:à|a)\s+l['’]int[ée]rieur\b|\bint[ée]rieurement\b|\ben\s+dedans\b|"
            r"\bface\s+interne\b)",
            re.IGNORECASE,
        ),
    ),
)
_SIDE_OF = {"adaxial": "adaxial", "abaxial": "abaxial", "outside": "abaxial", "inside": "adaxial"}


@dataclass(frozen=True)
class SurfaceScope:
    cue_side: str  # adaxial | abaxial | outside | inside
    side: str  # adaxial | abaxial
    scope_class: str
    mode: str
    cue_start: int
    cue_end: int


def surface_cue_at(text: str, start: int, end: int) -> tuple[str, int, int] | None:
    """Return ``(cue_side, start, end)`` when ``text[start:end]`` is exactly one surface cue."""

    fragment = text[start:end]
    for cue_side, pattern in SURFACE_CUES:
        match = pattern.fullmatch(fragment)
        if match:
            return cue_side, start, end
    return None


def find_surface_cues(text: str, start: int, end: int) -> list[tuple[str, int, int]]:
    found: list[tuple[str, int, int]] = []
    for cue_side, pattern in SURFACE_CUES:
        for match in pattern.finditer(text, start, end):
            found.append((cue_side, match.start(), match.end()))
    return sorted(found, key=lambda row: (row[1], -row[2]))


def surface_scope(outer_bearer: str, cue_side: str, cue_start: int, cue_end: int) -> SurfaceScope | None:
    """Map an outer bearer and a surface cue to the reviewed scope class, or ``None``."""

    outer = str(outer_bearer).replace(":", "_")
    if cue_side in {"inside", "outside"} and outer not in INSIDE_OUTSIDE_BEARERS:
        return None
    side = _SIDE_OF.get(cue_side)
    entry = SURFACE_SCOPE.get(outer, {}).get(side or "")
    if entry is None:
        return None
    return SurfaceScope(cue_side, side or "", entry[0], entry[1], cue_start, cue_end)


def reviewed_scope_pairs() -> set[tuple[str, str]]:
    return {
        (outer, scope)
        for outer, sides in SURFACE_SCOPE.items()
        for scope, _mode in sides.values()
    }


@lru_cache(maxsize=4)
def load_bspo_ids(path: str = str(BSPO_TERMS_PATH)) -> frozenset[str]:
    """Pinned BSPO identifiers (``BSPO_nnnnnnn``) from the module term list."""

    ids: set[str] = set()
    source = Path(path)
    if not source.exists():
        return frozenset()
    for line in source.read_text(encoding="utf-8").splitlines():
        token = line.split("#", 1)[0].strip()
        if token.startswith("BSPO:"):
            ids.add(token.replace(":", "_"))
    return frozenset(ids)


@lru_cache(maxsize=4)
def load_bspo_labels(path: str = str(BSPO_TERMS_PATH)) -> dict[str, str]:
    labels: dict[str, str] = {}
    source = Path(path)
    if not source.exists():
        return labels
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.startswith("BSPO:") and "#" in line:
            identifier, label = line.split("#", 1)
            labels[identifier.strip().replace(":", "_")] = label.strip()
    return labels


@lru_cache(maxsize=2)
def _po_graph(path: str = str(PO_OBO_PATH)) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """``(is_a, part_of)`` parent maps of the pinned PO release."""

    is_a: dict[str, set[str]] = {}
    part_of: dict[str, set[str]] = {}
    current = ""
    source = Path(path)
    if not source.exists():
        return is_a, part_of
    for line in source.read_text(encoding="utf-8").splitlines():
        if line.startswith("[Term]") or line.startswith("[Typedef]"):
            current = ""
        elif line.startswith("id: PO:"):
            current = line[4:].strip().replace(":", "_")
        elif current and line.startswith("is_a: PO:"):
            parent = line[6:].split("!", 1)[0].strip().replace(":", "_")
            is_a.setdefault(current, set()).add(parent)
        elif current and line.startswith("relationship: part_of PO:"):
            parent = line.split("part_of", 1)[1].split("!", 1)[0].strip().replace(":", "_")
            part_of.setdefault(current, set()).add(parent)
    return is_a, part_of


def _closure(start: str, graph: dict[str, set[str]]) -> set[str]:
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = stack.pop()
        for parent in graph.get(node, ()):
            if parent not in seen:
                seen.add(parent)
                stack.append(parent)
    return seen


def po_scope_within(scope_class: str, outer_bearer: str) -> bool:
    """True when PO places ``scope_class`` as a part of ``outer_bearer`` or of a superclass of it.

    The part side may be generalized by one ``is_a`` step before the first ``part_of`` step; after
    it only ``part_of`` is followed, so a leaf part is never accepted for a petal via a shared
    ``phyllome`` superclass.  The whole reached may be ``outer_bearer`` or an ``is_a`` ancestor of
    it (a vascular leaf is a leaf).
    """

    is_a, part_of = _po_graph()
    if not part_of:
        return False
    scope = scope_class.replace(":", "_")
    outer = outer_bearer.replace(":", "_")
    # One generalization step only: ``leaf lamina abaxial epidermis`` -> ``leaf lamina epidermis``
    # (part of leaf lamina).  Deeper steps reach generic classes (``phyllome epidermis``) whose
    # wholes are too general to place the part in a specific organ.
    part_side = {scope, *is_a.get(scope, set())}
    wholes: set[str] = set()
    for node in part_side:
        for parent in part_of.get(node, ()):
            wholes.add(parent)
            wholes.update(_closure(parent, part_of))
    return bool(wholes & {outer, *_closure(outer, is_a)})


def part_rows(rows: Any, depth: int = 1) -> list[tuple[int, dict[str, Any]]]:
    """Flatten nested ``part_restrictions`` into ``(depth, row)`` pairs (source-order)."""

    flattened: list[tuple[int, dict[str, Any]]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        flattened.append((depth, row))
        flattened.extend(part_rows(row.get("part_restrictions", []) or [], depth + 1))
    return flattened


def part_evidence_spans(assertion: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    spans = [
        (str(row.get("part_text") or ""), row.get("part_start"), row.get("part_end"))
        for _depth, row in part_rows(assertion.get("part_restrictions", []) or [])
        if row.get("part_text") or row.get("part_start") is not None
    ]
    scope = assertion.get("bearer_scope")
    if isinstance(scope, dict) and scope.get("scope_text"):
        spans.append((str(scope.get("scope_text") or ""), scope.get("scope_start"), scope.get("scope_end")))
    return spans


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_positional(
    assertion: dict[str, Any],
    text: str,
    *,
    bspo_ids: frozenset[str] | set[str] | None = None,
    check_po_closure: bool = True,
) -> list[tuple[str, str]]:
    """Validate E3 part evidence, depth, BSPO fillers and bearer scope; ``[(code, message)]``."""

    issues: list[tuple[str, str]] = []
    pinned = load_bspo_ids() if bspo_ids is None else bspo_ids
    for depth, row in part_rows(assertion.get("part_restrictions", []) or []):
        filler = str(row.get("filler_class", "") or "").replace(":", "_")
        if depth > 2:
            issues.append(("part_restriction_depth_exceeded", f"depth {depth}: {filler}"))
        if filler.startswith("BSPO_") and pinned and filler not in pinned:
            issues.append(("unknown_part_restriction_bspo_filler", filler))
        if not (row.get("qualities") or []) and not (row.get("part_restrictions") or []):
            issues.append(("part_restriction_empty", filler))
        part_text = row.get("part_text")
        start, end = row.get("part_start"), row.get("part_end")
        if part_text or start is not None or end is not None:
            if (
                not isinstance(part_text, str)
                or not part_text
                or not _int(start)
                or not _int(end)
                or not (0 <= start < end <= len(text))
                or text[start:end] != part_text
            ):
                issues.append(("part_text_not_verbatim", repr(part_text)))
    scope = assertion.get("bearer_scope")
    if not scope:
        return issues
    if not isinstance(scope, dict):
        return [*issues, ("bearer_scope_not_object", repr(type(scope)))]
    scope_text = scope.get("scope_text")
    start, end = scope.get("scope_start"), scope.get("scope_end")
    if (
        not isinstance(scope_text, str)
        or not scope_text
        or not _int(start)
        or not _int(end)
        or not (0 <= start < end <= len(text))
        or text[start:end] != scope_text
    ):
        issues.append(("bearer_scope_not_verbatim", repr(scope_text)))
    outer = str(scope.get("outer_bearer", "") or "").replace(":", "_")
    scope_class = str(scope.get("scope_class", "") or "").replace(":", "_")
    mode = str(scope.get("mode", "") or "")
    bearer = str(assertion.get("po_id", "") or "").replace(":", "_")
    fillers = {
        str(row.get("filler_class", "") or "").replace(":", "_")
        for _depth, row in part_rows(assertion.get("part_restrictions", []) or [])
    }
    if mode == "substituted_bearer" and bearer != scope_class:
        issues.append(("bearer_scope_mode_mismatch", f"po_id {bearer} != scope {scope_class}"))
    elif mode == "part_restriction" and scope_class not in fillers:
        issues.append(("bearer_scope_mode_mismatch", f"no part filler {scope_class}"))
    elif mode not in {"substituted_bearer", "part_restriction"}:
        issues.append(("bearer_scope_mode_mismatch", f"unknown mode {mode!r}"))
    if mode == "part_restriction" and bearer != outer:
        issues.append(("bearer_scope_mode_mismatch", f"part restriction bearer {bearer} != {outer}"))
    if scope_class.startswith("BSPO_"):
        if pinned and scope_class not in pinned:
            issues.append(("unknown_bearer_scope_bspo_class", scope_class))
    elif (outer, scope_class) not in reviewed_scope_pairs() and not (
        check_po_closure
        and scope_class.startswith("PO_")
        and outer.startswith("PO_")
        and po_scope_within(scope_class, outer)
    ):
        issues.append(
            ("bearer_scope_outer_not_ancestor", f"{scope_class} is not a reviewed part of {outer}")
        )
    return issues
