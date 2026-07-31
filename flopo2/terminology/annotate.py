"""Longest-span botanical terminology annotation and context-aware normalization."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

from flopo2.terminology.catalog import OntologyCatalog, load_catalog
from flopo2.terminology.model import Candidate, RegistryEntry, TermMention
from flopo2.terminology.normalize import fold, morphology_key, text_tokens
from flopo2.terminology.registry import read_registry
from flopo2.terminology.retrieve import HybridRetriever

_SINGLE_TOKEN_STOP = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "de",
    "des",
    "du",
    "en",
    "for",
    "in",
    "la",
    "le",
    "les",
    "of",
    "or",
    "the",
    "to",
    "with",
}

# These PATO identifiers are valid biomedical qualities whose lexical forms are botanical
# homonyms. They remain visible in the source registry for audit provenance, but must never enter
# the operational botanical candidate set.
_BOTANICAL_PATO_HOMONYM_BLOCKLIST = {
    "PATO_0000389",  # acute process duration
    "PATO_0000455",  # onset-of-puberty maturity
    "PATO_0002147",  # reduced virulence (synonym: attenuated)
}


def _parse_scores(value: str) -> list[float]:
    out = []
    for part in (value or "").split("|"):
        try:
            out.append(float(part))
        except ValueError:
            out.append(0.0)
    return out


class TerminologyIndex:
    def __init__(
        self,
        entries: list[RegistryEntry],
        catalog: OntologyCatalog,
        dense_encoder=None,
    ) -> None:
        self.entries = entries
        self.catalog = catalog
        self.retriever = HybridRetriever(catalog, dense_encoder=dense_encoder)
        self.by_id = {entry.term_id: entry for entry in entries}
        self.by_form: dict[str, list[RegistryEntry]] = defaultdict(list)
        self.by_morphology: dict[str, list[RegistryEntry]] = defaultdict(list)
        self.max_tokens = 1
        for entry in entries:
            normalized = entry.normalized_form or fold(entry.surface_form)
            tokens = normalized.split()
            if not tokens or (len(tokens) == 1 and (len(normalized) < 3 or normalized in _SINGLE_TOKEN_STOP)):
                continue
            self.by_form[normalized].append(entry)
            self.by_morphology[morphology_key(normalized)].append(entry)
            self.max_tokens = max(self.max_tokens, len(tokens))

    @classmethod
    def load(
        cls,
        registry: Path = Path("config/botanical_terminology.tsv"),
        catalog: OntologyCatalog | None = None,
        dense_encoder=None,
        include_catalog: bool = True,
    ) -> "TerminologyIndex":
        catalog = catalog or load_catalog()
        entries = read_registry(registry)
        if include_catalog:
            entries.extend(cls._catalog_entries(catalog))
        return cls(entries, catalog, dense_encoder=dense_encoder)

    @staticmethod
    def _catalog_entries(catalog: OntologyCatalog) -> list[RegistryEntry]:
        entries = []
        for curie in sorted(catalog.terms):
            term = catalog.terms[curie]
            if term.deprecated or term.namespace not in {"PO", "PATO", "FLOPO"}:
                continue
            role = {
                "PO": "entity",
                "PATO": "quality",
                "FLOPO": "phenotype",
            }[term.namespace]
            seen_forms: set[str] = set()
            for surface in term.forms:
                normalized = fold(surface)
                if not normalized or normalized in seen_forms:
                    continue
                seen_forms.add(normalized)
                relation = catalog.relation_for_surface(term, surface)
                digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:10]
                entries.append(
                    RegistryEntry(
                        term_id=f"ONTOFORM:{term.curie}:{digest}",
                        surface_form=surface,
                        normalized_form=normalized,
                        language="en",
                        semantic_role=role,
                        definition=term.definition,
                        source_id=term.source,
                        target_id=term.curie,
                        target_label=term.label,
                        target_namespace=term.namespace,
                        mapping_relation=relation,
                        mapping_confidence=0.99 if relation == "skos:exactMatch" else 0.85,
                        mapping_method="ontology_runtime_index",
                        review_status="auto" if relation == "skos:exactMatch" else "proposed",
                    )
                )
        return entries

    @classmethod
    def from_catalog(cls, catalog: OntologyCatalog | None = None, dense_encoder=None) -> "TerminologyIndex":
        """Build a runtime-only ontology-label index for the ontology-context ablation."""
        catalog = catalog or load_catalog()
        return cls(cls._catalog_entries(catalog), catalog, dense_encoder=dense_encoder)

    def _entry_candidates(
        self,
        entries: list[RegistryEntry],
        surface: str,
        organ_context: str,
        k: int,
    ) -> tuple[Candidate, ...]:
        combined: dict[str, Candidate] = {}
        curated_nil = any(
            entry.review_status in {"reviewed", "accepted"}
            and not entry.target_id
            and not entry.component_ids
            and entry.mapping_relation == "flopo:unmapped"
            for entry in entries
        )
        for entry in entries:
            if entry.review_status == "rejected":
                continue
            if (
                entry.review_status in {"reviewed", "accepted"}
                and not entry.target_id
                and not entry.component_ids
                and entry.mapping_relation == "flopo:unmapped"
            ):
                continue
            ids = [entry.target_id] if entry.target_id else list(entry.candidate_id_list)
            labels = ([entry.target_label] if entry.target_id else entry.candidate_labels.split("|"))
            scores = ([entry.mapping_confidence] if entry.target_id else _parse_scores(entry.candidate_scores))
            for position, target_id in enumerate(ids):
                if not target_id or target_id in _BOTANICAL_PATO_HOMONYM_BLOCKLIST:
                    continue
                target = self.catalog.terms.get(target_id)
                label = labels[position] if position < len(labels) else (target.label if target else target_id)
                namespace = target.namespace if target else target_id.split("_", 1)[0]
                score = scores[position] if position < len(scores) else 0.0
                if entry.review_status in {"reviewed", "accepted"}:
                    score = max(score, 1.0)
                elif entry.review_status == "auto":
                    score = max(score, 0.97)
                elif entry.target_id:
                    score = max(score, 0.90)
                if organ_context and entry.organ_context:
                    left, right = fold(organ_context), fold(entry.organ_context)
                    if left == right or left in right or right in left:
                        score = min(1.0, score + 0.03)
                candidate = Candidate(
                    target_id=target_id,
                    label=label,
                    namespace=namespace,
                    score=round(score, 4),
                    # A ranked candidate is not itself a mapping.  Preserve a relation only for
                    # an asserted/proposed target (for example, palmate RELATED digitate); leave
                    # retrieval-only candidates untyped so downstream code can apply thresholds.
                    mapping_relation=entry.mapping_relation if entry.target_id else "",
                    registry_term_ids=(entry.term_id,),
                    review_status=entry.review_status,
                    evidence=tuple(filter(None, (entry.mapping_method, entry.evidence))),
                    organ_score=0.03 if organ_context and entry.organ_context else 0.0,
                )
                previous = combined.get(target_id)
                if previous is None or candidate.score > previous.score:
                    combined[target_id] = candidate
                elif previous:
                    combined[target_id] = Candidate(
                        **{
                            **previous.to_dict(),
                            "registry_term_ids": tuple(
                                sorted(set(previous.registry_term_ids) | {entry.term_id})
                            ),
                        }
                    )
        if not combined and not curated_nil:
            roles = {entry.semantic_role for entry in entries}
            role = next(iter(roles)) if len(roles) == 1 else "ambiguous"
            for candidate in self.retriever.retrieve(surface, role=role, organ_context=organ_context, k=k):
                if candidate.target_id not in _BOTANICAL_PATO_HOMONYM_BLOCKLIST:
                    combined[candidate.target_id] = candidate
        return tuple(sorted(combined.values(), key=lambda item: (-item.score, item.target_id))[:k])

    def annotate(
        self,
        text: str,
        language: str = "",
        organ_context: str = "",
        keep_overlaps: bool = True,
        k: int = 5,
    ) -> list[TermMention]:
        tokens = text_tokens(text)
        raw_matches: dict[tuple[int, int], tuple[list[RegistryEntry], str]] = {}
        for start_token in range(len(tokens)):
            for length in range(1, min(self.max_tokens, len(tokens) - start_token) + 1):
                selected = tokens[start_token : start_token + length]
                normalized = " ".join(token[0] for token in selected)
                morphological = " ".join(token[1] for token in selected)
                exact_entries = list(self.by_form.get(normalized, ()))
                morphological_entries = list(self.by_morphology.get(morphological, ()))
                # An exact glossary surface can itself be unmapped (e.g. plural ``leaves``)
                # while its singular ontology-backed form is trusted.  Merge conservative
                # morphology matches instead of allowing the weaker exact record to mask them.
                entries = list(
                    {
                        entry.term_id: entry
                        for entry in (*exact_entries, *morphological_entries)
                    }.values()
                )
                match_type = "exact" if exact_entries else "inflection"
                if language:
                    entries = [
                        entry for entry in entries if entry.language in {language, "und", ""}
                    ]
                if not entries:
                    continue
                start, end = selected[0][2], selected[-1][3]
                previous = raw_matches.get((start, end))
                if previous:
                    merged = {entry.term_id: entry for entry in (*previous[0], *entries)}
                    raw_matches[(start, end)] = (list(merged.values()), previous[1])
                else:
                    raw_matches[(start, end)] = (entries, match_type)

        spans = sorted(raw_matches)
        groups: list[list[tuple[int, int]]] = []
        for span in spans:
            overlapping = [group for group in groups if any(span[0] < other[1] and other[0] < span[1] for other in group)]
            if not overlapping:
                groups.append([span])
            else:
                base = overlapping[0]
                base.append(span)
                for extra in overlapping[1:]:
                    base.extend(extra)
                    groups.remove(extra)

        group_by_span = {span: number for number, group in enumerate(groups, start=1) for span in group}
        longest = {
            span: not any(
                other != span
                and other[0] <= span[0]
                and other[1] >= span[1]
                and (other[1] - other[0]) > (span[1] - span[0])
                for other in groups[group_by_span[span] - 1]
            )
            for span in spans
        }
        mentions = []
        for start, end in spans:
            if not keep_overlaps and not longest[(start, end)]:
                continue
            entries, match_type = raw_matches[(start, end)]
            surface = text[start:end]
            roles = tuple(sorted({entry.semantic_role for entry in entries}))
            operators = {entry.logical_operator for entry in entries if entry.logical_operator}
            component_sets = {entry.components for entry in entries if entry.components}
            attributes = {entry.attribute_id for entry in entries if entry.attribute_id}
            digest = hashlib.sha1(f"{start}:{end}:{surface}".encode("utf-8")).hexdigest()[:8]
            mentions.append(
                TermMention(
                    mention_id=f"mention-{start}-{end}-{digest}",
                    start=start,
                    end=end,
                    surface_form=surface,
                    normalized_form=fold(surface),
                    language=language,
                    semantic_roles=roles,
                    registry_term_ids=tuple(sorted(entry.term_id for entry in entries)),
                    candidates=self._entry_candidates(entries, surface, organ_context, k),
                    longest_match=longest[(start, end)],
                    overlap_group=group_by_span[(start, end)],
                    match_type=match_type,
                    organ_context=organ_context,
                    logical_operator=next(iter(operators)) if len(operators) == 1 else "",
                    component_ids=next(iter(component_sets)) if len(component_sets) == 1 else (),
                    attribute_id=next(iter(attributes)) if len(attributes) == 1 else "",
                )
            )
        return mentions

    def resolve(
        self,
        surface: str,
        namespace: str,
        role: str,
        organ_context: str = "",
        k: int = 8,
    ) -> list[Candidate]:
        entries = list(self.by_form.get(fold(surface), ()))
        if not entries:
            entries = list(self.by_morphology.get(morphology_key(surface), ()))
        candidates = list(self._entry_candidates(entries, surface, organ_context, k)) if entries else []
        candidates = [candidate for candidate in candidates if candidate.namespace == namespace]
        candidates = [
            candidate
            for candidate in candidates
            if candidate.target_id not in _BOTANICAL_PATO_HOMONYM_BLOCKLIST
        ]
        if not candidates:
            candidates = [
                candidate
                for candidate in self.retriever.retrieve(
                    surface, role=role, organ_context=organ_context, k=max(k * 2, 10)
                )
                if candidate.namespace == namespace
                and candidate.target_id not in _BOTANICAL_PATO_HOMONYM_BLOCKLIST
            ]
        return candidates[:k]

    @staticmethod
    def prompt_context(mentions: list[TermMention], longest_only: bool = True, limit: int = 30) -> str:
        lines = []
        for mention in mentions:
            if longest_only and not mention.longest_match:
                continue
            eligible = [
                candidate
                for candidate in mention.candidates
                if candidate.score >= 0.72
                and candidate.mapping_relation in {"", "skos:exactMatch", "skos:closeMatch"}
            ]
            candidates = ", ".join(
                f"{candidate.target_id} {candidate.label} "
                f"({candidate.score:.2f}; {candidate.mapping_status or 'candidate'}; "
                f"{candidate.mapping_relation or 'relation-unreviewed'})"
                for candidate in eligible[:4]
            )
            logic = ""
            if mention.logical_operator:
                logic = (
                    f"; value_operator={mention.logical_operator}; "
                    f"attribute={mention.attribute_id}; components={'|'.join(mention.component_ids)}"
                )
            lines.append(
                f'- [{mention.start}:{mention.end}] "{mention.surface_form}" '
                f"roles={'/'.join(mention.semantic_roles)} -> {candidates or 'NIL'}{logic}"
            )
            if len(lines) >= limit:
                break
        return "\n".join(lines)


@lru_cache(maxsize=4)
def load_terminology_index(
    registry: str = "config/botanical_terminology.tsv",
) -> TerminologyIndex | None:
    path = Path(registry)
    if not path.exists():
        return None
    return TerminologyIndex.load(path)


@lru_cache(maxsize=1)
def load_ontology_index() -> TerminologyIndex:
    return TerminologyIndex.from_catalog()
