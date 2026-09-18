"""Constrained LLM adjudication of unresolved terminology mappings.

Adjudication only creates proposals.  It cannot mark a mapping reviewed or add ontology synonyms;
a human curator must make that transition in the registry.
"""

from __future__ import annotations

import json

from flopo2.terminology.catalog import OntologyCatalog
from flopo2.terminology.model import RegistryEntry

_RELATIONS = {
    "skos:exactMatch",
    "skos:closeMatch",
    "skos:relatedMatch",
    "skos:broadMatch",
    "skos:narrowMatch",
    "flopo:compositionalMatch",
    "flopo:unmapped",
}

_SYSTEM = """You align botanical glossary terminology to PO, PATO, or FLOPO.
Choose only from the supplied ontology candidates. Distinguish exact, close, broad, narrow,
compositional, and unmapped meanings. Never force an answer. A botanical phrase joined by 'or'
is one_of, not a conjunction and not multiple is_a parents. Return STRICT JSON only."""


def _prompt(entry: RegistryEntry, catalog: OntologyCatalog) -> str:
    candidates = []
    for curie in entry.candidate_id_list[:10]:
        term = catalog.terms.get(curie)
        if term is None:
            continue
        candidates.append(
            {
                "id": term.curie,
                "label": term.label,
                "namespace": term.namespace,
                "definition": term.definition,
                "parents": [
                    {"id": parent, "label": catalog.terms[parent].label if parent in catalog.terms else ""}
                    for parent in term.parents
                ],
            }
        )
    return f"""Glossary term: {entry.surface_form!r}
Language: {entry.language}
Role prior: {entry.semantic_role}
Glossary category: {entry.category}
Organ context: {entry.organ_context}
Licensed definition: {entry.definition or '(not available for indexing)'}
Candidates: {json.dumps(candidates, ensure_ascii=False)}

Return:
{{"decision":"mapped|compositional|unmapped",
  "target_ids":["candidate id"],
  "relation":"skos:exactMatch|skos:closeMatch|skos:relatedMatch|skos:broadMatch|skos:narrowMatch|flopo:compositionalMatch|flopo:unmapped",
  "logical_operator":"atomic|all_of|one_of",
  "confidence":0.0,
  "rationale":"short evidence-based explanation"}}"""


def adjudicate_entry(entry: RegistryEntry, catalog: OntologyCatalog, client, model: str) -> bool:
    result = client.chat_json(model, _SYSTEM, _prompt(entry, catalog)) or {}
    decision = result.get("decision", "")
    target_ids = [value for value in result.get("target_ids", []) if value in entry.candidate_id_list]
    relation = result.get("relation", "")
    operator = result.get("logical_operator", "atomic")
    if relation not in _RELATIONS or operator not in {"atomic", "all_of", "one_of"}:
        return False
    if decision == "mapped" and len(target_ids) == 1:
        if relation not in {
            "skos:exactMatch",
            "skos:closeMatch",
            "skos:relatedMatch",
            "skos:broadMatch",
            "skos:narrowMatch",
        }:
            return False
        target = catalog.terms.get(target_ids[0])
        if target is None:
            return False
        allowed = catalog.namespaces_for_role(entry.semantic_role)
        if target.namespace not in allowed:
            return False
        entry.target_id = target.curie
        entry.target_label = target.label
        entry.target_namespace = target.namespace
        entry.component_ids = ""
        entry.logical_operator = "atomic"
    elif decision == "compositional" and len(target_ids) >= 2:
        if operator not in {"all_of", "one_of"}:
            return False
        entry.target_id = ""
        entry.target_label = ""
        entry.target_namespace = ""
        entry.component_ids = "|".join(target_ids)
        entry.logical_operator = operator
        relation = "flopo:compositionalMatch"
    elif decision == "unmapped" and not target_ids:
        if relation != "flopo:unmapped":
            return False
        entry.target_id = ""
        entry.target_label = ""
        entry.target_namespace = ""
        entry.component_ids = ""
        entry.logical_operator = ""
        relation = "flopo:unmapped"
    else:
        return False
    try:
        confidence = max(0.0, min(1.0, float(result.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0
    entry.mapping_relation = relation
    entry.mapping_confidence = confidence
    entry.mapping_method = f"constrained_llm_adjudication:{model}"
    entry.review_status = "proposed"
    rationale = str(result.get("rationale", "")).replace("\t", " ").replace("\n", " ").strip()
    entry.evidence = rationale[:1000]
    return True


def adjudicate_registry(
    entries: list[RegistryEntry],
    catalog: OntologyCatalog,
    client,
    model: str,
    limit: int | None = None,
) -> dict:
    queue = [
        entry
        for entry in entries
        if entry.review_status not in {"reviewed", "accepted", "rejected"} and entry.candidate_ids
    ]
    queue.sort(key=lambda entry: (-entry.corpus_frequency, entry.source_id, entry.term_id))
    if limit is not None:
        queue = queue[:limit]
    changed = failed = 0
    for entry in queue:
        if adjudicate_entry(entry, catalog, client, model):
            changed += 1
        else:
            failed += 1
    return {"attempted": len(queue), "proposals_written": changed, "failed_validation": failed}
