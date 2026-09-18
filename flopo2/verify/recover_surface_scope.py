"""Re-admit surface-restricted values on reviewed surface bearers (schema extension E3).

Two corrections removed values that the source restricts to one surface of a laminar organ:

* ``surface-audit/surface-correction-delta.jsonl`` removed whole-organ colour/pilosity/texture
  assertions (``limbe glabre en dessus`` asserted as *leaf lamina glabrous*) and restored each
  value span as ``missing_or_unsupported_bearer`` (``pending_bearer`` "upper/lower/other surface");
* ``shape-tiebreak/correction-delta.jsonl`` removed leaflet values borne on the leaf lamina; the
  leaflet re-admission held the ones whose member names a surface
  (``surface_restricted_value``/``surface_restricted_next_member`` in
  ``leaflet-readmit-held.tsv``).

For every such removal this module re-asserts the *same* value on the reviewed surface class of
:func:`flopo2.annotation.positional.surface_scope` (PO first: ``leaf lamina adaxial epidermis``,
``sepal abaxial epidermis``; leaflet sides are portions of the leaf's adaxial/abaxial epidermis)
as a substituted bearer, with a ``bearer_scope`` that keeps the outer organ and the exact cue.
A value is re-admitted only when

* its family is pilosity, colour or surface texture;
* its own comma member names exactly one side (a both-surfaces cue, mixed sides without an
  adjacent cue, or a cue only in a neighbouring member stay unresolved);
* the member names no other lamina part (veins, margin, base, apex, glands ...) that could be the
  real bearer, and a colour does not sit beside hairs/indumentum (the colour of the hairs);
* :func:`flopo2.verify.gates.check_assertion` does not block it (``review`` for a novel
  bearer x quality pair is kept).

Output is a *correction* delta (applied after ``surface_restriction_correction``): it adds the
scoped assertion with a statement covering bearer, value and cue, and clears the restored span.

    python -m flopo2.verify.recover_surface_scope BASE --out-dir DIR [--sample-size 120]
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import random
import re
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from flopo2.annotation.positional import find_surface_cues, surface_scope
from flopo2.annotation.provenance import _normalise_statement, stable_statement_id
from flopo2.annotation.qualitative import is_fac_representable
from flopo2.extract.surface_context import value_member
from flopo2.owl.annotation_class import ensure_annotation_class_iri
from flopo2.verify.apply_deltas import DELTA_KEY_FIELDS, assertion_identity
from flopo2.verify.readmit_leaflet_bearers import GateResources
from flopo2.verify.surface_restriction_correction import _PILOSITY, value_family

EXTRACTOR = "deterministic_surface_scope_readmission_v1"
PROVENANCE = "surface_scope:E3"
ROOT = Path("scratchpad/flopo-claude-recovery-20260918")
SURFACE_CORRECTION = ROOT / "surface-audit" / "surface-correction-delta.jsonl"
LEAFLET_CORRECTION = ROOT / "shape-tiebreak" / "correction-delta.jsonl"
LEAFLET_HELD = ROOT / "shape-tiebreak" / "leaflet-readmit-held.tsv"
LEAFLET_SURFACE_GUARDS = frozenset({"surface_restricted_value", "surface_restricted_next_member"})
LEAFLET_LAMINA = "FLOPO_0986002"

_BOTH = re.compile(
    r"(?<![\w-])(?:(?:deux|2)\s+faces|both\s+(?:sides|surfaces|faces)|either\s+(?:side|surface)|"
    r"(?:above|dessus)\s+(?:and|et)\s+(?:beneath|below|dessous)|"
    r"(?:beneath|below|dessous)\s+(?:and|et)\s+(?:above|dessus))(?![\w-])",
    re.IGNORECASE,
)
# A lamina part in the member may be the true bearer (``nervures pubescentes en dessous``).
_OTHER_PART = re.compile(
    r"(?<!\w)(?:marges?|margins?|bords?|sommets?|apex|apices|bases?|acumens?|nervures?|"
    r"nerves?|veins?|veinules?|veinlets?|midribs?|costae?|r[ée]ticulum|reticulation|"
    r"domaties?|domatia|glandes?|glands?|ponctu\w*|punct\w*|dots?|points?|taches?|spots?|"
    r"c[ôo]tes?|ribs?|axils?|aisselles?|p[ée]tiol\w*|rachis|lobes?|dents?|teeth)(?![\w-])",
    re.IGNORECASE,
)
_HAIR_CONTEXT = re.compile(
    r"(?<!\w)(?:poils?|poilu\w*|velu\w*|cils?|cilia|ciliate|hairs?|hairy|indument\w*|tomentum|tomente\w*|tomentos\w*|tomentell\w*|"
    r"pubesc\w*|velout\w*|velutin\w*|soyeu\w*|seric\w*|silky|lanat\w*|laineu\w*|woolly|"
    r"villos\w*|pilos\w*|hirsut\w*|strigos\w*|puberul\w*|[ée]cailles?|scales?|lepido\w*|"
    r"stellate|[ée]toil\w*|flocc\w*|poudr\w*|powder\w*|arachn\w*|aran[ée]\w*|canesc\w*|farin\w*|furfur\w*|feutr\w*|felted|felty|waxy?|cireu\w*|pruin\w*)(?![\w-])",
    re.IGNORECASE,
)
# Temporal change, exceptions and region words make the side attachment unsafe (``d'abord
# pubescentes dessous puis glabres``; ``glabrous except sparsely hairy above``; ``vertes en bas et
# grisâtres au-dessus``).
_UNSAFE_MEMBER = re.compile(
    r"(?<![\w-])(?:puis|then|d['’]abord|at\s+first|becoming|devenant|later|finally|"
    r"except|excepted|excepting|sauf|except[ée]e?s?|but|mais|en\s+bas|en\s+haut|"
    r"at\s+the\s+(?:base|top|apex)|towards?|vers|"
    r"non|not|pas|nullement|hardly|scarcely|[àa]\s+peine|l['’]exception|exception)(?![\w-])",
    re.IGNORECASE,
)
# Patterned colour (``marbrées de blanc``, ``mottled``) is not a colour of the whole surface.
_PATTERN = re.compile(
    r"(?<!\w)(?:marbr\w*|tachet\w*|tach[ée]\w*|mottled|marbled|spotted|variegat\w*|"
    r"panach\w*|macul\w*|punct\w*|ponctu\w*|dotted|glandul\w*|gland\w*|stri[ée]\w*|streak\w*|veined|vein[ée]\w*|tinged|teint\w*|lav[ée]\w*)(?![\w-])",
    re.IGNORECASE,
)
# ``below``/``above`` also name the lower/upper *part* of an axis-like organ (``tepals yellow
# below, purple at apex``); as surface cues they are trusted only for leaves and leaflets.
_BELOW_ABOVE = re.compile(r"^(?:below|above)$", re.IGNORECASE)
_COMPARATIVE = re.compile(
    r"(?<![\w-])(?:paler|darker|lighter|brighter|duller|p[âa]les?|plus|moins|less|more)(?![\w-])",
    re.IGNORECASE,
)
_REGION_PREFIX = re.compile(r"(?:\bau[- ]|\bpar[- ]|\bci[- ])$", re.IGNORECASE)
# Organ nouns.  The first organ noun of the clause holding the value is its subject; it must name
# the outer organ (``Peduncle …, glabrous below``, ``Leaf-rhachis … pubescent above`` and
# ``pétioles … pubescents dessus`` are not lamina surfaces).
_LEAF_NOUNS = (
    r"leaf-blades?|leaf\s+blades?|leaves|leaf(?!-)|laminae?|blades?|feuilles?|limbes?"
)
_LEAFLET_NOUNS = r"leaflets?|folioles?|pinnules?|laterals|terminal"
SUBJECT_NOUNS = {
    "leaf": _LEAF_NOUNS,
    "leaflet": _LEAFLET_NOUNS + "|" + _LEAF_NOUNS,
    "PO_0009031": r"sepals?|s[ée]pales?|calyx|calice|calyx-lobes?",
    "PO_0009032": r"petals?|p[ée]tales?",
    "PO_0009033": r"tepals?|t[ée]pales?",
    "PO_0009055": r"bracts?|bract[ée]es?",
}
_OUTER_GROUP = {
    "PO_0009025": "leaf", "PO_0025034": "leaf", "PO_0020039": "leaf",
    "PO_0020049": "leaflet", "FLOPO_0986002": "leaflet",
}
_OTHER_ORGANS = (
    r"peduncles?|pedicels?|p[ée]doncules?|p[ée]dicelles?|petioles?|p[ée]tioles?|p[ée]tiolules?|"
    r"leaf-rh?achis|rh?achis|rhachides|stems?|tiges?|branch(?:es|lets)?|rameaux|twigs|sheaths?|"
    r"gaines?|stipules?|culms?|spikes?|inflorescences?|ovar(?:y|ies)|ovaires?|fruits?|"
    r"capsules?|seeds?|graines?|corolla|corolle|tubes?|anthers?|filaments?|stamens?|"
    r"[ée]tamines?|styles?|glumes?|lemmas?|involucres?|capitula|flowers?|fleurs?|midribs?|"
    r"nervures?|veins?|hairs|poils|scales|lobes?|segments?|ligules?|spathes?|cyathia|rays?|"
    r"bracteoles?|bract[ée]oles?|labell(?:um|e)|lips?|spurs?|[ée]perons?|bracts?|bract[ée]es?|"
    r"sepals?|s[ée]pales?|calyx|calice|petals?|p[ée]tales?|tepals?|t[ée]pales?|gorge|throat"
)
# A hedge between value and cue attaches the cue to a later value (``glabre parfois scabre dessus``).
_HEDGE_BETWEEN = re.compile(
    r"(?<![\w-])(?:parfois|sometimes|souvent|often|rarement|rarely|usually|g[ée]n[ée]ralement|"
    r"occasionally|quelquefois|or|ou)(?![\w-])",
    re.IGNORECASE,
)
_ADJACENT_FILLER = re.compile(r"[\s±]*(?:\w+ment\s+|très\s+|very\s+|rather\s+|assez\s+)*[\s]*$")


def _key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(name) for name in DELTA_KEY_FIELDS)


def _covers(removal: dict[str, Any], span: dict[str, Any]) -> bool:
    return int(removal["source_start"]) <= int(span["start"]) and int(span["end"]) <= int(
        removal["source_end"]
    )


def pair_surface_removals(line: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Pair each surface-correction removal with the span it restored (same order, same value)."""

    removals = list(line.get("remove_assertions", []) or [])
    restored = list(line.get("add_unresolved", []) or [])
    if len(removals) != len(restored):
        raise ValueError(f"{line['key']}: {len(removals)} removals but {len(restored)} spans")
    for removal, span in zip(removals, restored):
        if removal["pato_id"] != span.get("candidate_pato_id") or not _covers(removal, span):
            raise ValueError(f"{line['key']}: removal {removal} does not match {span}")
    return list(zip(removals, restored))


def _load_leaflet_held(path: Path) -> set[tuple[Any, ...]]:
    held: set[tuple[Any, ...]] = set()
    if not path.exists():
        return held
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("gate_reasons") in LEAFLET_SURFACE_GUARDS:
                held.add(
                    (
                        row["source"],
                        row["source_id"],
                        int(row["source_segment_index"]),
                        row["pato_id"],
                        int(row["source_start"]),
                        int(row["source_end"]),
                    )
                )
    return held


def load_candidates(
    surface_correction: Path = SURFACE_CORRECTION,
    leaflet_correction: Path = LEAFLET_CORRECTION,
    leaflet_held: Path = LEAFLET_HELD,
) -> dict[tuple[Any, ...], dict[str, Any]]:
    """``segment key -> {"key", "items": [(origin, outer_override, removal, span)]}``."""

    wanted: dict[tuple[Any, ...], dict[str, Any]] = {}
    for raw in Path(surface_correction).open(encoding="utf-8"):
        if raw.strip():
            line = json.loads(raw)
            entry = wanted.setdefault(_key(line["key"]), {"key": line["key"], "items": []})
            for removal, span in pair_surface_removals(line):
                entry["items"].append(("surface_restriction_correction", "", removal, span))
    held = _load_leaflet_held(Path(leaflet_held))
    for raw in Path(leaflet_correction).open(encoding="utf-8"):
        if not raw.strip():
            continue
        line = json.loads(raw)
        key = line["key"]
        removals = list(line.get("remove_assertions", []) or [])
        spans = list(line.get("add_unresolved", []) or [])
        for removal, span in zip(removals, spans):
            if span.get("pending_bearer") != "leaflet lamina":
                continue
            marker = (
                key["source"],
                str(key["source_id"]),
                int(key["source_segment_index"]),
                removal["pato_id"],
                int(removal["source_start"]),
                int(removal["source_end"]),
            )
            if marker not in held:
                continue
            entry = wanted.setdefault(_key(key), {"key": key, "items": []})
            entry["items"].append(("leaflet_bearer_correction", LEAFLET_LAMINA, removal, span))
    return wanted


# Surface textures only; whole-organ consistency (coriaceous, membranous, chartaceous) is not a
# property of one surface (``assez coriace et brillant en dessus``).
_SURFACE_TEXTURE_LABEL = re.compile(
    r"smooth|rough|glossy|shiny|shining|dull|glaucous|papillose|rugose|verrucose|scabr|"
    r"wrinkled|glistening|lustrous|waxy|pruinose|matt",
    re.IGNORECASE,
)


def _surface_texture(assertion: dict[str, Any], labels: dict[str, str]) -> bool:
    ids = [assertion.get("pato_id", ""), *(assertion.get("value_terms") or [])]
    return all(
        _SURFACE_TEXTURE_LABEL.search(labels.get(identifier, ""))
        for identifier in ids
        if identifier and identifier != "PATO_0000150"
    )


def attach_surface_cue(text: str, start: int, end: int) -> tuple[str, int, int] | str:
    """Return ``(cue_side, cue_start, cue_end)`` for the value, or a residual reason.

    ``cue_side == "both"`` (curator decision 2026-09-18, part c) marks a "both surfaces" /
    "sur les deux faces" style cue: the caller re-bears the value on *both* the adaxial and
    the abaxial scope class, as two separate assertions sharing this one cue span.
    """

    left, right = value_member(text, start, end)
    member = text[left:right]
    both_match = _BOTH.search(member)
    if both_match:
        return "both", left + both_match.start(), left + both_match.end()
    cues = find_surface_cues(text, left, right)
    # Drop cues nested inside a longer cue (``on the lower surface`` vs ``lower surface``).
    cues = [
        cue
        for cue in cues
        if not any(o != cue and o[1] <= cue[1] and cue[2] <= o[2] for o in cues)
    ]
    if not cues:
        return "no_surface_cue_in_member"
    if _OTHER_PART.search(member):
        return "other_lamina_part_in_member"
    if _UNSAFE_MEMBER.search(member):
        return "temporal_exception_or_region_in_member"
    if any(_REGION_PREFIX.search(text[max(0, cue[1] - 4) : cue[1]]) for cue in cues):
        return "region_cue_au_dessus"
    sides = {cue[0] for cue in cues}
    if len(sides) == 1:
        # Repeated cue for one side: take the nearest following, else nearest preceding.
        after = [cue for cue in cues if cue[1] >= end]
        chosen = after[0] if after else cues[-1]
    else:
        adjacent = [
            cue
            for cue in cues
            if cue[1] >= end and _ADJACENT_FILLER.fullmatch(text[end : cue[1]])
        ]
        if len(adjacent) != 1:
            return "mixed_sides_without_adjacent_cue"
        chosen = adjacent[0]
    between = text[end : chosen[1]] if chosen[1] >= end else text[chosen[2] : start]
    if _COMPARATIVE.search(between):
        return "comparative_between_value_and_cue"
    if chosen[1] >= end and _HEDGE_BETWEEN.search(between):
        return "hedge_between_value_and_cue"
    return chosen


_COLOUR_WORD = re.compile(
    r"(?<!\w)(?:green|vert\w*|verd\w*|brown\w*|brun\w*|marron|white\w*|blanc\w*|grey\w*|gray\w*|"
    r"gris\w*|yellow\w*|jaun\w*|red\w*|rouge\w*|roux|rousse\w*|purpl\w*|pourpr\w*|viol\w*|"
    r"black\w*|noir\w*|silver\w*|argent\w*|golden|dor[ée]\w*|glauc\w*|olive\w*|fauve\w*|"
    r"ferrugin\w*|rust\w*|rouill\w*|orange\w*|pink\w*|rose\w*|blu\w*|bleu\w*)(?![\w-])",
    re.IGNORECASE,
)


_FRENCH_PILOSITY = re.compile(
    r"(?<!\w)(?:glabr\w*|velu\w*|laineu\w*|coton\w*|soyeu\w*|tomenteu\w*|pubescen\w*|"
    r"pub[ée]rul\w*|strigu\w*|hirsut\w*|hispid\w*|poilu\w*|scabr\w*)",
    re.IGNORECASE,
)


def contradicting_same_side(text: str, start: int, end: int, cue: tuple[str, int, int], family: str) -> bool:
    """Another member of the clause names the same side with a value of the same family.

    ``brun foncé et glabres en dessous, velues-cotonneuses argentées en dessous`` is a source
    slip (one ``dessous`` should read ``dessus``); neither value can be attached safely.
    """

    clause_start = max(text.rfind(";", 0, start), text.rfind(". ", 0, start)) + 1
    ends = [i for i in (text.find(";", end), text.find(". ", end)) if i >= 0]
    clause_end = min(ends) if ends else len(text)
    own_left, own_right = value_member(text, start, end)
    if family == "pilosity":
        patterns: tuple[re.Pattern[str], ...] = (_PILOSITY, _HAIR_CONTEXT, _FRENCH_PILOSITY)
    elif family == "colour":
        patterns = (_COLOUR_WORD,)
    else:
        return False
    for side, cue_start, cue_end in find_surface_cues(text, clause_start, clause_end):
        if side != cue[0] or own_left <= cue_start < own_right:
            continue
        left, right = value_member(text, cue_start, cue_end)
        if any(pattern.search(text, left, right) for pattern in patterns):
            return True
    return False


def clause_subject_ok(text: str, start: int, outer: str) -> bool:
    """Every organ noun of the value's clause before it names the outer organ (or none is named)."""

    group = _OUTER_GROUP.get(outer, outer)
    allowed = SUBJECT_NOUNS.get(group)
    if allowed is None:
        return False
    # A sentence ends at ``. `` before a capital letter (``d'env. 2 mm`` is an abbreviation).
    boundary = max(text.rfind(";", 0, start), max(
        (m.end() for m in re.finditer(r"\.\s+(?=[A-ZÀ-Ý])", text[:start])), default=0
    ) - 1)
    clause_start = boundary + 1
    noun = re.compile(
        rf"(?<!\w)(?:(?P<allowed>{allowed})|(?P<other>{_OTHER_ORGANS}))(?![\w])",
        re.IGNORECASE,
    )
    # Every organ noun between the clause start and the value must name the outer organ
    # (``Leaves: rhachis …, pubescent above`` is the rachis).
    return all(match.group("allowed") is not None for match in noun.finditer(text, clause_start, start))


def _rebear_side(
    record: dict[str, Any],
    text: str,
    original: dict[str, Any],
    span: dict[str, Any],
    origin: str,
    outer_override: str,
    both: bool,
    family: str,
    cue_side: str,
    cue_start: int,
    cue_end: int,
) -> tuple[tuple[dict[str, Any], dict[str, Any]] | None, str]:
    """Build one re-borne assertion for a single resolved side; ``reason`` is empty on success."""

    start, end = int(span["start"]), int(span["end"])
    if contradicting_same_side(text, start, end, (cue_side, cue_start, cue_end), family):
        return None, "contradicting_same_side_member"
    if family == "colour":
        left, right = value_member(text, start, end)
        if _HAIR_CONTEXT.search(text, left, right):
            return None, "colour_beside_indumentum"
        if _PATTERN.search(text, left, right):
            return None, "patterned_colour"
    outer = outer_override or str(original.get("po_id", ""))
    scope = surface_scope(outer, cue_side, cue_start, cue_end)
    if scope is None:
        return None, f"no_reviewed_scope:{outer}:{cue_side}"
    if not both and _BELOW_ABOVE.match(text[cue_start:cue_end]) and _OUTER_GROUP.get(outer) is None:
        return None, "below_above_on_non_leaf_organ"
    if not clause_subject_ok(text, start, outer):
        return None, "clause_subject_not_outer_organ"
    assertion = copy.deepcopy(original)
    for field in ("gate", "phenotype_class_iri", "source_statement_id"):
        assertion.pop(field, None)
    assertion["po_id"] = scope.scope_class
    assertion["bearer_scope"] = {
        "outer_bearer": outer,
        "scope_class": scope.scope_class,
        "mode": scope.mode,
        "scope_text": text[cue_start:cue_end],
        "scope_start": cue_start,
        "scope_end": cue_end,
    }
    source_start = min(int(original["source_start"]), cue_start)
    source_end = max(int(original["source_end"]), cue_end)
    assertion["source_start"] = source_start
    assertion["source_end"] = source_end
    assertion["source_text"] = text[source_start:source_end]
    assertion["extractor"] = EXTRACTOR
    assertion["mapping_provenance"] = [
        *(original.get("mapping_provenance", []) or []),
        PROVENANCE,
        f"surface_scope:{outer}->{scope.scope_class}:{scope.cue_side}",
        f"surface_scope_readmits:{origin}:{original.get('extractor', '')}",
        *(["surface_scope:both_surfaces_split"] if both else []),
    ]
    composition = assertion.get("composition")
    if isinstance(composition, dict):
        composition["status"] = "accept"
    # The statement covers bearer mention, original evidence and the surface cue.
    points = [source_start, source_end]
    for key_start, key_end in (("bearer_start", "bearer_end"), ("modality_start", "modality_end")):
        if isinstance(original.get(key_start), int) and isinstance(original.get(key_end), int):
            points.extend([original[key_start], original[key_end]])
    statements = {
        row.get("statement_id"): row for row in record.get("source_statements", []) or []
    }
    old_statement = statements.get(original.get("source_statement_id"))
    if old_statement is not None:
        points.extend([int(old_statement["start"]), int(old_statement["end"])])
    statement_start, statement_end = min(points), max(points)
    verbatim = text[statement_start:statement_end]
    statement = _normalise_statement(
        record,
        {
            "statement_id": stable_statement_id(record, statement_start, statement_end, verbatim),
            "verbatim_text": verbatim,
            "start": statement_start,
            "end": statement_end,
        },
    )
    assertion["source_statement_id"] = statement["statement_id"]
    return (assertion, statement), ""


def rebear(
    record: dict[str, Any],
    original: dict[str, Any],
    span: dict[str, Any],
    origin: str,
    outer_override: str,
    labels: dict[str, str],
) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], str]:
    """Return ``([(assertion, statement), ...], reason)``; ``reason`` is empty when at least one
    assertion is produced.

    A "both surfaces" cue (curator decision 2026-09-18, part c) yields *two* results, one per
    side, each with its own ``bearer_scope``; every other cue yields at most one.
    """

    text = str(record.get("text", "") or "")
    family = value_family(original, labels)
    if family not in {"pilosity", "colour", "texture"}:
        return [], "not_a_surface_value"
    if family == "texture" and not _surface_texture(original, labels):
        return [], "texture_not_a_surface_property"
    start, end = int(span["start"]), int(span["end"])
    cue = attach_surface_cue(text, start, end)
    if isinstance(cue, str):
        return [], cue
    cue_side, cue_start, cue_end = cue
    both = cue_side == "both"
    sides = ("adaxial", "abaxial") if both else (cue_side,)
    results: list[tuple[dict[str, Any], dict[str, Any]]] = []
    reason = ""
    for side in sides:
        result, reason = _rebear_side(
            record, text, original, span, origin, outer_override, both, family, side, cue_start, cue_end
        )
        if result is not None:
            results.append(result)
    if not results:
        return [], reason
    return results, ""


def build(
    base: Path,
    out_dir: Path,
    *,
    sample_size: int = 120,
    seed: int = 20260923,
    resources: GateResources | None = None,
    candidates: dict[tuple[Any, ...], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    resources = resources or GateResources()
    wanted = candidates if candidates is not None else load_candidates()
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    audit: list[dict[str, Any]] = []
    residual_examples: dict[str, list[str]] = {}
    lines = 0
    found = 0
    delta_path = out_dir / "surface-scope-delta.jsonl"
    with delta_path.open("w", encoding="utf-8") as out, Path(base).open(encoding="utf-8") as src:
        for raw in src:
            record = json.loads(raw)
            entry = wanted.get(_key(record))
            if entry is None:
                continue
            found += 1
            text = str(record.get("text", "") or "")
            existing = {assertion_identity(row): row for row in record.get("assertions", []) or []}
            add_statements: dict[str, dict[str, Any]] = {}
            known = {row.get("statement_id") for row in record.get("source_statements", []) or []}
            add_assertions, clears = [], []
            for origin, outer_override, removal, span in entry["items"]:
                counts[f"candidates:{origin}"] += 1
                original = existing.get(assertion_identity(removal))
                if original is None:
                    raise ValueError(f"{entry['key']}: removed assertion not in base: {removal}")
                results, reason = rebear(
                    record, original, span, origin, outer_override, resources.pato_labels
                )
                if not results:
                    counts[f"residual:{reason.split(':')[0]}"] += 1
                    if reason.startswith("no_reviewed_scope"):
                        counts[f"residual:{reason}"] += 1
                    examples = residual_examples.setdefault(reason, [])
                    if len(examples) < 5:
                        examples.append(text[max(0, span["start"] - 60) : span["end"] + 40])
                    continue
                added_any = False
                for assertion, statement in results:
                    gate = resources.check(record, assertion)
                    if gate.status == "blocked":
                        counts["residual:gate_blocked"] += 1
                        continue
                    assertion["gate"] = asdict(gate)
                    if is_fac_representable(assertion):
                        ensure_annotation_class_iri(assertion)
                    if statement["statement_id"] not in known:
                        add_statements.setdefault(statement["statement_id"], statement)
                    add_assertions.append(assertion)
                    added_any = True
                    scope = assertion["bearer_scope"]
                    counts["readmitted"] += 1
                    counts[f"gate:{gate.status}"] += 1
                    counts[f"scope:{scope['outer_bearer']}->{scope['scope_class']}"] += 1
                    counts[f"language:{record.get('language', '')}"] += 1
                    counts[f"origin:{origin}"] += 1
                    audit.append(
                        {
                            "key": f"{record['source']}:{record['source_id']}:{record['source_segment_index']}",
                            "span": f"{span['start']}-{span['end']}:{span['surface_form']}",
                            "window": text[max(0, span["start"] - 110) : span["end"] + 70],
                            "assertion": (
                                f"{assertion['po_id']} {assertion['pato_id']} "
                                f"{'|'.join(assertion.get('value_terms') or [])} "
                                f"outer={scope['outer_bearer']} cue={scope['scope_text']!r} "
                                f"gate={gate.status}"
                            ),
                        }
                    )
                if added_any:
                    clears.append({name: span[name] for name in ("start", "end", "reason", "surface_form")})
            if add_assertions:
                out.write(
                    json.dumps(
                        {
                            "key": dict(entry["key"]),
                            "add_source_statements": list(add_statements.values()),
                            "add_assertions": add_assertions,
                            "remove_unresolved": clears,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                lines += 1
    if found != len(wanted):
        raise ValueError(f"{len(wanted) - found} candidate keys not found in {base}")
    rng = random.Random(seed)
    reviewed = set()
    for path in sorted(out_dir.glob("sample-review-round*.tsv")):
        with path.open(encoding="utf-8", newline="") as handle:
            reviewed.update((row["key"], row["span"]) for row in csv.DictReader(handle, delimiter="\t"))
    pool = [row for row in audit if (row["key"], row["span"]) not in reviewed]
    sample = rng.sample(pool, min(sample_size, len(pool)))
    with (out_dir / "sample-review-draft.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["span", "window", "assertion", "verdict", "note", "key"])
        for row in sample:
            writer.writerow(
                [row["span"], row["window"].replace("\t", " ").replace("\n", " "),
                 row["assertion"], "", "", row["key"]]
            )
    report = {
        "base": str(base),
        "delta": str(delta_path),
        "delta_lines": lines,
        "counts": dict(sorted(counts.items())),
        "residual_examples": residual_examples,
        "sample_size": len(sample),
        "seed": seed,
    }
    (out_dir / "build-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("base", type=Path)
    parser.add_argument("--out-dir", type=Path, default=ROOT / "surface_scope")
    parser.add_argument("--sample-size", type=int, default=120)
    parser.add_argument("--seed", type=int, default=20260923)
    args = parser.parse_args()
    report = build(args.base, args.out_dir, sample_size=args.sample_size, seed=args.seed)
    print(json.dumps({k: report[k] for k in ("delta_lines", "counts")}, indent=1))


if __name__ == "__main__":
    main()
