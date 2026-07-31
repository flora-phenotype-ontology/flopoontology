"""Validate corpus-missing surfaces against pinned PO/PATO/FLOPO lexical metadata."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

from flopo2.terminology.catalog import (
    OntologyCatalog,
    canonical_curie,
    load_catalog_from_ontology_files,
)
from flopo2.terminology.normalize import fold
from flopo2.terminology.registry import read_registry


REPORT_FIELDS = (
    "surface_form",
    "corpus_frequency",
    "semantic_roles",
    "exact_target_ids",
    "exact_target_labels",
    "scoped_target_ids",
    "scoped_target_labels",
    "scoped_relations",
    "existing_target_ids",
    "existing_relations",
    "existing_review_statuses",
    "recommendation",
    "validation_findings",
    "next_action",
)


def _baseline_surfaces(path: Path) -> dict[str, int]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    pairs = data.get("unresolved", {}).get("missing_surfaces", [])
    surfaces: dict[str, int] = {}
    for value, frequency in pairs:
        surface = fold(str(value))
        if not surface:
            raise ValueError(f"{path}: empty missing surface")
        if surface in surfaces:
            raise ValueError(f"{path}: duplicate normalized missing surface {surface!r}")
        surfaces[surface] = int(frequency)
    if not surfaces:
        raise ValueError(f"{path}: no unresolved.missing_surfaces entries")
    return surfaces


def _role_compatible(namespace: str, roles: set[str]) -> bool:
    if not roles or "ambiguous" in roles:
        return True
    if namespace == "PO":
        return "entity" in roles
    if namespace == "PATO":
        return bool(roles & {"quality", "value"})
    if namespace == "FLOPO":
        return bool(roles & {"entity", "quality", "value", "phenotype"})
    return False


def _joined(values) -> str:
    return "|".join(str(value).replace("|", "/") for value in values if value != "")


def _recommendation(
    exact_ids: list[str], scoped_ids: list[str], catalog: OntologyCatalog, roles: set[str]
) -> tuple[str, str]:
    compatible = [
        curie for curie in exact_ids if _role_compatible(catalog.terms[curie].namespace, roles)
    ]
    if len(exact_ids) == 1 and len(compatible) == 1:
        return (
            "deterministic_exact_candidate",
            "Review the corpus sense, then accept the single preferred-label/EXACT-synonym target.",
        )
    if len(exact_ids) == 1:
        return (
            "exact_candidate_role_review",
            "Resolve the registry semantic-role conflict before accepting the lexical target.",
        )
    if len(exact_ids) > 1:
        return (
            "ambiguous_exact_candidates",
            "Disambiguate per mention; exact spelling alone cannot choose among ontology senses.",
        )
    if scoped_ids:
        return (
            "scoped_synonym_review",
            "Preserve BROAD/NARROW/RELATED direction and adjudicate; do not auto-normalize.",
        )
    return (
        "no_lexical_candidate",
        "Send to evidence-backed mapping, ontology-gap, compositional-phenotype, or noise review.",
    )


def validate_missing_surface_mappings(
    baseline_manifest: Path,
    registry_path: Path,
    catalog: OntologyCatalog,
) -> tuple[list[dict[str, str | int]], dict[str, object]]:
    """Return one validation row for every frozen corpus-missing surface."""
    frequencies = _baseline_surfaces(baseline_manifest)
    registry_by_surface = defaultdict(list)
    for entry in read_registry(registry_path):
        registry_by_surface[fold(entry.normalized_form or entry.surface_form)].append(entry)

    rows: list[dict[str, str | int]] = []
    recommendation_counts = Counter()
    finding_counts = Counter()
    exact_candidate_mentions = 0

    for surface, frequency in sorted(frequencies.items(), key=lambda item: (-item[1], item[0])):
        entries = registry_by_surface.get(surface, [])
        roles = {entry.semantic_role for entry in entries if entry.semantic_role}
        target_ids = sorted(catalog.form_to_ids.get(surface, ()))
        exact_ids: list[str] = []
        scoped: list[tuple[str, str]] = []
        for curie in target_ids:
            term = catalog.terms[curie]
            relation = catalog.relation_for_surface(term, surface)
            if relation == "skos:exactMatch":
                exact_ids.append(curie)
            else:
                scoped.append((curie, relation))

        existing = []
        for entry in entries:
            if not entry.target_id:
                continue
            existing.append(
                (
                    canonical_curie(entry.target_id),
                    entry.mapping_relation,
                    entry.review_status,
                )
            )

        findings: set[str] = set()
        if not entries:
            findings.add("surface_absent_from_registry")
        for curie, relation, _status in existing:
            term = catalog.terms.get(curie)
            if term is None:
                findings.add("existing_target_unknown_in_pinned_catalog")
                continue
            if term.deprecated:
                findings.add("existing_target_deprecated")
                continue
            if curie not in target_ids:
                findings.add("existing_target_not_lexically_supported")
                continue
            lexical_relation = catalog.relation_for_surface(term, surface)
            if relation == "skos:exactMatch" and lexical_relation != "skos:exactMatch":
                findings.add("unsafe_exact_over_scoped_synonym")
            elif relation.startswith("skos:") and relation != lexical_relation:
                findings.add("mapping_relation_differs_from_ontology_scope")
        if not existing:
            findings.add("no_existing_mapping")
        if exact_ids and not any(
            _role_compatible(catalog.terms[curie].namespace, roles) for curie in exact_ids
        ):
            findings.add("semantic_role_namespace_conflict")
        if len(exact_ids) > 1:
            findings.add("lexical_collision")

        recommendation, next_action = _recommendation(
            exact_ids, [curie for curie, _relation in scoped], catalog, roles
        )
        recommendation_counts[recommendation] += 1
        if recommendation == "deterministic_exact_candidate":
            exact_candidate_mentions += frequency
        for finding in findings:
            finding_counts[finding] += 1

        rows.append(
            {
                "surface_form": surface,
                "corpus_frequency": frequency,
                "semantic_roles": _joined(sorted(roles)),
                "exact_target_ids": _joined(exact_ids),
                "exact_target_labels": _joined(catalog.terms[curie].label for curie in exact_ids),
                "scoped_target_ids": _joined(curie for curie, _relation in scoped),
                "scoped_target_labels": _joined(
                    catalog.terms[curie].label for curie, _relation in scoped
                ),
                "scoped_relations": _joined(relation for _curie, relation in scoped),
                "existing_target_ids": _joined(sorted({item[0] for item in existing})),
                "existing_relations": _joined(sorted({item[1] for item in existing})),
                "existing_review_statuses": _joined(sorted({item[2] for item in existing})),
                "recommendation": recommendation,
                "validation_findings": _joined(sorted(findings)),
                "next_action": next_action,
            }
        )

    summary: dict[str, object] = {
        "total_surfaces": len(rows),
        "total_missing_mentions": sum(frequencies.values()),
        "recommendations": dict(sorted(recommendation_counts.items())),
        "validation_findings": dict(sorted(finding_counts.items())),
        "deterministic_exact_candidate_mentions": exact_candidate_mentions,
        "policy": {
            "automatic_acceptance": False,
            "exact_candidate_meaning": (
                "one live preferred-label or EXACT-synonym target with a compatible namespace; "
                "corpus-sense review is still required"
            ),
            "scoped_synonyms": "never treated as exact",
        },
    }
    return rows, summary


def write_report(path: Path, rows: list[dict[str, str | int]]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=REPORT_FIELDS, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument(
        "--registry", type=Path, default=Path("config/botanical_terminology.tsv")
    )
    parser.add_argument("--po-obo", type=Path, required=True)
    parser.add_argument("--pato-obo", type=Path, required=True)
    parser.add_argument("--flopo-owl", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--flopo-registry", type=Path)
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    args = parser.parse_args()

    catalog = load_catalog_from_ontology_files(
        args.po_obo, args.pato_obo, args.flopo_owl, args.flopo_registry
    )
    rows, summary = validate_missing_surface_mappings(
        args.baseline_manifest, args.registry, catalog
    )
    write_report(args.out, rows)
    rendered = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
