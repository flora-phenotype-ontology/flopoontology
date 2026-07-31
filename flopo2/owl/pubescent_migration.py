"""Prepare, but do not apply, the botanical-pubescence obsolete-and-replace migration."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from lxml import etree

CURRENT = "PATO_0000455"
REPLACEMENT = "PATO_0001320"
_OWL = "http://www.w3.org/2002/07/owl#"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_OBO = "http://purl.obolibrary.org/obo/"

FIELDS = (
    "old_flopo_id",
    "old_label",
    "obsolete_label",
    "old_signature",
    "replacement_flopo_id",
    "replacement_label",
    "replacement_signature",
    "replacement_id_status",
    "term_replaced_by",
    "current_quality_label",
    "current_quality_definition",
    "replacement_quality_label",
    "replacement_quality_definition",
    "old_class_action",
    "replacement_class_action",
    "evidence",
    "recommendation",
    "curator_decision",
    "curator_notes",
)


def _owl_uses(path: Path, pato_id: str) -> tuple[set[str], int]:
    target = f"{_OBO}{pato_id}"
    classes: set[str] = set()
    occurrences = 0
    context = etree.iterparse(
        str(path), events=("end",), tag=f"{{{_OWL}}}Class", recover=True, huge_tree=True
    )
    for _event, element in context:
        class_iri = element.get(f"{{{_RDF}}}about", "")
        # Anonymous expressions are children of the named class. Clearing them separately would
        # erase the restrictions before their named parent is inspected.
        if not class_iri:
            continue
        hits = element.xpath(
            ".//owl:someValuesFrom[@rdf:resource=$target]",
            namespaces={"owl": _OWL, "rdf": _RDF},
            target=target,
        )
        if hits and class_iri.startswith(f"{_OBO}FLOPO_"):
            classes.add(class_iri.rsplit("/", 1)[-1])
            occurrences += len(hits)
        element.clear(keep_tail=True)
    return classes, occurrences


def _quality_metadata(pato_obo: Path) -> dict[str, tuple[str, str]]:
    from flopo2.terminology.catalog import load_obo_metadata

    metadata = load_obo_metadata(pato_obo)
    return {
        curie: (
            metadata.get(curie, {}).get("label", ""),
            metadata.get(curie, {}).get("definition", ""),
        )
        for curie in (CURRENT, REPLACEMENT)
    }


def _flopo_id(iri: str) -> str:
    return iri.rsplit("/", 1)[-1]


def _numeric_id(flopo_id: str) -> int:
    return int(flopo_id.removeprefix("FLOPO_"))


def _allocate_replacements(
    registry: list[dict[str, str]], affected: list[dict[str, str]]
) -> tuple[dict[str, tuple[str, str]], int, int]:
    """Map corrected signatures to existing or deterministic provisional replacement IDs."""

    active_by_signature: dict[str, list[str]] = {}
    max_number = 0
    for row in registry:
        flopo_id = _flopo_id(row["flopo_iri"])
        max_number = max(max_number, _numeric_id(flopo_id))
        if row.get("deprecated", "0") not in {"1", "true", "True"}:
            active_by_signature.setdefault(row.get("signature", ""), []).append(flopo_id)

    replacement_by_signature: dict[str, tuple[str, str]] = {}
    reused = 0
    minted = 0
    for signature in sorted(
        {row["signature"].replace(CURRENT, REPLACEMENT) for row in affected}
    ):
        existing_ids = sorted(active_by_signature.get(signature, []), key=_numeric_id)
        if existing_ids:
            replacement_by_signature[signature] = (existing_ids[0], "existing_active")
            reused += 1
            continue
        max_number += 1
        replacement_by_signature[signature] = (
            f"FLOPO_{max_number:07d}",
            "provisional_unreserved",
        )
        minted += 1
    return replacement_by_signature, reused, minted


def build_migration_report(
    registry_path: Path,
    owl_path: Path,
    pato_obo: Path,
    *,
    approved: bool = False,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    """Return an obsolete-and-replace review table without changing registry or OWL files."""

    with registry_path.open(encoding="utf-8", newline="") as handle:
        registry = list(csv.DictReader(handle, delimiter="\t"))
    affected = [
        row for row in registry if CURRENT in (row.get("signature") or "").split("|")
    ]
    affected.sort(key=lambda row: _numeric_id(_flopo_id(row["flopo_iri"])))

    metadata = _quality_metadata(pato_obo)
    current_label, current_definition = metadata[CURRENT]
    replacement_label, replacement_definition = metadata[REPLACEMENT]
    if not current_definition or not replacement_definition:
        raise ValueError("both PATO source and replacement must have textual definitions")

    replacements, reused, minted = _allocate_replacements(registry, affected)
    rows: list[dict[str, str]] = []
    registry_ids: set[str] = set()
    for source in affected:
        old_id = _flopo_id(source["flopo_iri"])
        registry_ids.add(old_id)
        old_signature = source["signature"]
        replacement_signature = old_signature.replace(CURRENT, REPLACEMENT)
        replacement_id, replacement_status = replacements[replacement_signature]
        label = source.get("label", "")
        rows.append(
            {
                "old_flopo_id": old_id,
                "old_label": label,
                "obsolete_label": (
                    label if label.lower().startswith("obsolete ") else f"obsolete {label}"
                ),
                "old_signature": old_signature,
                "replacement_flopo_id": replacement_id,
                "replacement_label": label,
                "replacement_signature": replacement_signature,
                "replacement_id_status": (
                    "new_approved_reserved"
                    if approved and replacement_status == "provisional_unreserved"
                    else replacement_status
                ),
                "term_replaced_by": f"{_OBO}{replacement_id}",
                "current_quality_label": current_label,
                "current_quality_definition": current_definition,
                "replacement_quality_label": replacement_label,
                "replacement_quality_definition": replacement_definition,
                "old_class_action": (
                    "remove_logical_axioms_and_usages;retain_definition;"
                    "add_owl_deprecated_true;prefix_label_obsolete;add_IAO_0100001"
                ),
                "replacement_class_action": (
                    "reuse_existing_correct_class"
                    if replacement_status == "existing_active"
                    else "mint_new_class_with_correct_botanical_pilosity_signature"
                ),
                "evidence": "EVID:UPOV_TGP14|EVID:AOS_DOWNY|PATO-source-definitions",
                "recommendation": "obsolete_and_replace_wrong_semantics",
                "curator_decision": "accept" if approved else "",
                "curator_notes": (
                    "Approved by Robert Hoehndorf (ORCID:0000-0001-8149-5890) "
                    "on 2026-07-15."
                    if approved
                    else ""
                ),
            }
        )

    owl_ids, owl_occurrences = _owl_uses(owl_path, CURRENT)
    summary: dict[str, object] = {
        "migration_mode": "obsolete_and_replace",
        "current_quality": CURRENT,
        "current_label": current_label,
        "replacement_quality": REPLACEMENT,
        "replacement_label": replacement_label,
        "affected_registry_rows": len(rows),
        "affected_owl_classes": len(owl_ids),
        "owl_restriction_occurrences": owl_occurrences,
        "unique_replacement_signatures": len(replacements),
        "existing_replacements_reused": reused,
        "provisional_replacements_minted": minted,
        "registry_only_ids": sorted(registry_ids - owl_ids),
        "owl_only_ids": sorted(owl_ids - registry_ids),
        "cross_artifact_match": registry_ids == owl_ids and len(rows) == owl_occurrences,
        "old_logical_axioms_removed_required": True,
        "term_replaced_by_required": True,
        "proposed_ids_are_reserved": approved,
        "automatic_application": False,
        "application_ready": approved and registry_ids == owl_ids,
        "curator_decision_default": "accept" if approved else "blank",
    }
    return rows, summary


def write_report(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", type=Path, default=Path("config/flopo_id_registry.tsv")
    )
    parser.add_argument("--owl", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--pato-obo", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    parser.add_argument(
        "--approved",
        action="store_true",
        help="Record the curator's approval and reserve the proposed replacement IDs.",
    )
    args = parser.parse_args()
    rows, summary = build_migration_report(
        args.registry, args.owl, args.pato_obo, approved=args.approved
    )
    write_report(args.out, rows)
    rendered = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
