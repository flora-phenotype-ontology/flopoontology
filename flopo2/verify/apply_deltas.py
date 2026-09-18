"""Apply an ordered, precedence-resolved list of segment deltas to a gated corpus stage.

Every recovery, tie-break and correction campaign writes a *delta*: one JSON line per touched
segment::

    {"key": {"source", "source_id", "source_segment_index", "taxon", "organ",
             "char_start", "char_end"},
     "add_source_statements": [...], "add_assertions": [...],
     "remove_unresolved": [{"start", "end", "reason", "surface_form"}],
     # correction deltas only:
     "remove_assertions": [{"source_statement_id", "po_id", "pato_id",
                            "source_start", "source_end"}],
     "add_unresolved": [{"start", "end", "reason", "surface_form", ...}],
     # provenance-only enrichment of an existing assertion (FAC identity must not change):
     "update_assertions": [{"source_statement_id", "po_id", "pato_id", "source_start",
                            "source_end", "set": {"value_operands": [...]},
                            "add_mapping_provenance": ["..."]}]}

This module replaces the per-module ``apply`` helpers with one fail-closed applier driven by a
JSON *manifest*::

    {"base": "stage22.jsonl",
     "deltas": [{"name": "...", "path": "...", "kind": "correction|tiebreak|recovery",
                 "audit": {"correct": 160, "n": 160},          # recovery only
                 "admission": {"match": {...}, "provenance": ["..."]}}]}   # optional

Precedence (documented, deterministic)
    1. ``correction`` deltas, in manifest order;
    2. ``tiebreak`` admissions, in manifest order;
    3. ``recovery`` categories by measured precision: the 95% Wilson lower bound of their seeded
       audit (``audit.correct`` of ``audit.n``; unsure verdicts count as incorrect), then the
       point estimate, then manifest order.

Deltas are applied in precedence order.  Before anything is written, every pair of deltas that
touch the same segment is compared.  Two added assertions whose source spans overlap are

* a ``duplicate`` when their normalized signatures (bearer, attribute, operator, value terms,
  qualitative relation, negation) are identical;
* a ``conflict_shared_span`` when they differ and both deltas clear an overlapping unresolved
  span;
* a ``conflict_same_attribute`` when they differ but share bearer and attribute.

A lower-precedence assertion that overlaps a span a correction restored is a
``conflict_correction_restored``.  Overlapping assertions about different attributes of
disjoint spans (``bark red-brown, rough or smooth``) are compatible and are not reported.

Every duplicate or conflict is written to the conflicts TSV and resolved in favour of the
higher-precedence delta: the losing assertion is dropped, and the loser keeps only the span
clears still covered by one of its surviving assertions and not already cleared by the winner.
Nothing is resolved silently.

After resolution the applier fails on: a delta key that matches no segment, a duplicate key within
one delta, removal of an unresolved span that is not present, removal of an assertion that does
not match exactly one existing assertion, an assertion that references an unknown source
statement, a statement id reused for different text, and a restored span that does not match the
segment text or is already unresolved.

``admission`` stamps ``mapping_provenance`` entries (for example
``admission:deterministic_audited_rule:<rule>:wilson_lb_<x>``) on the delta's assertions that
match every field of ``match`` (``extractor``, ``gate_status``, ``interpretation``).

``merge-held`` combines a module's ``--admit`` delta with its review-held delta: relations the
admitted run retained (for example because of a clause-level disjunction) keep their held
records and review status, so admission never loses a recovered span.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

DELTA_KEY_FIELDS = (
    "source",
    "source_id",
    "source_segment_index",
    "taxon",
    "organ",
    "char_start",
    "char_end",
)
REMOVE_FIELDS = ("source_statement_id", "po_id", "pato_id", "source_start", "source_end")
# Fields an ``update_assertions`` entry may set.  They are provenance/annotation fields that never
# enter the FAC signature (schema extensions E2/E3), so an update cannot change FAC identity.
UPDATABLE_FIELDS = frozenset({"value_operands", "bearer_scope"})
KIND_RANK = {"correction": 0, "tiebreak": 1, "recovery": 2}
CONFLICT_FIELDS = (
    "source",
    "source_id",
    "source_segment_index",
    "organ",
    "char_start",
    "char_end",
    "conflict",
    "resolution",
    "winner_delta",
    "winner_signature",
    "winner_span",
    "winner_text",
    "loser_delta",
    "loser_signature",
    "loser_span",
    "loser_text",
    "contested_spans",
)


class DeltaError(ValueError):
    """A delta cannot be applied exactly as written."""


# ---------------------------------------------------------------------------------------------
# Helpers


def _rows(path: Path) -> Iterator[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def segment_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(name) for name in DELTA_KEY_FIELDS)


def wilson_lower_bound(successes: int, total: int, z: float = 1.959964) -> float:
    if total <= 0:
        return 0.0
    p = successes / total
    denominator = 1 + z * z / total
    centre = p + z * z / (2 * total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total))
    return (centre - half) / denominator


def assertion_identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("source_statement_id"),
        row.get("po_id"),
        row.get("pato_id"),
        int(row.get("source_start", -1)),
        int(row.get("source_end", -1)),
    )


def assertion_signature(row: dict[str, Any]) -> str:
    relation = row.get("qualitative_value_relation") or {}
    parts = [
        str(row.get("po_id", "")),
        str(row.get("pato_id", "")),
        str(row.get("value_operator", "atomic") or "atomic"),
        "&".join(sorted(str(term) for term in row.get("value_terms", []) or [])),
    ]
    if relation:
        parts.append(
            f"{relation.get('interpretation')}:{relation.get('from_value')}>{relation.get('to_value')}"
        )
    if row.get("negated"):
        parts.append("negated")
    return "|".join(parts)


def _span(row: dict[str, Any]) -> tuple[int, int]:
    return int(row["start"]), int(row["end"])


def _span_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return int(row["start"]), int(row["end"]), row.get("reason"), row.get("surface_form")


def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _source_range(assertion: dict[str, Any]) -> tuple[int, int]:
    return int(assertion["source_start"]), int(assertion["source_end"])


def _covers(assertion: dict[str, Any], span: dict[str, Any]) -> bool:
    start, end = _source_range(assertion)
    return start <= int(span["start"]) and int(span["end"]) <= end


# ---------------------------------------------------------------------------------------------
# Manifest


@dataclass
class DeltaSpec:
    name: str
    path: Path
    kind: str
    order: int
    audit: dict[str, int] | None = None
    admission: dict[str, Any] | None = None
    lines: dict[tuple[Any, ...], dict[str, Any]] = field(default_factory=dict)

    @property
    def wilson_lb(self) -> float | None:
        if not self.audit:
            return None
        return wilson_lower_bound(int(self.audit["correct"]), int(self.audit["n"]))

    @property
    def precision(self) -> float | None:
        if not self.audit:
            return None
        return int(self.audit["correct"]) / int(self.audit["n"])

    def precedence(self) -> tuple[Any, ...]:
        if self.kind == "recovery":
            return (KIND_RANK[self.kind], -(self.wilson_lb or 0.0), -(self.precision or 0.0), self.order)
        return (KIND_RANK[self.kind], 0.0, 0.0, self.order)


def load_manifest(path: Path) -> tuple[Path, list[DeltaSpec]]:
    """Return the base path and the delta specs of ``path`` in precedence order."""

    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    root = Path(path).parent
    specs = []
    names = set()
    for order, entry in enumerate(manifest["deltas"]):
        kind = entry.get("kind")
        if kind not in KIND_RANK:
            raise DeltaError(f"{entry.get('name')}: unknown delta kind {kind!r}")
        if kind == "recovery" and not entry.get("audit"):
            raise DeltaError(f"{entry['name']}: recovery deltas need an audit to rank precision")
        if entry["name"] in names:
            raise DeltaError(f"duplicate delta name {entry['name']}")
        names.add(entry["name"])
        delta_path = Path(entry["path"])
        specs.append(
            DeltaSpec(
                name=entry["name"],
                path=delta_path if delta_path.is_absolute() else _resolve(root, delta_path),
                kind=kind,
                order=order,
                audit=entry.get("audit"),
                admission=entry.get("admission"),
            )
        )
    base = Path(manifest["base"])
    return (base if base.is_absolute() else _resolve(root, base)), sorted(
        specs, key=lambda spec: spec.precedence()
    )


def _resolve(root: Path, path: Path) -> Path:
    """Resolve manifest paths against the working directory first, then the manifest folder."""

    return path if path.exists() else root / path


def read_delta(spec: DeltaSpec) -> None:
    for line in _rows(spec.path):
        key = segment_key(line["key"])
        if key in spec.lines:
            raise DeltaError(f"{spec.name}: duplicate delta key {key}")
        for assertion in line.get("add_assertions", []) or []:
            for name in ("source_start", "source_end", "po_id", "pato_id"):
                if name not in assertion:
                    raise DeltaError(f"{spec.name}: {key}: added assertion lacks {name}")
        spec.lines[key] = line


# ---------------------------------------------------------------------------------------------
# Admission provenance


def _admission_matches(assertion: dict[str, Any], match: dict[str, Any]) -> bool:
    for name, expected in match.items():
        if name == "extractor":
            actual = assertion.get("extractor")
        elif name == "gate_status":
            actual = (assertion.get("gate") or {}).get("status")
        elif name == "interpretation":
            actual = (assertion.get("qualitative_value_relation") or {}).get("interpretation")
        else:
            raise DeltaError(f"unknown admission match field {name!r}")
        if actual != expected:
            return False
    return True


def stamp_admission(spec: DeltaSpec) -> int:
    """Add the spec's admission provenance to matching assertions; return how many matched."""

    if not spec.admission:
        return 0
    match = spec.admission.get("match") or {}
    notes = list(spec.admission.get("provenance") or [])
    if not notes:
        raise DeltaError(f"{spec.name}: admission lacks provenance entries")
    stamped = 0
    for line in spec.lines.values():
        for assertion in line.get("add_assertions", []) or []:
            if not _admission_matches(assertion, match):
                continue
            provenance = list(assertion.get("mapping_provenance", []) or [])
            provenance.extend(note for note in notes if note not in provenance)
            assertion["mapping_provenance"] = provenance
            stamped += 1
    return stamped


# ---------------------------------------------------------------------------------------------
# Conflict resolution


def _conflict_row(
    key: tuple[Any, ...],
    kind: str,
    winner: DeltaSpec,
    won: dict[str, Any] | None,
    loser: DeltaSpec,
    lost: dict[str, Any],
    contested: list[dict[str, Any]],
) -> dict[str, Any]:
    row = dict(zip(DELTA_KEY_FIELDS, key))
    row.pop("taxon", None)
    row.update(
        {
            "conflict": kind,
            "resolution": f"kept:{winner.name};dropped:{loser.name}",
            "winner_delta": winner.name,
            "winner_signature": assertion_signature(won) if won else "",
            "winner_span": f"{won['source_start']}-{won['source_end']}" if won else "",
            "winner_text": (won or {}).get("source_text", ""),
            "loser_delta": loser.name,
            "loser_signature": assertion_signature(lost),
            "loser_span": f"{lost['source_start']}-{lost['source_end']}",
            "loser_text": lost.get("source_text", ""),
            "contested_spans": ";".join(
                f"{span['start']}-{span['end']}:{span.get('reason', '')}:{span.get('surface_form', '')}"
                for span in contested
            ),
        }
    )
    return row


def resolve_conflicts(specs: list[DeltaSpec]) -> list[dict[str, Any]]:
    """Prune lower-precedence assertions that clash with a higher-precedence delta.

    ``specs`` must be in precedence order.  Mutates the delta lines in place and returns one
    conflict row per dropped assertion.
    """

    conflicts: list[dict[str, Any]] = []
    touching: dict[tuple[Any, ...], list[DeltaSpec]] = defaultdict(list)
    for spec in specs:
        for key in spec.lines:
            touching[key].append(spec)
    for key, owners in touching.items():
        if len(owners) < 2:
            continue
        # Claims already made by higher-precedence deltas on this segment.
        kept: list[tuple[DeltaSpec, dict[str, Any], list[dict[str, Any]]]] = []
        restored: list[tuple[DeltaSpec, dict[str, Any]]] = []
        cleared: list[tuple[DeltaSpec, dict[str, Any]]] = []
        for spec in owners:
            line = spec.lines[key]
            survivors = []
            for assertion in line.get("add_assertions", []) or []:
                own_spans = [
                    span for span in line.get("remove_unresolved", []) or [] if _covers(assertion, span)
                ]
                verdict = None
                for winner, won, won_spans in kept:
                    if not _overlaps(_source_range(won), _source_range(assertion)):
                        continue
                    contested = [
                        span
                        for span in own_spans
                        if any(_overlaps(_span(span), _span(other)) for other in won_spans)
                    ]
                    if assertion_signature(won) == assertion_signature(assertion):
                        verdict = ("duplicate", winner, won, contested)
                    elif contested:
                        verdict = ("conflict_shared_span", winner, won, contested)
                    elif (won.get("po_id"), won.get("pato_id")) == (
                        assertion.get("po_id"),
                        assertion.get("pato_id"),
                    ):
                        verdict = ("conflict_same_attribute", winner, won, contested)
                    if verdict:
                        break
                if verdict is None:
                    # A later correction that explicitly clears a restored span re-admits it
                    # (e.g. re-bearing a corrected quality on a newly approved bearer class).
                    readmitted = (
                        {_span_key(span) for span in own_spans} if spec.kind == "correction" else set()
                    )
                    for winner, span in restored:
                        if _span_key(span) in readmitted:
                            continue
                        if _overlaps(_span(span), _source_range(assertion)):
                            verdict = ("conflict_correction_restored", winner, None, [span])
                            break
                if verdict is None:
                    survivors.append((assertion, own_spans))
                    continue
                kind, winner, won, contested = verdict
                conflicts.append(_conflict_row(key, kind, winner, won, spec, assertion, contested))
            if len(survivors) != len(line.get("add_assertions", []) or []):
                _prune_line(line, [assertion for assertion, _ in survivors], cleared)
            for assertion, own_spans in survivors:
                kept.append((spec, assertion, own_spans))
            restored.extend((spec, span) for span in line.get("add_unresolved", []) or [])
            cleared.extend((spec, span) for span in line.get("remove_unresolved", []) or [])
    return conflicts


def _prune_line(
    line: dict[str, Any],
    survivors: list[dict[str, Any]],
    cleared: list[tuple[DeltaSpec, dict[str, Any]]],
) -> None:
    """Keep ``survivors`` and only the clears and statements they still justify."""

    line["add_assertions"] = survivors
    already = {_span_key(span) for _, span in cleared}
    line["remove_unresolved"] = [
        span
        for span in line.get("remove_unresolved", []) or []
        if any(_covers(assertion, span) for assertion in survivors)
        and _span_key(span) not in already
    ]
    referenced = {assertion.get("source_statement_id") for assertion in survivors}
    line["add_source_statements"] = [
        statement
        for statement in line.get("add_source_statements", []) or []
        if statement.get("statement_id") in referenced
    ]


# ---------------------------------------------------------------------------------------------
# Record application


def apply_line(record: dict[str, Any], line: dict[str, Any], name: str) -> dict[str, Any]:
    """Return a patched copy of ``record``; raise :class:`DeltaError` on any mismatch.

    Order: assertion removals, restored spans, statements, assertion additions, span clears.
    """

    where = f"{name}: {segment_key(record)}"
    text = str(record.get("text", "") or "")
    out = dict(record)

    assertions = list(record.get("assertions", []) or [])
    for removal in line.get("remove_assertions", []) or []:
        missing = [name_ for name_ in REMOVE_FIELDS if name_ not in removal]
        if missing:
            raise DeltaError(f"{where}: remove_assertions entry lacks {missing}")
        target = assertion_identity(removal)
        hits = [index for index, row in enumerate(assertions) if assertion_identity(row) == target]
        if len(hits) != 1:
            raise DeltaError(f"{where}: assertion to remove {target} matched {len(hits)} assertions")
        del assertions[hits[0]]

    for update in line.get("update_assertions", []) or []:
        missing = [name_ for name_ in REMOVE_FIELDS if name_ not in update]
        if missing:
            raise DeltaError(f"{where}: update_assertions entry lacks {missing}")
        fields = dict(update.get("set") or {})
        unsupported = sorted(set(fields) - UPDATABLE_FIELDS)
        if unsupported:
            raise DeltaError(f"{where}: update_assertions may not set {unsupported}")
        target = assertion_identity(update)
        hits = [index for index, row in enumerate(assertions) if assertion_identity(row) == target]
        if len(hits) != 1:
            raise DeltaError(f"{where}: assertion to update {target} matched {len(hits)} assertions")
        updated = copy.deepcopy(assertions[hits[0]])
        updated.update(fields)
        provenance = list(updated.get("mapping_provenance", []) or [])
        provenance.extend(
            note for note in update.get("add_mapping_provenance", []) or [] if note not in provenance
        )
        updated["mapping_provenance"] = provenance
        stored = str(updated.get("phenotype_class_iri", "") or "")
        if stored:
            from flopo2.annotation.qualitative import is_fac_representable
            from flopo2.owl.annotation_class import annotation_class_iri

            if not is_fac_representable(updated) or annotation_class_iri(updated) != stored:
                raise DeltaError(f"{where}: update of {target} would change its FAC identity")
        assertions[hits[0]] = updated

    unresolved = list(record.get("unresolved_spans", []) or [])
    present = {(int(span.get("start", -1)), int(span.get("end", -1)), span.get("reason")) for span in unresolved}
    for span in line.get("add_unresolved", []) or []:
        start, end = _span(span)
        if not span.get("reason") or text[start:end] != span.get("surface_form"):
            raise DeltaError(f"{where}: restored span {start}:{end} does not match the segment text")
        if (start, end, span["reason"]) in present:
            raise DeltaError(f"{where}: restored span {start}:{end} is already unresolved")
        present.add((start, end, span["reason"]))
        unresolved.append(dict(span))

    statements = list(record.get("source_statements", []) or [])
    known = {str(row.get("statement_id", "")): row for row in statements}
    for statement in line.get("add_source_statements", []) or []:
        statement_id = str(statement["statement_id"])
        start, end = int(statement["start"]), int(statement["end"])
        if text[start:end] != statement.get("verbatim_text"):
            raise DeltaError(f"{where}: statement {statement_id} does not match the segment text")
        existing = known.get(statement_id)
        if existing is not None:
            if (int(existing.get("start", -1)), int(existing.get("end", -1))) != (start, end):
                raise DeltaError(f"{where}: statement id {statement_id} reused for other text")
            continue
        statements.append(statement)
        known[statement_id] = statement

    for assertion in line.get("add_assertions", []) or []:
        if str(assertion.get("source_statement_id", "")) not in known:
            raise DeltaError(
                f"{where}: assertion references unknown statement {assertion.get('source_statement_id')}"
            )
        start, end = _source_range(assertion)
        if "source_text" in assertion and text[start:end] != assertion["source_text"]:
            raise DeltaError(f"{where}: assertion evidence does not match text at {start}:{end}")
        assertions.append(assertion)

    remove = [_span_key(span) for span in line.get("remove_unresolved", []) or []]
    if len(set(remove)) != len(remove):
        raise DeltaError(f"{where}: duplicate unresolved-span removal")
    wanted = set(remove)
    kept = []
    for span in unresolved:
        key = _span_key(span)
        if key in wanted:
            wanted.discard(key)
            continue
        kept.append(span)
    if wanted:
        raise DeltaError(f"{where}: unresolved spans to remove are not present: {sorted(wanted)}")

    out["assertions"] = assertions
    out["source_statements"] = statements
    out["unresolved_spans"] = kept
    return out


# ---------------------------------------------------------------------------------------------
# Driver


def merge(
    base: Path,
    specs: list[DeltaSpec],
    output: Path,
    conflicts_path: Path | None = None,
) -> dict[str, Any]:
    """Apply ``specs`` (already in precedence order) to ``base`` and write ``output``."""

    if Path(base).resolve() == Path(output).resolve():
        raise DeltaError("output must differ from the base stage")
    for spec in specs:
        if not spec.lines:
            read_delta(spec)
    stamped = {spec.name: stamp_admission(spec) for spec in specs}
    conflicts = resolve_conflicts(specs)
    if conflicts_path is not None:
        write_conflicts(conflicts_path, conflicts)

    pending: dict[tuple[Any, ...], list[DeltaSpec]] = defaultdict(list)
    for spec in specs:
        for key in spec.lines:
            pending[key].append(spec)
    per_delta = {
        spec.name: Counter(
            {"segments": 0, "assertions_added": 0, "assertions_removed": 0,
             "assertions_updated": 0, "spans_removed": 0, "spans_restored": 0,
             "statements_added": 0}
        )
        for spec in specs
    }
    before: Counter[str] = Counter()
    after: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    tmp = Path(str(output) + ".partial")
    try:
        with tmp.open("w", encoding="utf-8") as handle:
            for record in _rows(base):
                totals["segments"] += 1
                totals["assertions_before"] += len(record.get("assertions", []) or [])
                before.update(span.get("reason", "") for span in record.get("unresolved_spans", []) or [])
                key = segment_key(record)
                owners = pending.pop(key, [])
                touched = False
                for spec in owners:
                    line = spec.lines[key]
                    if not any(line.get(name) for name in (
                        "add_assertions", "remove_assertions", "remove_unresolved", "add_unresolved",
                        "update_assertions",
                    )):
                        continue
                    statement_count = len(record.get("source_statements", []) or [])
                    record = apply_line(record, line, spec.name)
                    counts = per_delta[spec.name]
                    counts["segments"] += 1
                    counts["assertions_added"] += len(line.get("add_assertions", []) or [])
                    counts["assertions_removed"] += len(line.get("remove_assertions", []) or [])
                    counts["assertions_updated"] += len(line.get("update_assertions", []) or [])
                    counts["spans_removed"] += len(line.get("remove_unresolved", []) or [])
                    counts["spans_restored"] += len(line.get("add_unresolved", []) or [])
                    counts["statements_added"] += (
                        len(record.get("source_statements", []) or []) - statement_count
                    )
                    touched = True
                totals["segments_patched"] += touched
                totals["assertions_after"] += len(record.get("assertions", []) or [])
                after.update(span.get("reason", "") for span in record.get("unresolved_spans", []) or [])
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if pending:
            sample = [(spec.name, key) for key, owners in list(pending.items())[:3] for spec in owners]
            raise DeltaError(f"{len(pending)} delta keys match no segment, e.g. {sample}")
        tmp.replace(output)
    finally:
        if tmp.exists():
            tmp.unlink()

    conflict_counts = Counter(row["conflict"] for row in conflicts)
    return {
        "base": str(base),
        "output": str(output),
        "precedence": [
            {
                "name": spec.name,
                "kind": spec.kind,
                "path": str(spec.path),
                "audit": spec.audit,
                "wilson_lb": round(spec.wilson_lb, 4) if spec.wilson_lb is not None else None,
                "admission_provenance_stamped": stamped[spec.name],
            }
            for spec in specs
        ],
        "per_delta": {name: dict(counts) for name, counts in per_delta.items()},
        "totals": {
            **dict(totals),
            "assertions_added": sum(c["assertions_added"] for c in per_delta.values()),
            "assertions_removed": sum(c["assertions_removed"] for c in per_delta.values()),
            "spans_removed": sum(c["spans_removed"] for c in per_delta.values()),
            "spans_restored": sum(c["spans_restored"] for c in per_delta.values()),
            "unresolved_before": sum(before.values()),
            "unresolved_after": sum(after.values()),
        },
        "unresolved_by_reason": {
            reason: {"before": before[reason], "after": after[reason], "change": after[reason] - before[reason]}
            for reason in sorted(set(before) | set(after))
        },
        "conflicts": {"total": len(conflicts), "by_kind": dict(sorted(conflict_counts.items()))},
    }


def write_conflicts(path: Path, conflicts: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONFLICT_FIELDS, delimiter="\t")
        writer.writeheader()
        for row in conflicts:
            writer.writerow(
                {name: str(row.get(name, "")).replace("\t", " ").replace("\n", " ") for name in CONFLICT_FIELDS}
            )


def merge_held(admitted_path: Path, held_path: Path, output: Path) -> dict[str, int]:
    """Union an ``--admit`` delta with the review-held delta of the same module run.

    Every admitted assertion must also be in the held delta (same identity); held assertions the
    admitted run retained are carried over with their review gate, their statements and the span
    clears they cover.
    """

    admitted = {segment_key(line["key"]): line for line in _rows(admitted_path)}
    counts = Counter()
    held_ids: set[tuple[Any, ...]] = set()
    merged: dict[tuple[Any, ...], dict[str, Any]] = {
        key: copy.deepcopy(line) for key, line in admitted.items()
    }
    for line in _rows(held_path):
        key = segment_key(line["key"])
        base = merged.get(key)
        present = {
            assertion_identity(row) for row in (base or {}).get("add_assertions", []) or []
        }
        held_ids.update((key, assertion_identity(row)) for row in line.get("add_assertions", []) or [])
        extra = [
            row for row in line.get("add_assertions", []) or [] if assertion_identity(row) not in present
        ]
        if not extra:
            continue
        if base is None:
            base = {
                "key": line["key"],
                "add_source_statements": [],
                "add_assertions": [],
                "remove_unresolved": [],
            }
            merged[key] = base
        cleared = {_span_key(span) for span in base["remove_unresolved"]}
        statements = {row["statement_id"] for row in base["add_source_statements"]}
        wanted_statements = {row.get("source_statement_id") for row in extra}
        for statement in line.get("add_source_statements", []) or []:
            if statement["statement_id"] in wanted_statements and statement["statement_id"] not in statements:
                base["add_source_statements"].append(statement)
                statements.add(statement["statement_id"])
        for span in line.get("remove_unresolved", []) or []:
            if _span_key(span) not in cleared and any(_covers(row, span) for row in extra):
                base["remove_unresolved"].append(span)
                cleared.add(_span_key(span))
                counts["held_spans_carried"] += 1
        base["add_assertions"].extend(extra)
        counts["held_assertions_carried"] += len(extra)
    for key, line in admitted.items():
        for row in line.get("add_assertions", []) or []:
            if (key, assertion_identity(row)) not in held_ids:
                raise DeltaError(f"admitted assertion {assertion_identity(row)} is absent from the held delta")
            counts["admitted_assertions"] += 1
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for line in merged.values():
            handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
    counts["segments"] = len(merged)
    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("merge", help="apply a manifest of deltas to its base stage")
    run.add_argument("manifest", type=Path)
    run.add_argument("-o", "--output", type=Path, required=True)
    run.add_argument("--conflicts", type=Path, required=True)
    run.add_argument("--report", type=Path)
    held = sub.add_parser("merge-held", help="union an --admit delta with its review-held delta")
    held.add_argument("--admitted", type=Path, required=True)
    held.add_argument("--held", type=Path, required=True)
    held.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "merge":
        base, specs = load_manifest(args.manifest)
        report = merge(base, specs, args.output, args.conflicts)
        report["manifest"] = str(args.manifest)
        report["conflicts"]["tsv"] = str(args.conflicts)
    else:
        report = merge_held(args.admitted, args.held, args.output)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if getattr(args, "report", None):
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
