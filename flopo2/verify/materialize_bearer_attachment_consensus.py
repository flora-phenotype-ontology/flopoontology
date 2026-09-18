"""Materialize admitted bearer-attachment consensus items as a gated stage delta.

For every item whose 2-of-3 consensus names a bearer, the quality is re-derived from the corpus
record with the *same* deterministic code that produced the inventory (never taken from the
review), the reviewed bearer is attached, and all deterministic gates run again:

* explicit-disjunction unions: :func:`recover_claude_explicit_disjunction.find_candidate`
  (bearerless mode: operands, exhaustiveness, context cues, modality) -> ``build_assertion`` ->
  leaflet re-bearing -> :func:`gates.check_assertion` (``accepted`` only);
* missing-bearer qualities: :meth:`Recoverer.evaluate` must still retain the span for a bearer
  reason, then :meth:`Recoverer._build` re-runs negation, hedging, stage, compound, disjunction,
  transition and composite checks with the reviewed bearer and gates (``accepted``/``allowed``).

Gate-held items are written with the bearer x quality pair they would need; nothing is minted and
``config/valid_combinations.tsv`` is never edited.  Output: ``delta.jsonl`` (one line per
segment), ``materialization-held.jsonl``, ``needed-pairs.tsv`` and a report.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any

from flopo2.annotation.provenance import ensure_source_statements
from flopo2.extract import baseline
from flopo2.extract.leaflet_context import leaflet_bearer
from flopo2.owl.annotation_class import ensure_annotation_class_iri
from flopo2.review.bearer_attachment_consensus import ADMISSION_RULE
from flopo2.review.bearer_attachment_inventory import MISSING_REASONS, iter_jsonl
from flopo2.verify import recover_claude_explicit_disjunction as disj
from flopo2.verify.gates import check_assertion
from flopo2.verify.recover_claude_missing_bearer import Bearer, Recoverer

EXTRACTOR = "bearer_attachment_review_v1"
CAMPAIGN = "flopo-bearer-review-20260918"
KEY_FIELDS = ("source", "source_id", "source_segment_index", "taxon", "organ", "char_start", "char_end")


def _key(row: dict[str, Any]) -> tuple:
    return tuple(row.get(name) for name in KEY_FIELDS)


def choose_mention(item: dict[str, Any], bearer_id: str) -> dict[str, Any]:
    """The runner evidence for the chosen bearer: nearest verbatim mention before the value,
    else any verbatim mention, else the (non-verbatim) record heading."""

    candidate = next(c for c in item["candidates"] if c["bearer_id"] == bearer_id)
    verbatim = [e for e in candidate["evidence"] if e.get("start") is not None]
    before = [e for e in verbatim if e["end"] <= item["value_start"]]
    if before:
        return max(before, key=lambda e: e["start"])
    if verbatim:
        return min(verbatim, key=lambda e: e["start"])
    return candidate["evidence"][0]


def _review_provenance(item: dict[str, Any], decision: dict[str, Any], mention: dict[str, Any]) -> list[str]:
    return [
        f"bearer_attachment_review:{CAMPAIGN}",
        f"bearer_attachment_item:{item['item_id']}",
        f"admission:{ADMISSION_RULE}",
        *(f"bearer_attachment_reviewer:{reviewer}" for reviewer in decision["agreeing_reviewers"]),
        f"bearer_attachment_signature:{decision['signature_sha256']}",
        f"bearer_evidence:{mention['basis']} {mention['surface']!r}"
        + (f" [{mention['start']},{mention['end']})" if mention.get("start") is not None else " (non-verbatim heading)"),
        "machine_review_provenance_not_curator_approval",
    ]


class Materializer:
    def __init__(self) -> None:
        self.gates = disj.GateContext.load()
        self.recoverer = Recoverer.from_config()

    # -------------------------------------------------------------- explicit disjunction
    def union_assertion(
        self, record: dict[str, Any], item: dict[str, Any], decision: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None]:
        text = str(record.get("text", "") or "")
        span = item["spans"][0]
        union, why = disj.find_candidate(record, span["start"], span["end"], bearerless=True)
        if union is None:
            return None, f"union_not_rederived:{why}", None
        if (union.start, union.end) != (item["value_start"], item["value_end"]) or [
            op.pato_id for op in union.operands
        ] != item["quality"]["value_terms"]:
            return None, "union_drift", None
        if disj._overlaps_existing(record, union):
            return None, "overlaps_existing_assertion", None
        mention = choose_mention(item, decision["bearer_id"])
        if mention.get("start") is None:
            union.bearer_method = "organ_heading"
            union.bearer_start = union.bearer_end = union.start
        else:
            union.bearer_method = "reviewed_bearer_attachment"
            union.bearer_start, union.bearer_end = mention["start"], mention["end"]
        union.bearer_po = decision["bearer_id"]
        union.bearer_text = mention["surface"]
        assertion = disj.build_assertion(record, union)
        leaflet_part = leaflet_bearer(assertion["po_id"], text, union.start)
        if leaflet_part != assertion["po_id"]:
            assertion["mapping_provenance"].append(
                f"leaflet_context_bearer:{assertion['po_id']}->{leaflet_part}"
            )
            assertion["po_id"] = leaflet_part
        assertion["extractor"] = EXTRACTOR
        assertion["mapping_provenance"].extend(_review_provenance(item, decision, mention))
        assertion["composition"]["reasons"] = [ADMISSION_RULE]
        gate = check_assertion(
            text,
            assertion,
            self.gates.combinations,
            self.gates.registry,
            self.gates.signature_registry,
            self.gates.attribute_ids,
            taxon_provenance=record.get("taxon") if "taxon" in record else None,
            pato_catalog_ids=self.gates.pato_ids,
            flopo_catalog_ids=self.gates.flopo_ids,
            po_catalog_ids=self.gates.po_ids,
        )
        if gate.status != "accepted":
            return None, f"gate_{gate.status}:{';'.join(gate.reasons)}", assertion
        assertion["gate"] = asdict(gate)
        assertion["gate"]["assertion_index"] = len(record.get("assertions", []) or [])
        ensure_annotation_class_iri(assertion)
        return assertion, "", assertion

    # -------------------------------------------------------------- missing bearer
    def quality_assertion(
        self, record: dict[str, Any], item: dict[str, Any], decision: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, str, dict[str, Any] | None]:
        text = str(record.get("text", "") or "")
        target = item["spans"][0]
        span = next(
            (
                s for s in record.get("unresolved_spans", []) or []
                if (s.get("start"), s.get("end"), s.get("reason"))
                == (target["start"], target["end"], target["reason"])
            ),
            None,
        )
        if span is None:
            return None, "span_not_present", None
        assertion, reason, _ = self.recoverer.evaluate(record, span)
        if assertion is not None or reason not in MISSING_REASONS:
            return None, f"span_no_longer_bearer_only:{reason or 'recovered_deterministically'}", None
        mention = choose_mention(item, decision["bearer_id"])
        verbatim = mention.get("start") is not None
        rule = "record_heading"
        if verbatim:
            rule = "semicolon_carry_over" if mention["start"] < item["value_start"] else "clause_head"
        bearer = Bearer(
            rule=rule,
            po_id=decision["bearer_id"],
            head_id="bearer_attachment_review",
            surface=mention["surface"],
            start=mention.get("start"),
            end=mention.get("end"),
            category_in_head=False,
        )
        clause, clause_start = baseline._clause_at(text, int(span["start"]))
        built, why, _ = self.recoverer._build(
            record, span, bearer, clause, clause_start, clause_start + len(clause)
        )
        if built is None:
            return None, f"deterministic_check:{why}", None
        built["extractor"] = EXTRACTOR
        # Replace the recovery-rule provenance with the review provenance (the bearer basis and
        # leaflet re-bearing entries are kept).
        kept = [
            entry for entry in built["mapping_provenance"]
            if entry.startswith(("leaflet_context_bearer:", "bearer_basis:"))
        ]
        built["mapping_provenance"] = [
            "reviewed_bearer_attachment:" + ("verbatim_mention" if verbatim else "record_heading"),
            *kept,
            *_review_provenance(item, decision, mention),
        ]
        built["composition"]["reasons"] = [ADMISSION_RULE]
        if "_held_gate" in built:
            held = built.pop("_held_gate")
            return None, f"gate_{held['status']}:{';'.join(held['reasons'])}", built
        return built, "", built


def materialize(
    stage: Path, inventory: Path, consensus: Path, out_dir: Path
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    items = {row["item_id"]: row for row in iter_jsonl(inventory)}
    decisions = {
        row["item_id"]: row for row in iter_jsonl(consensus) if row["status"] == "admitted_for_gates"
    }
    by_record: defaultdict[tuple, list[str]] = defaultdict(list)
    for item_id in decisions:
        by_record[_key(items[item_id]["key"])].append(item_id)
    materializer = Materializer()
    counts: Counter[str] = Counter()
    needed: Counter[tuple[str, str, str]] = Counter()
    with (
        (out_dir / "delta.jsonl").open("w", encoding="utf-8") as delta_out,
        (out_dir / "materialization-held.jsonl").open("w", encoding="utf-8") as held_out,
        (out_dir / "materialized.jsonl").open("w", encoding="utf-8") as done_out,
    ):
        for record in iter_jsonl(stage):
            ids = by_record.get(_key(record))
            if not ids:
                continue
            working = copy.deepcopy(record)
            known = {row.get("statement_id") for row in record.get("source_statements", []) or []}
            new_statements: dict[str, dict] = {}
            added: list[dict] = []
            removed: list[dict] = []
            for item_id in sorted(ids, key=lambda i: items[i]["value_start"]):
                item, decision = items[item_id], decisions[item_id]
                if item["target_kind"] == "explicit_disjunction_union":
                    assertion, why, probe = materializer.union_assertion(working, item, decision)
                else:
                    assertion, why, probe = materializer.quality_assertion(working, item, decision)
                if assertion is None:
                    counts[f"held:{why.split(':')[0]}"] += len(item["spans"])
                    if why.startswith("gate_") and probe is not None:
                        needed[(probe["po_id"], probe["pato_id"], why.split(":", 1)[1])] += 1
                    held_out.write(json.dumps({
                        "item_id": item_id, "bearer_id": decision["bearer_id"], "reason": why,
                        "po_id": probe.get("po_id") if probe else None,
                        "pato_id": probe.get("pato_id") if probe else None,
                        "value_text": item["value_text"], "context": item["context"],
                    }, ensure_ascii=False) + "\n")
                    continue
                probe_record = dict(working)
                probe_record["assertions"] = [*(working.get("assertions", []) or []), assertion]
                upgraded = ensure_source_statements(probe_record)
                materialized = upgraded["assertions"][-1]
                statement_id = materialized["source_statement_id"]
                statement = next(
                    row for row in upgraded["source_statements"] if row["statement_id"] == statement_id
                )
                if statement_id not in known:
                    new_statements[statement_id] = statement
                working["source_statements"] = upgraded["source_statements"]
                working["assertions"] = [*(working.get("assertions", []) or []), materialized]
                working["unresolved_spans"] = [
                    s for s in working.get("unresolved_spans", []) or []
                    if not any(
                        (s.get("start"), s.get("end"), s.get("reason"))
                        == (t["start"], t["end"], t["reason"]) for t in item["spans"]
                    )
                ]
                added.append(materialized)
                removed.extend(
                    {"start": t["start"], "end": t["end"], "reason": t["reason"],
                     "surface_form": t["surface_form"]}
                    for t in item["spans"]
                )
                counts["admitted_items"] += 1
                counts["admitted_spans"] += len(item["spans"])
                counts[f"admitted:{item['target_kind']}"] += 1
                done_out.write(json.dumps({
                    "item_id": item_id, "target_kind": item["target_kind"],
                    "po_id": materialized["po_id"], "pato_id": materialized["pato_id"],
                    "value_terms": materialized.get("value_terms", []),
                    "source_text": materialized["source_text"], "value_text": item["value_text"],
                    "context": item["context"], "agreeing": decision["agreeing_reviewers"],
                }, ensure_ascii=False) + "\n")
            if added:
                delta_out.write(json.dumps({
                    "key": {name: record.get(name) for name in KEY_FIELDS},
                    "add_source_statements": list(new_statements.values()),
                    "add_assertions": added,
                    "remove_unresolved": removed,
                }, ensure_ascii=False) + "\n")
                counts["delta_segments"] += 1
    with (out_dir / "needed-pairs.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["po_id", "pato_id", "gate_reasons", "items"])
        for (po_id, pato_id, reasons), count in needed.most_common():
            writer.writerow([po_id, pato_id, reasons, count])
    report = {
        "stage": str(stage),
        "consensus_admitted_items": len(decisions),
        "counts": dict(sorted(counts.items())),
        "needed_pairs": len(needed),
    }
    (out_dir / "materialization-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("stage", type=Path)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("consensus", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(materialize(args.stage, args.inventory, args.consensus, args.out_dir), indent=2))


if __name__ == "__main__":
    main()
