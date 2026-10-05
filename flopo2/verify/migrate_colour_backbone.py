"""Rewrite superseded colour values in an annotation corpus to the ISCC-NBS colour backbone.

On 2026-09-18 FLOPO obsoleted 103 colour classes and withdrew nine PATO colour identifiers that
had only been requested upstream.  ``config/colour_backbone_crosswalk.tsv`` maps every superseded
colour to its replacement; this module applies that mapping to a JSONL corpus.

Rules (curator-approved, encoded in the crosswalk)
    exact    the replacement is an exact reading (``eq_axiom=EquivalentTo``, ``word_scope=EXACT`` or
             a migration ``IAO:0100001`` replaced_by) -> the IRI is replaced by ``canonical_id``.
    narrow   the source word is narrower than its covering class (crimson < red) -> replaced by the
             covering class (``backbone_id``, else ``canonical_id``); the generalisation is
             entailed, so qualifiers are unchanged.
    related  "-ish" words (greenish, reddish, scarlet) -> replaced by ``backbone_id`` (else
             ``canonical_id``) and marked approximate with the schema's existing mechanism:
               * an operand (``value_operands``) or a relation endpoint (``from_operand`` /
                 ``to_operand``) gets ``value_qualifier: approximately`` plus the verbatim cue
                 (the "-ish"/"-atre" suffix, else the whole word);
               * an atomic assertion without operands gets the assertion-level
                 ``value_qualifier: approximately`` and ``modality_text`` cue;
               * a multi-term assertion without operands has its operands reconstructed from
                 ``value_text`` when the connectors split it into exactly one piece per term,
                 otherwise it falls back to the assertion-level qualifier.

Derived data is recomputed: ``gate.flopo_signature``, ``phenotype_class_iri`` (a FAC IRI is a
digest of the expression; an assertion with an approximated *operand* is not FAC-representable and
its IRI is cleared, an assertion-level ``approximately`` keeps a FAC IRI exactly as the 6,000+
existing ``approximately`` assertions do), and ``gate.flopo_iri``/``flopo_status`` (looked up by
signature in ``config/flopo_id_registry.tsv``; empty when no class exists).  No IRI is invented.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flopo2.annotation.operands import make_operand, operands_fac_representable
from flopo2.owl.annotation_class import annotation_class_iri
from flopo2.verify.gates import assertion_signature, load_signature_registry

CROSSWALK = Path("config/colour_backbone_crosswalk.tsv")
MIGRATION = Path("config/flopo_colour_backbone_migration.tsv")
REGISTRY = Path("config/flopo_id_registry.tsv")
SUPERSEDED_STATUSES = {"flopo_obsolete", "pato_withdrawn"}
PROVENANCE_PREFIX = "colour_backbone_migration:"
COLOUR_ATTRIBUTE = "PATO_0000014"  # PATO color
NON_ENTAILING = {"approximately", "nearly", "almost", "sub"}

# Morphological cue of a hue-tendency word: English "-ish", French "-atre(s)".
_SUFFIX = re.compile(r"(?:â|a)tres?$|ish$", re.IGNORECASE)
_SPLIT = re.compile(r"\s*,\s*|\s*/\s*|\s+(?:ou|or|et|and|and/or|ou bien)\s+", re.IGNORECASE)


@dataclass(frozen=True)
class Rule:
    old: str
    new: str
    kind: str  # exact | narrow | related
    label: str = ""
    fallback: bool = False  # backbone_id was empty and canonical_id was used


def _norm(value: object) -> str:
    return str(value or "").strip().replace(":", "_")


def load_rules(crosswalk: Path = CROSSWALK, migration: Path = MIGRATION) -> dict[str, Rule]:
    rules: dict[str, Rule] = {}
    with Path(crosswalk).open(encoding="utf-8", newline="") as handle:
        rows = csv.DictReader((ln for ln in handle if not ln.startswith("#")), delimiter="\t")
        for row in rows:
            if row["source_status"] not in SUPERSEDED_STATUSES:
                continue
            old = _norm(row["source_id"])
            scope = row["word_scope"]
            backbone, canonical = _norm(row["backbone_id"]), _norm(row["canonical_id"])
            if row["eq_axiom"] == "EquivalentTo" or scope == "EXACT":
                kind, new, fb = "exact", canonical or backbone, not canonical
            elif scope == "NARROW":
                kind, new, fb = "narrow", backbone or canonical, not backbone
            elif scope == "RELATED":
                kind, new, fb = "related", backbone or canonical, not backbone
            else:
                raise ValueError(f"unknown word_scope for {old}: {scope!r}")
            rules[old] = Rule(old, new, kind, row["source_label"], fb)
    if Path(migration).exists():
        with Path(migration).open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                old = _norm(row.get("flopo_id"))
                prop, target = row.get("replacement_property", ""), _norm(row.get("target"))
                if old in rules or not old or not target or row.get("action") != "obsolete":
                    continue
                kind = "exact" if prop == "IAO:0100001" else "related"
                rules[old] = Rule(old, target, kind, row.get("label", ""))
    return rules


# --------------------------------------------------------------------------- cue helpers


def _cue_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Verbatim cue inside the word at ``text[start:end]``: its -ish/-atre suffix, else the word."""

    segment = text[start:end].rstrip(" ,;.")
    end = start + len(segment)
    token_start = start + (max(segment.rfind(" "), -1) + 1)
    token = text[token_start:end]
    match = _SUFFIX.search(token)
    if match and match.start() > 0:
        return token_start + match.start(), end
    return token_start, end


def _last_token_span(text: str, start: int, end: int) -> tuple[int, int]:
    segment = text[start:end].rstrip(" ,;.")
    end = start + len(segment)
    return start + (max(segment.rfind(" "), -1) + 1), end


def _mark_operand(operand: dict[str, Any], assertion: dict[str, Any], text: str) -> str:
    """Make ``operand`` approximate; returns "marked", "already" or "conflict"."""

    top = assertion.get("value_qualifier") or "exact"
    own = operand.get("value_qualifier") or "exact"
    if own in NON_ENTAILING:
        return "already"
    if own != "exact" or (top != "exact" and top != "approximately"):
        return "conflict"
    start, end = int(operand["start"]), int(operand["end"])
    cue_start, cue_end = _cue_span(text, start, end)
    if operand.get("qualifier_text"):  # keep an existing degree/frequency cue; cover both
        cue_start = min(cue_start, int(operand["qualifier_start"]))
        cue_end = max(cue_end, int(operand["qualifier_end"]))
    operand["value_qualifier"] = "approximately"
    operand["qualifier_text"] = text[cue_start:cue_end]
    operand["qualifier_start"] = cue_start
    operand["qualifier_end"] = cue_end
    return "marked"


def _surface(assertion: dict[str, Any], text: str) -> tuple[int, int] | None:
    lo, hi = assertion.get("source_start"), assertion.get("source_end")
    if not isinstance(lo, int) or not isinstance(hi, int):
        return None
    for key in ("value_text", "raw_quality_text", "source_text"):
        surface = assertion.get(key) or ""
        if surface:
            index = text.find(surface, lo, hi)
            if index >= 0:
                return index, index + len(surface)
    return None


def _reconstruct_operands(
    assertion: dict[str, Any], text: str, values: list[str]
) -> list[dict[str, Any]] | None:
    """One operand per term from ``value_text`` split on connectors, or None when not 1:1."""

    value_text = assertion.get("value_text") or ""
    lo, hi = assertion.get("source_start"), assertion.get("source_end")
    if not value_text or not isinstance(lo, int) or not isinstance(hi, int):
        return None
    base = text.find(value_text, lo, hi)
    if base < 0 or text.find(value_text, base + 1, hi) >= 0:
        return None
    pieces, cursor = [], 0
    for sep in _SPLIT.finditer(value_text):
        pieces.append((cursor, sep.start()))
        cursor = sep.end()
    pieces.append((cursor, len(value_text)))
    pieces = [(a, b) for a, b in pieces if b > a]
    if len(pieces) != len(values):
        return None
    return [
        make_operand(i, value, text, base + a, base + b)
        for i, (value, (a, b)) in enumerate(zip(values, pieces))
    ]


# --------------------------------------------------------------------------- migration


class Migrator:
    def __init__(
        self,
        rules: dict[str, Rule],
        signature_registry: dict[str, tuple[str, bool]] | None = None,
    ) -> None:
        self.rules = rules
        self.registry = signature_registry or {}
        self.stats: dict[str, Counter] = {
            name: Counter()
            for name in (
                "by_mapping",  # old->new, occurrences
                "by_mapping_assertions",
                "by_rule",
                "by_rule_assertions",
                "by_shape",
                "approximation",
                "fac",
                "gate",
                "degenerate",
                "fallback_canonical",
            )
        }
        self.degenerate: list[dict[str, Any]] = []

    # -- value rewriting helpers
    def _map(self, old: Any, changes: list[Rule]) -> str:
        value = _norm(old)
        rule = self.rules.get(value)
        if rule is None:
            return str(old) if old is not None else old  # type: ignore[return-value]
        changes.append(rule)
        return rule.new

    def migrate_assertion(self, assertion: dict[str, Any], text: str) -> bool:
        before_has_fac = bool(assertion.get("phenotype_class_iri"))
        old_gate = dict(assertion.get("gate") or {})
        changes: list[Rule] = []
        shape = self._rewrite(assertion, text, changes)
        if not changes:
            return False
        provenance = assertion.setdefault("mapping_provenance", [])
        for rule in dict.fromkeys(changes):
            provenance.append(f"{PROVENANCE_PREFIX}{rule.old}->{rule.new}")
        self._recompute(assertion, before_has_fac, old_gate)
        seen = set()
        for rule in changes:
            self.stats["by_mapping"][f"{rule.old}->{rule.new}"] += 1
            self.stats["by_rule"][rule.kind] += 1
            if rule.fallback:
                self.stats["fallback_canonical"][f"{rule.old}->{rule.new}"] += 1
            if (rule.old, rule.new) not in seen:
                seen.add((rule.old, rule.new))
                self.stats["by_mapping_assertions"][f"{rule.old}->{rule.new}"] += 1
        for kind in {rule.kind for rule in changes}:
            self.stats["by_rule_assertions"][kind] += 1
        self.stats["by_shape"][shape] += 1
        return True

    def _rewrite(self, a: dict[str, Any], text: str, changes: list[Rule]) -> str:
        relation = a.get("qualitative_value_relation")
        if relation:
            return self._rewrite_relation(a, relation, text, changes)

        operands = a.get("value_operands") or []
        terms = list(a.get("value_terms") or [])
        original_pato_terms = bool(terms)
        pato_before = a.get("pato_id")
        pato_hit = self.rules.get(_norm(pato_before))
        if pato_hit is not None:
            if not terms and pato_hit.new.startswith("FLOPO_"):
                # ``pato_id`` must stay a PATO class: a FLOPO value is carried by value_terms
                # under the colour attribute, the encoding of every existing FLOPO colour value.
                # The term loop below maps (and records) the replacement.
                terms = [_norm(pato_before)]
                a["pato_id"] = COLOUR_ATTRIBUTE
            else:
                a["pato_id"] = self._map(pato_before, changes)
        related_old = {r.old for r in changes if r.kind == "related"}
        related_operands: list[dict[str, Any]] = []
        # The value is carried by value_terms, operands, or (atomic) pato_id.
        for operand in operands:
            hit = self.rules.get(_norm(operand.get("value")))
            if hit is not None:
                operand["value"] = self._map(operand["value"], changes)
                if hit.kind == "related":
                    related_old.add(hit.old)
                    related_operands.append(operand)
        original_terms = terms
        mapped_terms: list[str] = []
        for term in terms:
            hit = self.rules.get(_norm(term))
            mapped_terms.append(self._map(term, changes))
            if hit is not None and hit.kind == "related":
                related_old.add(hit.old)
        if mapped_terms:
            deduped = list(dict.fromkeys(mapped_terms))
            a["value_terms"] = deduped
            if len(deduped) != len(mapped_terms):
                self._collapse(a, original_terms, mapped_terms, text)
        shape = "operands" if operands else ("value_terms" if terms else "pato_id")
        if pato_hit is not None and shape == "value_terms" and not original_pato_terms:
            shape = "pato_id_to_value_terms"

        if related_old:
            shape = self._mark_related(a, text, shape, original_terms, related_operands)
        return shape

    def _collapse(
        self, a: dict[str, Any], original: list[str], mapped: list[str], text: str
    ) -> None:
        """Two terms of a one_of/all_of collapsed onto one class (e.g. red or crimson)."""

        self.stats["degenerate"]["duplicate_terms_collapsed"] += 1
        self.degenerate.append(
            {"kind": "duplicate_terms_collapsed", "terms": original, "mapped": mapped,
             "source_text": a.get("source_text")}
        )
        terms = a["value_terms"]
        if len(terms) == 1:
            a["value_operator"] = "atomic"
        operands = a.get("value_operands") or []
        if operands:
            kept: dict[str, dict[str, Any]] = {}
            for operand in operands:
                first = kept.get(operand["value"])
                if first is None:
                    kept[operand["value"]] = operand
                elif (operand.get("value_qualifier") or "exact") != "exact" and (
                    first.get("value_qualifier") or "exact"
                ) == "exact":
                    kept[operand["value"]] = {**operand, "operand_index": first["operand_index"]}
            ordered = sorted(kept.values(), key=lambda o: o["start"])
            for index, operand in enumerate(ordered):
                operand["operand_index"] = index
            a["value_operands"] = ordered

    def _mark_related(
        self, a: dict[str, Any], text: str, shape: str, original_terms: list[str],
        related_operands: list[dict[str, Any]],
    ) -> str:
        operands = a.get("value_operands") or []
        if not operands and len(original_terms) > 1 and len(a["value_terms"]) == len(original_terms):
            built = _reconstruct_operands(a, text, list(a["value_terms"]))
            if built is not None:
                a["value_operands"] = operands = built
                related_operands = [
                    op for op, term in zip(built, original_terms)
                    if getattr(self.rules.get(_norm(term)), "kind", "") == "related"
                ]
                shape = "operands_reconstructed"
        if operands:
            for operand in related_operands:
                outcome = _mark_operand(operand, a, text)
                self.stats["approximation"][f"operand_{outcome}"] += 1
                if outcome == "conflict":
                    self._unmarked(a, "operand_qualifier_conflict")
            return shape
        # assertion-level approximation (atomic, or a multi-term fallback)
        surface = _surface(a, text)
        if surface is None:
            self.stats["approximation"]["assertion_unmarked_no_surface"] += 1
            self._unmarked(a, "no_surface")
            return shape + "_unmarked"
        top = a.get("value_qualifier") or "exact"
        if top in NON_ENTAILING:
            self.stats["approximation"]["assertion_already"] += 1
            return shape
        if top != "exact":
            self._unmarked(a, "assertion_qualifier_conflict")
            return shape + "_unmarked"
        # cue of the related word: the last token of the surface (value_text names only values)
        cue_start, cue_end = _cue_span(text, *_last_token_span(text, *surface))
        if len(a.get("value_terms") or []) > 1:
            # the related word is not necessarily last; locate the suffix cue anywhere in the surface
            # prefer a suffix at a token end; otherwise keep the last-token cue
            for token in re.finditer(r"\S+", text[surface[0]:surface[1]]):
                m = _SUFFIX.search(token.group(0).rstrip(" ,;."))
                if m and m.start() > 0:
                    cue_start = surface[0] + token.start() + m.start()
                    cue_end = surface[0] + token.start() + len(token.group(0).rstrip(" ,;."))
                    break
        existing = a.get("modality_text") or ""
        if existing:
            lo = a.get("modality_start")
            hi = a.get("modality_end")
            if isinstance(lo, int) and isinstance(hi, int) and max(hi, cue_end) - min(lo, cue_start) <= 80:
                cue_start, cue_end = min(lo, cue_start), max(hi, cue_end)
            else:
                self._unmarked(a, "modality_cue_conflict")
                return shape + "_unmarked"
        a["value_qualifier"] = "approximately"
        a["modality_text"] = text[cue_start:cue_end]
        a["modality_start"] = cue_start
        a["modality_end"] = cue_end
        self.stats["approximation"]["assertion_marked"] += 1
        return shape

    def _unmarked(self, a: dict[str, Any], reason: str) -> None:
        self.stats["degenerate"][f"approximation_unmarked:{reason}"] += 1
        self.degenerate.append(
            {"kind": f"approximation_unmarked:{reason}", "source_text": a.get("source_text"),
             "value_terms": a.get("value_terms"), "pato_id": a.get("pato_id")}
        )

    def _rewrite_relation(
        self, a: dict[str, Any], relation: dict[str, Any], text: str, changes: list[Rule]
    ) -> str:
        old_from, old_to = relation["from_value"], relation["to_value"]
        for side in ("from", "to"):
            hit = self.rules.get(_norm(relation[f"{side}_value"]))
            if hit is None:
                continue
            relation[f"{side}_value"] = self._map(relation[f"{side}_value"], changes)
            operand = relation.get(f"{side}_operand")
            if operand:
                operand["value"] = relation[f"{side}_value"]
            if hit.kind != "related":
                continue
            if not operand:
                operand = make_operand(
                    0 if side == "from" else 1,
                    relation[f"{side}_value"],
                    text,
                    relation[f"{side}_start"],
                    relation[f"{side}_end"],
                )
                relation[f"{side}_operand"] = operand
            outcome = _mark_operand(operand, a, text)
            if outcome == "conflict" and not operand.get("qualifier_text"):
                relation.pop(f"{side}_operand", None)
            self.stats["approximation"][f"endpoint_{outcome}"] += 1
            if outcome == "conflict":
                self._unmarked(a, "endpoint_qualifier_conflict")
        if _norm(relation["from_value"]) == _norm(relation["to_value"]):
            # Endpoints must be distinct; keep the original endpoints so the record stays valid
            # and report it (a curator must decide whether the relation is an atomic value).
            self.stats["degenerate"]["relation_identical_endpoints"] += 1
            self.degenerate.append(
                {"kind": "relation_identical_endpoints", "from": old_from, "to": old_to,
                 "source_text": a.get("source_text")}
            )
            for side, old in (("from", old_from), ("to", old_to)):
                relation[f"{side}_value"] = old
                relation.pop(f"{side}_operand", None)
            changes.clear()
        return "relation"

    # -- derived data
    def _recompute(self, a: dict[str, Any], had_fac: bool, old_gate: dict[str, Any]) -> None:
        gate = a.setdefault("gate", {})
        try:
            new_signature = assertion_signature(a)
        except ValueError:
            new_signature = ""
        if gate.get("flopo_signature") != new_signature:
            self.stats["gate"]["flopo_signature_changed"] += 1
        gate["flopo_signature"] = new_signature

        if a.get("qualitative_value_relation"):
            return
        if not operands_fac_representable(a):
            if had_fac:
                self.stats["fac"]["cleared_non_entailing_operand"] += 1
            a.pop("phenotype_class_iri", None)
            if gate.get("flopo_iri"):
                self.stats["gate"]["flopo_iri_cleared"] += 1
            gate["flopo_iri"] = ""
            gate["flopo_status"] = "structured_annotation_only"
            reasons = [r for r in gate.get("reasons", []) if r != "existing_flopo_deprecated"]
            gate["reasons"] = reasons
            return
        if had_fac:
            new_iri = annotation_class_iri(a)
            if new_iri != a.get("phenotype_class_iri"):
                self.stats["fac"]["recomputed_changed"] += 1
            else:
                self.stats["fac"]["recomputed_same"] += 1
            a["phenotype_class_iri"] = new_iri
        status = gate.get("flopo_status", "")
        if status in {"existing", "existing_deprecated", "new_class_candidate"}:
            hit = self.registry.get(new_signature)
            reasons = [r for r in gate.get("reasons", []) if r != "existing_flopo_deprecated"]
            if hit:
                iri, deprecated = hit
                gate["flopo_iri"] = iri
                gate["flopo_status"] = "existing_deprecated" if deprecated else "existing"
                if deprecated:
                    reasons.append("existing_flopo_deprecated")
            else:
                gate["flopo_iri"] = ""
                gate["flopo_status"] = "new_class_candidate"
            gate["reasons"] = reasons
            if gate.get("flopo_iri") != old_gate.get("flopo_iri"):
                self.stats["gate"]["flopo_iri_changed"] += 1

    def migrate_record(self, record: dict[str, Any]) -> bool:
        text = record.get("text") or ""
        changed = False
        for assertion in record.get("assertions", []) or []:
            changed |= self.migrate_assertion(assertion, text)
        return changed


def migrate_file(
    input_jsonl: Path,
    output_jsonl: Path,
    *,
    rules: dict[str, Rule] | None = None,
    registry: Path = REGISTRY,
) -> dict[str, Any]:
    rules = rules if rules is not None else load_rules()
    migrator = Migrator(rules, load_signature_registry(registry))
    records = changed_records = assertions = 0
    output_jsonl = Path(output_jsonl)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with Path(input_jsonl).open(encoding="utf-8") as source, output_jsonl.open(
        "w", encoding="utf-8"
    ) as sink:
        for line in source:
            if not line.strip():
                continue
            record = json.loads(line)
            records += 1
            assertions += len(record.get("assertions", []) or [])
            if migrator.migrate_record(record):
                changed_records += 1
                sink.write(json.dumps(record, ensure_ascii=False) + "\n")
            else:
                sink.write(line if line.endswith("\n") else line + "\n")
    stats = {name: dict(sorted(counter.items())) for name, counter in migrator.stats.items()}
    return {
        "input": str(input_jsonl),
        "output": str(output_jsonl),
        "records": records,
        "changed_records": changed_records,
        "assertions": assertions,
        "changed_assertions": sum(migrator.stats["by_shape"].values()),
        "rules_loaded": len(rules),
        **stats,
        "degenerate_cases": migrator.degenerate,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--crosswalk", type=Path, default=CROSSWALK)
    parser.add_argument("--migration", type=Path, default=MIGRATION)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    args = parser.parse_args(argv)
    report = migrate_file(
        args.input,
        args.output,
        rules=load_rules(args.crosswalk, args.migration),
        registry=args.registry,
    )
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(
        f"{report['changed_assertions']} assertions in {report['changed_records']} records migrated",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
