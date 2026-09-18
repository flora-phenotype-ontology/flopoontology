"""Leaflet-context guard for leaf-part bearers.

In compound-leaf descriptions the lamina described after the leaflets belongs to the leaflet:
``folioles 5–7; pétiolule …; limbe elliptique, acuminé au sommet`` or ``lateral leaflets
elliptic, …, apex acuminate``.  Attaching such a quality to leaf apex, leaf base or leaf lamina
misattributes it, and PO has no leaflet apex, leaflet base or leaflet lamina class to re-bear it
on.  Recovery passes therefore keep these spans unresolved.

The guard fires when a leaflet cue (foliole/-foliolé, leaflet, pinna, pinnule, penne, segment)
occurs earlier in the same segment and the description has not returned to the leaf (no
``leaf``/``leaves``/``feuille(s)`` noun between that cue and the quality).  A lamina noun
(``limbe``/``blade``/``lamina``) after the cue is recorded as the stronger pattern.
"""

from __future__ import annotations

import re


# Leaf lamina (PO_0020039) is guarded by the ``foliol*`` trigger only.  A manual review of all 789
# stage22 leaf-lamina assertions in full-guard context found 705 (89.4%) leaflet-borne, below the
# 95% bar: fern fronds (``lamina`` after ``pinnae``), petal laminae and dissected-leaf ``segments``
# are the counterexamples.  The ``foliol*`` cue alone was 608/610 (99.7%) leaflet.
LEAF_LAMINA_PO_ID = "PO_0020039"
LEAF_PART_PO_IDS = frozenset(
    {
        "PO_0020137",  # leaf apex
        "PO_0020040",  # leaf base
    }
)
LEAFLET_CUE = re.compile(
    r"foliol\w*|\bleaflets?\b|\bpinnae?\b|\bpinnules?\b|\bpennes?\b|\bsegments?\b",
    re.IGNORECASE,
)
FOLIOLE_CUE = re.compile(r"foliol\w*", re.IGNORECASE)
LAMINA_CUE = re.compile(r"\blimbes?\b|\bblades?\b|\blaminae?\b", re.IGNORECASE)
LEAF_NOUN = re.compile(r"\b(?:leaf|leaves|feuilles?)\b", re.IGNORECASE)
# A leaf noun inside a prepositional phrase (``poils … sur les jeunes feuilles``) does not return
# the description to the leaf.
_PREPOSITIONAL = re.compile(
    r"\b(?:sur|des|de|du|aux|of|on|than|que)\s+"
    r"(?:(?:les|la|le|l'|l’|the|young|jeunes|old|vieilles)\s+){0,2}$",
    re.IGNORECASE,
)


def _returns_to_leaf(prefix: str, start: int) -> bool:
    return any(
        not _PREPOSITIONAL.search(prefix[: match.start()])
        for match in LEAF_NOUN.finditer(prefix, start)
    )


def leaflet_context(text: str, position: int) -> str:
    """Return the guard pattern name if ``position`` sits in a leaflet description, else ``""``.

    ``leaflet_clause_then_lamina`` means a leaflet cue is followed by a lamina noun before
    ``position``; ``leaflet_subject`` means the leaflet itself is the described subject.
    """

    prefix = text[: max(0, position)]
    cues = list(LEAFLET_CUE.finditer(prefix))
    if not cues:
        return ""
    last = cues[-1]
    if _returns_to_leaf(prefix, last.end()):
        return ""
    if LAMINA_CUE.search(prefix, last.end()):
        return "leaflet_clause_then_lamina"
    return "leaflet_subject"


def foliole_context(text: str, position: int) -> bool:
    """True when a ``foliol*`` cue precedes ``position`` with no return to the leaf."""

    prefix = text[: max(0, position)]
    cues = list(FOLIOLE_CUE.finditer(prefix))
    return bool(cues) and not _returns_to_leaf(prefix, cues[-1].end())


def leaflet_guarded(po_id: str, text: str, position: int) -> bool:
    """True when a leaf-part bearer must not be asserted at ``position``.

    Leaf apex and leaf base use the full leaflet context; leaf lamina uses only the
    high-precision ``foliol*`` trigger.
    """

    if po_id in LEAF_PART_PO_IDS:
        return bool(leaflet_context(text, position))
    if po_id == LEAF_LAMINA_PO_ID:
        return foliole_context(text, position)
    return False


# Curator-approved FLOPO-local leaflet part classes (2026-09-18; ontology/
# flopo-anatomy-support-extension.ttl).  A guarded leaf-part bearer is re-borne on the leaflet
# part instead of being dropped; the Phase 7 gate still decides whether the new bearer x quality
# pair is admissible (config/valid_combinations.tsv).
LEAFLET_APEX_ID = "FLOPO_0986000"
LEAFLET_BASE_ID = "FLOPO_0986001"
LEAFLET_LAMINA_ID = "FLOPO_0986002"
LEAFLET_PART_BY_LEAF_PART = {
    "PO_0020137": LEAFLET_APEX_ID,
    "PO_0020040": LEAFLET_BASE_ID,
    LEAF_LAMINA_PO_ID: LEAFLET_LAMINA_ID,
}


def leaflet_bearer(po_id: str, text: str, position: int) -> str:
    """Return the FLOPO leaflet-part bearer for a guarded leaf-part bearer, else ``po_id``.

    Uses exactly the :func:`leaflet_guarded` triggers (full context for apex/base, ``foliol*``
    only for the lamina), so the remap never fires where the guard would not.
    """

    if po_id in LEAFLET_PART_BY_LEAF_PART and leaflet_guarded(po_id, text, position):
        return LEAFLET_PART_BY_LEAF_PART[po_id]
    return po_id
