"""Build and maintain the reviewable botanical terminology registry."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from flopo2.terminology.catalog import OntologyCatalog, load_catalog
from flopo2.terminology.model import REGISTRY_FIELDS, GlossaryTerm, RegistryEntry
from flopo2.terminology.normalize import fold
from flopo2.terminology.retrieve import HybridRetriever
from flopo2.terminology.sources import iter_manifest_terms

_CURATED_FIELDS = (
    "target_id",
    "target_label",
    "target_namespace",
    "mapping_relation",
    "mapping_confidence",
    "mapping_method",
    "review_status",
    "curator_orcid",
    "mapping_date",
    "component_ids",
    "logical_operator",
    "attribute_id",
    "evidence",
    "notes",
)


def read_registry(path: Path) -> list[RegistryEntry]:
    if not Path(path).exists():
        return []
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return [RegistryEntry.from_row(row) for row in csv.DictReader(handle, delimiter="\t")]


def write_registry(entries: list[RegistryEntry], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REGISTRY_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for entry in sorted(entries, key=lambda item: (item.source_id, item.term_id)):
            writer.writerow(entry.to_row())


def _candidate_columns(candidates) -> tuple[str, str, str]:
    return (
        "|".join(candidate.target_id for candidate in candidates),
        "|".join(candidate.label.replace("|", "/") for candidate in candidates),
        "|".join(f"{candidate.score:.4f}" for candidate in candidates),
    )


def _from_source(term: GlossaryTerm) -> RegistryEntry:
    return RegistryEntry(
        term_id=term.term_id,
        surface_form=term.surface_form,
        normalized_form=fold(term.surface_form),
        language=term.language,
        semantic_role=term.semantic_role,
        category=term.category,
        organ_context=term.organ_context,
        definition=term.definition,
        source_id=term.source_id,
        source_record_id=term.source_record_id,
        source_version=term.source_version,
        source_url=term.source_url,
        license=term.license,
        translation_group=term.translation_group,
        target_id=term.target_id,
        target_label=term.target_label,
        target_namespace=term.target_namespace,
        mapping_relation=term.mapping_relation or "flopo:unmapped",
        mapping_confidence=term.mapping_confidence,
        mapping_method=term.mapping_method,
        review_status=term.review_status,
        curator_orcid=term.curator_orcid,
        mapping_date=term.mapping_date,
        component_ids="|".join(part for part in term.component_ids if part),
        logical_operator=term.logical_operator,
        attribute_id=term.attribute_id,
        evidence=term.evidence,
        notes=term.notes,
    )


def _align_entry(entry: RegistryEntry, catalog: OntologyCatalog, retriever: HybridRetriever) -> None:
    if entry.target_id:
        if entry.target_id in catalog.terms and not entry.target_label:
            entry.target_label = catalog.terms[entry.target_id].label
        entry.candidate_ids = entry.target_id
        entry.candidate_labels = entry.target_label
        entry.candidate_scores = "1.0000"
        return
    exact = catalog.exact(entry.surface_form, entry.semantic_role)
    if len(exact) == 1:
        target = exact[0]
        primary = fold(target.label) == entry.normalized_form
        relation = catalog.relation_for_surface(target, entry.surface_form)
        entry.target_id = target.curie
        entry.target_label = target.label
        entry.target_namespace = target.namespace
        entry.mapping_relation = relation
        if relation == "skos:exactMatch":
            entry.mapping_confidence = 0.99 if primary else 0.97
            entry.mapping_method = "ontology_primary_label_exact" if primary else "ontology_synonym_exact"
            entry.review_status = "auto"
        else:
            entry.mapping_confidence = 0.85
            entry.mapping_method = "ontology_scoped_synonym_proposal"
            entry.review_status = "proposed"
        entry.candidate_ids = target.curie
        entry.candidate_labels = target.label
        entry.candidate_scores = f"{entry.mapping_confidence:.4f}"
        return
    candidates = retriever.retrieve(
        entry.surface_form,
        role=entry.semantic_role,
        category=entry.category,
        organ_context=entry.organ_context,
        k=10,
    )
    entry.candidate_ids, entry.candidate_labels, entry.candidate_scores = _candidate_columns(candidates)
    if len(exact) > 1:
        entry.review_status = "review"
        entry.mapping_method = "ambiguous_ontology_exact"
        entry.mapping_confidence = 0.0
        entry.mapping_relation = "flopo:unmapped"
    elif candidates:
        entry.review_status = "proposed"
        entry.mapping_method = "hybrid_candidate_retrieval"
        entry.mapping_confidence = candidates[0].score
        entry.mapping_relation = "flopo:unmapped"


def _propagate_reviewed_surfaces(entries: list[RegistryEntry], catalog: OntologyCatalog) -> None:
    trusted: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in entries:
        if entry.target_id and entry.review_status in {"reviewed", "accepted"}:
            trusted[(entry.normalized_form, entry.semantic_role)].add(entry.target_id)
    for entry in entries:
        targets = trusted.get((entry.normalized_form, entry.semantic_role), set())
        if entry.target_id or entry.review_status in {"reviewed", "accepted", "rejected"}:
            continue
        if len(targets) != 1:
            continue
        target_id = next(iter(targets))
        target = catalog.terms.get(target_id)
        if target is None:
            continue
        entry.target_id = target_id
        entry.target_label = target.label
        entry.target_namespace = target.namespace
        entry.mapping_relation = "skos:closeMatch"
        entry.mapping_confidence = 0.94
        entry.mapping_method = "reviewed_surface_transfer"
        entry.review_status = "proposed"
        entry.candidate_ids = target_id
        entry.candidate_labels = target.label
        entry.candidate_scores = "0.9400"


def _propagate_translation_groups(entries: list[RegistryEntry], catalog: OntologyCatalog) -> None:
    groups: dict[str, list[RegistryEntry]] = defaultdict(list)
    for entry in entries:
        if entry.translation_group:
            groups[entry.translation_group].append(entry)
    for members in groups.values():
        target_ids = {
            member.target_id
            for member in members
            if member.target_id and member.review_status in {"reviewed", "accepted", "auto"}
        }
        if len(target_ids) != 1:
            continue
        target_id = next(iter(target_ids))
        target = catalog.terms.get(target_id)
        if target is None:
            continue
        for member in members:
            if member.target_id or member.review_status in {"reviewed", "accepted", "rejected"}:
                continue
            member.target_id = target_id
            member.target_label = target.label
            member.target_namespace = target.namespace
            member.mapping_relation = "skos:closeMatch"
            member.mapping_confidence = 0.92
            member.mapping_method = "parallel_glossary_transfer"
            member.review_status = "proposed"
            member.candidate_ids = target_id
            member.candidate_labels = target.label
            member.candidate_scores = "0.9200"


def _preserve_curated(entry: RegistryEntry, existing: RegistryEntry) -> None:
    entry.corpus_frequency = existing.corpus_frequency
    if not existing.is_curated and existing.review_status != "rejected":
        return
    for field_name in _CURATED_FIELDS:
        setattr(entry, field_name, getattr(existing, field_name))


def build_registry(
    manifest: Path = Path("config/terminology_sources.tsv"),
    output: Path = Path("config/botanical_terminology.tsv"),
    root: Path = Path("."),
    catalog: OntologyCatalog | None = None,
    dense_encoder=None,
) -> list[RegistryEntry]:
    """Rebuild source metadata while preserving explicitly reviewed mapping decisions."""
    catalog = catalog or load_catalog()
    retriever = HybridRetriever(catalog, dense_encoder=dense_encoder)
    existing = {entry.term_id: entry for entry in read_registry(output)}
    entries: list[RegistryEntry] = []
    seen: set[str] = set()
    for term in iter_manifest_terms(manifest, root=root):
        if term.term_id in seen:
            raise ValueError(f"duplicate stable botanical term id: {term.term_id}")
        seen.add(term.term_id)
        entry = _from_source(term)
        _align_entry(entry, catalog, retriever)
        if term.term_id in existing:
            _preserve_curated(entry, existing[term.term_id])
        entries.append(entry)
    _propagate_reviewed_surfaces(entries, catalog)
    _propagate_translation_groups(entries, catalog)
    write_registry(entries, output)
    return entries
