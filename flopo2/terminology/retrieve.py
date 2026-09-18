"""Hybrid lexical/definition/dense retrieval over PO, PATO, and FLOPO.

Exact lookup remains the highest-precision path.  The hybrid retriever is for unresolved terms and
returns candidates, never an automatic ontology assertion.  Dense scoring is optional so offline
and CI runs remain reproducible without downloading a model.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from flopo2.terminology.catalog import OntologyCatalog, OntologyTerm
from flopo2.terminology.model import Candidate
from flopo2.terminology.normalize import char_ngrams, fold


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    ln = math.sqrt(sum(a * a for a in left))
    rn = math.sqrt(sum(b * b for b in right))
    return dot / (ln * rn) if ln and rn else 0.0


class SentenceTransformerEncoder:
    """Lazy optional dense encoder, normally SapBERT for biomedical terminology."""

    def __init__(self, model: str = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext") -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional heavy dependency
            raise RuntimeError(
                "dense terminology retrieval requires the 'terminology' optional dependencies"
            ) from exc
        self.model_name = model
        self.model = SentenceTransformer(model)

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        values = self.model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        return [list(map(float, row)) for row in values]


@dataclass(frozen=True)
class _Document:
    term: OntologyTerm
    text: str
    tokens: tuple[str, ...]
    definition_tokens: frozenset[str]
    trigrams: frozenset[str]


class HybridRetriever:
    def __init__(self, catalog: OntologyCatalog, dense_encoder=None) -> None:
        self.catalog = catalog
        self.documents: dict[str, _Document] = {}
        self.token_index: dict[str, set[str]] = defaultdict(set)
        self.trigram_index: dict[str, set[str]] = defaultdict(set)
        self.df: Counter[str] = Counter()
        self.dense_encoder = dense_encoder
        self._dense_vectors: dict[str, list[float]] = {}

        for curie, term in catalog.terms.items():
            if term.deprecated:
                continue
            parent_labels = [
                catalog.terms[parent].label for parent in term.parents if parent in catalog.terms
            ]
            text = " ".join((term.label, *term.synonyms, term.definition, *parent_labels)).strip()
            tokens = tuple(fold(text).split())
            document = _Document(
                term=term,
                text=text,
                tokens=tokens,
                definition_tokens=frozenset(fold(term.definition).split()),
                trigrams=frozenset(char_ngrams(" ".join(term.forms))),
            )
            self.documents[curie] = document
            unique_tokens = set(tokens)
            self.df.update(unique_tokens)
            for token in unique_tokens:
                self.token_index[token].add(curie)
            for trigram in document.trigrams:
                self.trigram_index[trigram].add(curie)
        self.avgdl = (
            sum(len(document.tokens) for document in self.documents.values()) / len(self.documents)
            if self.documents
            else 1.0
        )

    def _candidate_pool(self, query: str, namespaces: set[str], limit: int = 600) -> set[str]:
        normalized = fold(query)
        exact = self.catalog.form_to_ids.get(normalized, set())
        counts: Counter[str] = Counter()
        for token in set(normalized.split()):
            counts.update(self.token_index.get(token, ()))
        for trigram in char_ngrams(normalized):
            counts.update(self.trigram_index.get(trigram, ()))
        pool = set(exact)
        # Counter.most_common() preserves encounter order for ties.  The indexes above store
        # CURIEs in sets, so relying on that order made the generated registry vary with
        # PYTHONHASHSEED.  Rank ties by CURIE before truncating the lexical candidate pool.
        ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
        for curie, _ in ranked:
            if self.documents[curie].term.namespace in namespaces:
                pool.add(curie)
        return {
            curie
            for curie in pool
            if curie in self.documents and self.documents[curie].term.namespace in namespaces
        }

    def _bm25(self, query_tokens: list[str], document: _Document) -> float:
        if not query_tokens:
            return 0.0
        tf = Counter(document.tokens)
        total = 0.0
        n_docs = max(1, len(self.documents))
        k1, b = 1.5, 0.75
        for token in set(query_tokens):
            freq = tf[token]
            if not freq:
                continue
            df = self.df[token]
            idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
            denominator = freq + k1 * (1 - b + b * len(document.tokens) / self.avgdl)
            total += idf * (freq * (k1 + 1) / denominator)
        return total

    def _dense_scores(self, query: str, ids: list[str]) -> dict[str, float]:
        if self.dense_encoder is None or not ids:
            return {}
        missing = [curie for curie in ids if curie not in self._dense_vectors]
        if missing:
            vectors = self.dense_encoder.encode([self.documents[curie].text for curie in missing])
            self._dense_vectors.update(zip(missing, vectors, strict=True))
        query_vector = self.dense_encoder.encode([query])[0]
        return {curie: max(0.0, _cosine(query_vector, self._dense_vectors[curie])) for curie in ids}

    def _dense_top(self, query: str, namespaces: set[str], limit: int = 100) -> set[str]:
        if self.dense_encoder is None:
            return set()
        ids = [
            curie
            for curie, document in self.documents.items()
            if document.term.namespace in namespaces
        ]
        scores = self._dense_scores(query, ids)
        return {
            curie
            for curie, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
        }

    def retrieve(
        self,
        query: str,
        role: str = "ambiguous",
        category: str = "",
        organ_context: str = "",
        k: int = 10,
    ) -> list[Candidate]:
        normalized = fold(query)
        if not normalized:
            return []
        namespaces = self.catalog.namespaces_for_role(role)
        pool = self._candidate_pool(query, namespaces)
        pool.update(self._dense_top(query, namespaces))
        if not pool:
            return []
        query_tokens = normalized.split()
        query_trigrams = char_ngrams(normalized)
        raw_bm25 = {curie: self._bm25(query_tokens, self.documents[curie]) for curie in pool}
        max_bm25 = max(raw_bm25.values(), default=1.0) or 1.0
        dense = self._dense_scores(query, sorted(pool))
        candidates: list[Candidate] = []
        for curie in sorted(pool):
            doc = self.documents[curie]
            term = doc.term
            form_scores = []
            exact_form = False
            primary_exact = fold(term.label) == normalized
            for form in term.forms:
                form_normalized = fold(form)
                if form_normalized == normalized:
                    exact_form = True
                    form_scores.append(1.0 if form == term.label else 0.98)
                    continue
                grams = char_ngrams(form_normalized)
                overlap = len(query_trigrams & grams)
                form_scores.append(2 * overlap / (len(query_trigrams) + len(grams)) if grams else 0.0)
            lexical = max(form_scores, default=0.0)
            bm25 = raw_bm25[curie] / max_bm25
            definition_overlap = len(set(query_tokens) & doc.definition_tokens)
            definition_score = definition_overlap / len(set(query_tokens)) if query_tokens else 0.0
            role_score = 1.0 if term.namespace in namespaces else 0.0
            organ = fold(organ_context)
            organ_score = 0.0
            if organ and term.namespace == "PO":
                organ_tokens = set(organ.split())
                target_tokens = set(fold(doc.text).split())
                organ_score = len(organ_tokens & target_tokens) / len(organ_tokens)
            dense_score = dense.get(curie, 0.0)
            score = (
                0.44 * lexical
                + 0.20 * bm25
                + 0.10 * definition_score
                + 0.10 * role_score
                + 0.05 * organ_score
                + 0.11 * dense_score
            )
            if exact_form:
                score = max(score, 0.99 if primary_exact else 0.97)
            evidence = []
            if primary_exact:
                evidence.append("primary_label_exact")
            elif exact_form:
                evidence.append("synonym_exact")
            if category:
                evidence.append(f"glossary_category={category}")
            if definition_score:
                evidence.append("definition_token_overlap")
            if dense_score:
                evidence.append("dense_similarity")
            candidates.append(
                Candidate(
                    target_id=curie,
                    label=term.label,
                    namespace=term.namespace,
                    score=round(min(1.0, score), 4),
                    evidence=tuple(evidence),
                    lexical_score=round(lexical, 4),
                    definition_score=round(definition_score, 4),
                    dense_score=round(dense_score, 4),
                    role_score=round(role_score, 4),
                    organ_score=round(organ_score, 4),
                )
            )
        candidates.sort(key=lambda candidate: (-candidate.score, candidate.target_id))
        return candidates[:k]
