"""Re-admit leaflet-borne qualities removed by the 2026-09-18 leaflet-bearer correction.

``scratchpad/flopo-claude-recovery-20260918/shape-tiebreak/correction-delta.jsonl`` removed 836
assertions whose quality belongs to a leaflet but was borne on leaf apex (PO_0020137), leaf base
(PO_0020040) or leaf lamina (PO_0020039), and restored each quality span as unresolved with
``pending_bearer`` "leaflet apex" / "leaflet base" / "leaflet lamina".  The curator has since
approved the FLOPO-local support classes leaflet apex/base/lamina (FLOPO_0986000-0986002).

For every removal this module re-asserts the *same* assertion (same quality, same source span and
statement) on the leaflet class and re-runs :func:`flopo2.verify.gates.check_assertion`.  Only
``accepted`` assertions with an ``allowed`` bearer x quality pair are emitted, as a correction
delta that clears the restored span.  Held removals are listed with their gate reasons, and the
bearer x quality pairs that block them are written as curator candidates (no pair is approved here).
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from flopo2.extract import baseline
from flopo2.extract.leaflet_context import (
    FOLIOLE_CUE,
    LEAFLET_APEX_ID,
    LEAFLET_BASE_ID,
    LEAFLET_LAMINA_ID,
    foliole_context,
)
from flopo2.extract.surface_context import surface_restriction, value_member
from flopo2.owl.annotation_class import ensure_annotation_class_iri
from flopo2.verify.apply_deltas import DELTA_KEY_FIELDS, assertion_identity
from flopo2.verify.gates import (
    Combination,
    check_assertion,
    load_catalog_ids,
    load_combinations,
    load_eq_registry,
    load_flopo_ids,
    load_pato_attribute_terms,
    load_signature_registry,
)

# pending_bearer -> (corrected PO leaf part, FLOPO leaflet part, label)
LEAFLET_TARGETS = {
    "leaflet apex": ("PO_0020137", LEAFLET_APEX_ID),
    "leaflet base": ("PO_0020040", LEAFLET_BASE_ID),
    "leaflet lamina": ("PO_0020039", LEAFLET_LAMINA_ID),
}
CORRECTION_EXTRACTOR = "leaflet_bearer_correction_v1"
DEFAULT_CORRECTION = Path(
    "scratchpad/flopo-claude-recovery-20260918/shape-tiebreak/correction-delta.jsonl"
)
CLASS_APPROVAL = (
    "curator_class_approval:curation/curator_approvals.tsv:"
    "curation/flopo_anatomy_support_classes_20260918.tsv:FLOPO_0986000-0986006:"
    "orcid_0000-0001-8149-5890:2026-09-18"
)


def _key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(name) for name in DELTA_KEY_FIELDS)


def _covers(assertion: dict[str, Any], span: dict[str, Any]) -> bool:
    return int(assertion["source_start"]) <= int(span["start"]) and int(span["end"]) <= int(
        assertion["source_end"]
    )


def pair_removals(line: dict[str, Any]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Pair each removed assertion with the span the correction restored for it."""

    removals = list(line.get("remove_assertions", []) or [])
    restored = [
        span
        for span in line.get("add_unresolved", []) or []
        if span.get("extractor") == CORRECTION_EXTRACTOR and span.get("pending_bearer") in LEAFLET_TARGETS
    ]
    if len(removals) != len(restored):
        raise ValueError(f"{line['key']}: {len(removals)} removals but {len(restored)} restored spans")
    pairs = []
    for removal, span in zip(removals, restored):
        expected_po, _flopo = LEAFLET_TARGETS[span["pending_bearer"]]
        if (
            removal["po_id"] != expected_po
            or removal["pato_id"] != span.get("candidate_pato_id")
            or not _covers(removal, span)
        ):
            raise ValueError(f"{line['key']}: removal {removal} does not match restored span {span}")
        pairs.append((removal, span))
    return pairs


class GateResources:
    def __init__(self) -> None:
        registry = Path("config/flopo_id_registry.tsv")
        self.combinations = load_combinations()
        self.registry = load_eq_registry(registry)
        self.signature_registry = load_signature_registry(registry)
        self.attribute_ids = load_pato_attribute_terms()
        self.po_ids = load_catalog_ids(Path("config/po_lexicon.tsv"))
        self.pato_ids = load_catalog_ids(Path("config/pato_lexicon.tsv"))
        self.flopo_ids = load_flopo_ids(registry)
        with Path("config/pato_lexicon.tsv").open(encoding="utf-8", newline="") as handle:
            self.pato_labels = {
                row["id"]: row.get("label", "") for row in csv.DictReader(handle, delimiter="\t")
            }

    def check(self, record: dict[str, Any], assertion: dict[str, Any], combinations=None):
        return check_assertion(
            str(record.get("text", "") or ""),
            assertion,
            self.combinations if combinations is None else combinations,
            self.registry,
            self.signature_registry,
            self.attribute_ids,
            taxon_provenance=record.get("taxon") if "taxon" in record else None,
            pato_catalog_ids=self.pato_ids,
            flopo_catalog_ids=self.flopo_ids,
            po_catalog_ids=self.po_ids,
        )


_LOBE_OR_SEGMENT = re.compile(r"(?<![\w-])(?:lobes?|lobules?|segments?|dents?|teeth|tooth)(?![\w-])", re.I)
# A lamina value whose member names a part of the lamina describes that part (``marge pubescente``,
# ``sommet à peine acuminé``, ``acumen … 2 cm de longueur``, ``nervures … dressées``).
_LAMINA_PART = re.compile(
    r"(?<![\w-])(?:marges?|margins?|bords?|bordée?s?|sommets?|apex|apices|bases?|acumen|"
    r"nervures?|nerves?|veins?|veinules?|r[ée]ticulum|midrib|ponctuations?)(?![\w-])",
    re.I,
)
_HEDGE_OR_FREQUENCY = re.compile(
    r"(?<![\w-])(?:[àa]\s+peine|rarement|rarely|parfois|sometimes|exceptionnellement|"
    r"occasionally|quelquefois|presque|nearly|almost|tant[ôo]t|either)(?![\w-])",
    re.I,
)
_PILOSITY_LABEL = re.compile(
    r"glabr|pubesc|tomentose|hairy|pilose|villous|hirsute|sericeous|velutinous|puberul|strigose|"
    r"hispid|ciliat|pubescent",
    re.I,
)
# ``suborbiculaire à largement oblong``: an atomic value that ends a range or alternative.
_RANGE_BEFORE = re.compile(r"[^\W\d_]{3,}\s+(?:[àa]|to|ou|or)\s+", re.I)
_LAMINA_NOUN = re.compile(r"(?<![\w-])(?:limbes?|laminae?|blades?)(?![\w-])", re.I)
_EXCEPTION_AFTER = re.compile(r"\s*,?\s*(?:sauf|except[ée]?|excepting|but\s+for)\b", re.I)
_ALTERNATIVE_AFTER = re.compile(r"(?<![\w-])(?:ou|or|tant[ôo]t)(?![\w-])", re.I)
_FREQUENCY = re.compile(
    r"(?<![\w-])(?:g[ée]n[ée]ralement|ordinairement|souvent|habituellement|usually|often|mostly|"
    r"generally|typically|commonly|frequently)(?![\w-])",
    re.I,
)
_CLAUSE_ALTERNATION = re.compile(r"(?<![\w-])(?:tant[ôo]t|either|soit)(?![\w-])", re.I)
# ``limbe elliptique ové``, ``limbe oblong oblancéolé``: a second outline word follows directly.
_SHAPE_WORD_AFTER = re.compile(
    r"\s+(?:ov|obov|oblanc|lanc|ellip|oblong|lin[ée]a|orbic|subul|spat|rhomb|triang|delto|falc)\w*",
    re.I,
)
_RANGE_AFTER = re.compile(r"\s+(?:[àa]|to)\s+(?:[±]\s*)?[^\W\d_]", re.I)
_SUBSET_BEFORE = re.compile(
    r"(?<![\w-])(?:les?\s+plus|la\s+plus|the\s+(?:longest|largest|shortest|smallest|lowest|upper|lower))"
    r"(?![\w-])",
    re.I,
)
_LAMINA_HEAD = re.compile(r"(?<![\w-])(?<!du\s)(?<!de\sla\s)(?<!des\s)(?:limbes?|laminae?|blades?)(?![\w-])", re.I)
_TIP_PART = re.compile(r"(?<![\w-])(?:acumens?|pointes?|mucrons?|apiculus)(?![\w-])", re.I)
_MEMBER_INITIAL_LAMINA = re.compile(
    r"(?:^\s*|[;:.,]\s*|(?<![\w-])[àa]\s+)(?:limbes?|laminae?|blades?)(?![\w-])", re.I
)
_DOTS_AFTER = re.compile(r"\s*(?:dots?|spots?|points?|ponctuations?|taches?|glands?)\b", re.I)
# Obtuse/acute on a lamina clause usually describe its base or apex (``atténué vers la base, ± obtus,
# à sommet aigu``); the lamina itself is not obtuse.
APEX_OR_BASE_SHAPES = frozenset({"PATO_0001935", "PATO_0000389", "PATO_0001985"})
ATTACHMENT_QUALITIES = frozenset({"PATO_0001436"})  # sessile: borne by the leaflet, not its lamina


def _surface_value(pato_id: str, label: str) -> bool:
    return pato_id in baseline.COLOR_PATO_IDS or bool(_PILOSITY_LABEL.search(label or ""))


def readmit_guard(
    text: str,
    span: dict[str, Any],
    pato_id: str,
    *,
    lamina: bool = True,
    quality_label: str = "",
    atomic: bool = True,
    frequency: str = "unspecified",
) -> str:
    """Reasons the original leaf-part assertion was itself unsafe to re-bear on the leaflet part."""

    start, end = int(span["start"]), int(span["end"])
    if not atomic:
        # One-of unions and qualitative relations were not re-checked for completeness
        # (``limbe ovale, oblong ou elliptique`` drops ``ovale``).
        return "non_atomic_value"
    if surface_restriction(text, start, end):
        return "surface_restricted_value"
    left, right = value_member(text, start, end)
    if _LOBE_OR_SEGMENT.search(text, left, right):
        return "lobe_or_segment_member"
    if _HEDGE_OR_FREQUENCY.search(text, left, start):
        return "hedge_or_frequency_before_value"
    if (frequency or "unspecified") == "unspecified" and _FREQUENCY.search(text, left, start):
        return "frequency_not_recorded"
    clause_start = max(text.rfind(";", 0, start), text.rfind(".", 0, start)) + 1
    if _CLAUSE_ALTERNATION.search(text, clause_start, start):
        return "clause_level_alternation"
    if _RANGE_AFTER.match(text, end):
        return "range_after_value"
    if _SUBSET_BEFORE.search(text, left, start):
        return "subset_before_value"
    if _SHAPE_WORD_AFTER.match(text, end):
        return "compound_outline_after_value"
    if _RANGE_BEFORE.search(text, left, start):
        return "range_or_alternative_before_value"
    clause_end = min((i for i in (text.find(";", end), text.find(".", end)) if i >= 0), default=len(text))
    if _ALTERNATIVE_AFTER.search(text, end, clause_end):
        next_end = text.find(",", right + 1)
        window_end = min(clause_end, next_end if next_end >= 0 else clause_end)
        if _ALTERNATIVE_AFTER.search(text, end, window_end):
            # ``lamina elliptic, cuneate-obovate or almost orbicular``: the value opens a list of
            # alternatives.
            return "alternative_after_value"
    if _EXCEPTION_AFTER.match(text, right):
        return "exception_after_value"
    if not lamina:
        return ""
    if not foliole_context(text, start):
        # Only the foliol* cue is reliable for laminas (608/610 leaflet in the lamina review);
        # pinna/pinnule/segment/leaflet cues mix fern fronds, subsets and dissected leaves.
        return "lamina_without_foliole_cue"
    cue_end = [match.end() for match in FOLIOLE_CUE.finditer(text, 0, start)][-1]
    heads = [match.end() for match in _LAMINA_HEAD.finditer(text, cue_end, start)]
    if not heads:
        # ``Folioles …, 12-20 cm long`` or ``… du limbe …, longues de``: the leaflet itself is the
        # subject, not its lamina.
        return "leaflet_subject_not_lamina"
    if _TIP_PART.search(text, heads[-1], start):
        # ``limbe … acumen de 1 cm de largeur à la base, 2 cm de longueur``.
        return "tip_part_since_lamina_head"
    if pato_id in ATTACHMENT_QUALITIES:
        return "attachment_quality_on_leaflet_part"
    if pato_id in APEX_OR_BASE_SHAPES:
        return "apex_or_base_shape_on_lamina"
    if _DOTS_AFTER.match(text, end) or (start > 0 and text[start - 1] in "(" or text[max(0, start - 2):start] == "( "):
        return "value_of_dots_or_parenthetical"
    clause_start = max(text.rfind(";", 0, start), text.rfind(".", 0, start)) + 1
    if not _MEMBER_INITIAL_LAMINA.search(text[clause_start:start]):
        return "lamina_not_clause_subject"
    if _LAMINA_PART.search(text, left, right):
        return "lamina_part_member"
    if _surface_value(pato_id, quality_label):
        # ``vert très foncé, luisant en dessus, vert clair en dessous``: the next member restricts
        # the surface this colour or pilosity value belongs to.
        next_left, next_right = value_member(text, right + 1, right + 1)
        if right < len(text) and text[right] == "," and surface_restriction(
            text, next_left, next_right
        ):
            return "surface_restricted_next_member"
    return ""


def readmit_assertion(
    original: dict[str, Any], span: dict[str, Any], correction_path: str
) -> dict[str, Any]:
    """Return ``original`` re-borne on the FLOPO leaflet part, without a gate decision."""

    old_po, new_po = LEAFLET_TARGETS[span["pending_bearer"]]
    assertion = copy.deepcopy(original)
    assertion["po_id"] = new_po
    assertion.pop("gate", None)
    assertion.pop("phenotype_class_iri", None)
    composition = assertion.get("composition")
    if isinstance(composition, dict) and "entity_label" in composition:
        composition["entity_label"] = span["pending_bearer"]
    assertion["mapping_provenance"] = [
        *(assertion.get("mapping_provenance", []) or []),
        f"leaflet_readmission:{old_po}->{new_po}",
        f"leaflet_correction:{correction_path}:{CORRECTION_EXTRACTOR}",
        CLASS_APPROVAL,
    ]
    return assertion


def build(
    stage: Path,
    correction: Path,
    out_dir: Path,
    *,
    resources: GateResources | None = None,
) -> dict[str, Any]:
    resources = resources or GateResources()
    wanted: dict[tuple[Any, ...], dict[str, Any]] = {}
    for raw in correction.open(encoding="utf-8"):
        if raw.strip():
            line = json.loads(raw)
            wanted[_key(line["key"])] = line
    out_dir.mkdir(parents=True, exist_ok=True)
    delta_rows: list[dict[str, Any]] = []
    held_rows: list[dict[str, Any]] = []
    pair_counts: dict[tuple[str, str], dict[str, Any]] = {}
    counts: Counter[str] = Counter()
    found = 0
    for raw in stage.open(encoding="utf-8"):
        record = json.loads(raw)
        line = wanted.get(_key(record))
        if line is None:
            continue
        found += 1
        existing = {assertion_identity(row): row for row in record.get("assertions", []) or []}
        statements = {row.get("statement_id") for row in record.get("source_statements", []) or []}
        add_assertions, clears = [], []
        for removal, span in pair_removals(line):
            counts["removed"] += 1
            original = existing.get(assertion_identity(removal))
            if original is None:
                raise ValueError(f"{line['key']}: removed assertion not found in stage: {removal}")
            if original.get("source_statement_id") not in statements:
                raise ValueError(f"{line['key']}: statement missing for {removal}")
            assertion = readmit_assertion(original, span, str(correction))
            guard = readmit_guard(
                str(record.get("text", "") or ""),
                span,
                removal["pato_id"],
                lamina=span["pending_bearer"] == "leaflet lamina",
                quality_label=resources.pato_labels.get(removal["pato_id"], ""),
                atomic=(original.get("value_operator") or "atomic") == "atomic"
                and not original.get("qualitative_value_relation"),
                frequency=str(original.get("frequency_qualifier") or "unspecified"),
            )
            if guard:
                counts[f"guard:{guard}"] += 1
                held_rows.append(
                    {
                        "source": record.get("source"),
                        "source_id": record.get("source_id"),
                        "source_segment_index": record.get("source_segment_index"),
                        "taxon": record.get("taxon"),
                        "pending_bearer": span["pending_bearer"],
                        "po_id": assertion["po_id"],
                        "pato_id": removal["pato_id"],
                        "source_start": removal["source_start"],
                        "source_end": removal["source_end"],
                        "source_text": original.get("source_text", ""),
                        "gate_status": "guard",
                        "gate_reasons": guard,
                        "passes_if_pair_allowed": "false",
                    }
                )
                continue
            gate = resources.check(record, assertion)
            new_po = assertion["po_id"]
            if gate.status == "accepted" and gate.po_pato_status == "allowed":
                assertion["gate"] = asdict(gate)
                if original.get("phenotype_class_iri"):
                    ensure_annotation_class_iri(assertion)
                add_assertions.append(assertion)
                clears.append({name: span[name] for name in ("start", "end", "reason", "surface_form")})
                counts[f"readmitted:{span['pending_bearer']}"] += 1
                continue
            # Would the only obstacle be the missing bearer x quality pair?  Evaluate as if the
            # curator approved the pair, for the curator candidate list only.
            leaf_pair = resources.combinations.get((removal["po_id"], removal["pato_id"]))
            hypothetical = dict(resources.combinations)
            hypothetical[(new_po, removal["pato_id"])] = Combination(
                status="allowed", source="curator_review_hypothetical"
            )
            would = resources.check(record, assertion, hypothetical)
            pair_only = would.status == "accepted" and would.po_pato_status == "allowed"
            counts[f"held:{span['pending_bearer']}"] += 1
            counts["held_pair_only" if pair_only else "held_other_reasons"] += 1
            held_rows.append(
                {
                    "source": record.get("source"),
                    "source_id": record.get("source_id"),
                    "source_segment_index": record.get("source_segment_index"),
                    "taxon": record.get("taxon"),
                    "pending_bearer": span["pending_bearer"],
                    "po_id": new_po,
                    "pato_id": removal["pato_id"],
                    "source_start": removal["source_start"],
                    "source_end": removal["source_end"],
                    "source_text": original.get("source_text", ""),
                    "gate_status": gate.status,
                    "gate_reasons": "|".join(gate.reasons),
                    "passes_if_pair_allowed": str(pair_only).lower(),
                }
            )
            entry = pair_counts.setdefault(
                (new_po, removal["pato_id"]),
                {
                    "po_id": new_po,
                    "po_label": span["pending_bearer"],
                    "pato_id": removal["pato_id"],
                    "quality_label": (original.get("composition") or {}).get("quality_label", ""),
                    "leaf_part_pair": f"{removal['po_id']}|{removal['pato_id']}",
                    "leaf_part_pair_status": leaf_pair.status if leaf_pair else "novel",
                    "leaf_part_pair_source": leaf_pair.source if leaf_pair else "",
                    "spans": 0,
                    "spans_passing_if_pair_allowed": 0,
                    "examples": [],
                },
            )
            entry["spans"] += 1
            entry["spans_passing_if_pair_allowed"] += int(pair_only)
            if len(entry["examples"]) < 3:
                entry["examples"].append(
                    f"{record.get('source')} {record.get('source_id')}: {original.get('source_text', '')[:60]}"
                )
        if add_assertions:
            delta_rows.append(
                {
                    "key": dict(line["key"]),
                    "add_source_statements": [],
                    "add_assertions": add_assertions,
                    "remove_unresolved": clears,
                }
            )
    if found != len(wanted):
        raise ValueError(f"{len(wanted) - found} correction keys not found in {stage}")
    delta_path = out_dir / "leaflet-readmit-delta.jsonl"
    with delta_path.open("w", encoding="utf-8") as handle:
        for row in delta_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    _write_tsv(out_dir / "leaflet-readmit-held.tsv", held_rows)
    pairs = sorted(pair_counts.values(), key=lambda row: (-row["spans"], row["po_id"], row["pato_id"]))
    for row in pairs:
        row["examples"] = " || ".join(row["examples"])
    _write_tsv(out_dir / "leaflet-readmit-pair-candidates.tsv", pairs)
    by_bearer: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for row in held_rows:
        by_bearer[row["pending_bearer"]][row["gate_reasons"]] += 1
    report = {
        "stage": str(stage),
        "correction": str(correction),
        "counts": dict(sorted(counts.items())),
        "delta_lines": len(delta_rows),
        "readmitted_assertions": sum(len(row["add_assertions"]) for row in delta_rows),
        "pair_candidates": len(pairs),
        "held_by_bearer_and_gate_reasons": {k: dict(v) for k, v in sorted(by_bearer.items())},
    }
    (out_dir / "leaflet-readmit-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _write_tsv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        if not rows:
            return
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("stage", type=Path)
    parser.add_argument("--correction", type=Path, default=DEFAULT_CORRECTION)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.stage, args.correction, args.out_dir), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
