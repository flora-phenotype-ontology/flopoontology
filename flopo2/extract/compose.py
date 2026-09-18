"""Phase 6 composition cross-check for entity-quality bindings.

The Phase 5 extractor proposes grounded (PO, PATO) assertions. This module checks whether the
source span and local clause support binding that quality to that entity. It has two layers:

* deterministic gates that are cheap and CI-friendly: source span must be verbatim, assertions in
  the same segment are checked for likely related-part conflicts, and English labels are matched
  when they are visible in the span;
* an optional dependency-parser hook. In production this can be backed by spaCy/Stanza; in tests it
  is just an injectable callable that returns a boolean agreement signal.

The output is a review decision. ``accept`` means the assertion can continue to Phase 7 gates;
``review`` means it needs curation before database promotion.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from pathlib import Path

from flopo2.eval.scoring import Assertion
from flopo2.extract.ground import Lexicon, load_lexicons

ParserCheck = Callable[[str, str, str], bool | None]


@dataclass(frozen=True)
class CompositionDecision:
    assertion: Assertion
    status: str
    confidence: float
    reasons: tuple[str, ...]
    entity_label: str = ""
    quality_label: str = ""
    clause: str = ""
    assertion_index: int = -1

    @property
    def accepted(self) -> bool:
        return self.status == "accept"


@dataclass(frozen=True)
class ParserSpec:
    """A parser-backed dependency check plus the languages it supports."""

    check: ParserCheck
    languages: frozenset[str]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _terms_for_id(lex: Lexicon, curie: str) -> list[str]:
    labels = [lex.id_to_label.get(curie, "")]
    labels.extend(k for k, v in lex.label_to_id.items() if v == curie)
    out = []
    seen = set()
    for label in labels:
        label = _norm(label)
        if label and label not in seen:
            seen.add(label)
            out.append(label)
    return out


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    haystack = f" {_norm(text)} "
    for term in terms:
        term = _norm(term)
        if not term:
            continue
        if f" {term} " in haystack or term in haystack:
            return True
    return False


def _matching_terms(text: str, terms: Iterable[str]) -> list[str]:
    return [term for term in terms if _contains_any(text, [term])]


def _other_po_mentions(text: str, po_lex: Lexicon, current_po_id: str) -> list[str]:
    """PO labels/synonyms visible in ``text`` that ground to a different entity."""
    hits = []
    seen = set()
    for term, po_id in po_lex.label_to_id.items():
        if po_id == current_po_id or len(term) < 3:
            continue
        if term in seen:
            continue
        if _contains_any(text, [term]):
            hits.append(term)
            seen.add(term)
    return hits


def _sentence_period(segment: str, position: int) -> bool:
    if (
        position > 0
        and position + 1 < len(segment)
        and segment[position - 1].isdigit()
        and segment[position + 1].isdigit()
    ):
        return False
    following = position + 1
    while following < len(segment) and segment[following].isspace():
        following += 1
    return following >= len(segment) or segment[following].isupper()


def _clause_around(
    segment: str,
    source_text: str,
    source_start: int | None = None,
    source_end: int | None = None,
) -> str:
    if not source_text:
        return segment
    if (
        source_start is not None
        and source_end is not None
        and 0 <= source_start <= source_end <= len(segment)
        and segment[source_start:source_end] == source_text
    ):
        start_at, end_at = source_start, source_end
    else:
        occurrences = [match.start() for match in re.finditer(re.escape(source_text), segment)]
        if len(occurrences) != 1:
            return source_text
        start_at = occurrences[0]
        end_at = start_at + len(source_text)
    boundaries = [
        idx
        for idx, char in enumerate(segment)
        if char == ";"
        or (char == "," and not (
            idx > 0
            and idx + 1 < len(segment)
            and segment[idx - 1].isdigit()
            and segment[idx + 1].isdigit()
        ))
        or (char == "." and _sentence_period(segment, idx))
    ]
    left = max((idx for idx in boundaries if idx < start_at), default=-1) + 1
    right = min((idx for idx in boundaries if idx >= end_at), default=len(segment))
    clause = segment[left:right].strip()
    if not clause:
        return source_text
    return clause


def _token_head(label: str) -> str:
    bits = re.findall(r"[a-z0-9]+", _norm(label))
    return bits[-1] if bits else ""


def _path_len(tok_a, tok_b) -> int | None:
    """Return dependency-tree path length between two spaCy tokens, if connected."""
    ancestors_a = {tok_a: 0}
    cur = tok_a
    for dist in range(1, 20):
        if cur.head is cur:
            break
        cur = cur.head
        ancestors_a[cur] = dist
    cur = tok_b
    for dist_b in range(0, 20):
        if cur in ancestors_a:
            return ancestors_a[cur] + dist_b
        if cur.head is cur:
            break
        cur = cur.head
    return None


def spacy_parser_check(model: str = "en_core_web_sm") -> ParserCheck:
    """Build a spaCy dependency checker.

    The dependency path is intentionally conservative: it returns ``None`` when the labels are not
    visible or no parser is available, ``True`` when entity and quality are locally connected, and
    ``False`` when both labels are visible but are too far apart in the parse.
    """
    try:
        import spacy  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("spaCy is not installed; install the nlp extra") from exc
    try:
        nlp = spacy.load(model)
    except OSError as exc:  # pragma: no cover - depends on local model download
        raise RuntimeError(f"spaCy model {model!r} is not installed") from exc

    def check(clause: str, entity_label: str, quality_label: str) -> bool | None:
        doc = nlp(clause)
        entity = _token_head(entity_label)
        quality = _token_head(quality_label)
        if not entity or not quality:
            return None
        entity_tokens = [t for t in doc if t.text.lower() == entity or t.lemma_.lower() == entity]
        quality_tokens = [t for t in doc if t.text.lower() == quality or t.lemma_.lower() == quality]
        if not entity_tokens or not quality_tokens:
            return None
        distances = [
            dist for e in entity_tokens for q in quality_tokens
            if (dist := _path_len(e, q)) is not None
        ]
        if not distances:
            return None
        return min(distances) <= 4

    return check


def stanza_parser_check(lang: str = "fr") -> ParserCheck:
    """Build a Stanza dependency checker for French.

    Stanza model availability varies by machine, so callers should use this through
    ``parser_spec("auto", ...)`` unless they want a hard failure.
    """
    try:
        import stanza  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError("stanza is not installed; install the nlp extra") from exc
    try:
        nlp = stanza.Pipeline(lang=lang, processors="tokenize,pos,lemma,depparse", verbose=False)
    except Exception as exc:  # pragma: no cover - depends on local model download
        raise RuntimeError(f"Stanza model for {lang!r} is not installed") from exc

    def check(clause: str, entity_label: str, quality_label: str) -> bool | None:
        doc = nlp(clause)
        entity = _token_head(entity_label)
        quality = _token_head(quality_label)
        if not entity or not quality:
            return None
        for sent in doc.sentences:
            words = sent.words
            entity_idxs = [
                w.id for w in words
                if (w.text or "").lower() == entity or (w.lemma or "").lower() == entity
            ]
            quality_idxs = [
                w.id for w in words
                if (w.text or "").lower() == quality or (w.lemma or "").lower() == quality
            ]
            if not entity_idxs or not quality_idxs:
                continue
            parents = {w.id: w.head for w in words}

            def ancestors(idx: int) -> dict[int, int]:
                out = {idx: 0}
                cur = idx
                for dist in range(1, 20):
                    cur = parents.get(cur, 0)
                    if cur == 0:
                        break
                    out[cur] = dist
                return out

            for e in entity_idxs:
                ea = ancestors(e)
                for q in quality_idxs:
                    cur = q
                    for qdist in range(0, 20):
                        if cur in ea:
                            return ea[cur] + qdist <= 4
                        cur = parents.get(cur, 0)
                        if cur == 0:
                            break
        return None

    return check


def parser_spec(mode: str, language: str | None = None) -> ParserSpec | None:
    """Return an optional parser checker for ``mode``.

    ``auto`` is soft-fail: if optional NLP models are absent, Phase 6 still runs deterministic
    gates. Explicit ``spacy``/``stanza`` modes fail loudly so deployment misconfiguration is visible.
    """
    language = (language or "").lower()
    if mode == "off":
        return None
    if mode == "spacy":
        return ParserSpec(spacy_parser_check(), frozenset({"en"}))
    if mode == "stanza":
        return ParserSpec(stanza_parser_check("fr"), frozenset({"fr"}))
    if mode != "auto":
        raise ValueError(f"unknown parser mode: {mode}")
    if language.startswith("fr"):
        try:
            return ParserSpec(stanza_parser_check("fr"), frozenset({"fr"}))
        except RuntimeError:
            return None
    if language.startswith("en"):
        try:
            return ParserSpec(spacy_parser_check(), frozenset({"en"}))
        except RuntimeError:
            return None
    return None


def check_assertion(
    segment_text: str,
    assertion: Assertion,
    po_lex: Lexicon,
    pato_lex: Lexicon,
    parser_check: ParserCheck | None = None,
    competing_entity_terms: Iterable[str] = (),
    assertion_index: int = -1,
    language: str = "",
) -> CompositionDecision:
    """Return accept/review for one assertion's entity-quality binding."""
    reasons: list[str] = []
    score = 1.0
    source = assertion.source_text or ""
    source_norm = _norm(source)
    segment_norm = _norm(segment_text)

    if not source_norm or source_norm not in segment_norm:
        reasons.append("source_span_not_verbatim")
        score -= 0.45

    entity_terms = _terms_for_id(po_lex, assertion.po_id)
    quality_terms = _terms_for_id(pato_lex, assertion.pato_id)
    entity_label = po_lex.id_to_label.get(assertion.po_id, assertion.po_id)
    quality_label = pato_lex.id_to_label.get(assertion.pato_id, assertion.pato_id)
    clause = _clause_around(
        segment_text,
        source,
        assertion.source_start,
        assertion.source_end,
    )

    entity_visible = _contains_any(source, entity_terms) or _contains_any(clause, entity_terms)
    quality_visible = _contains_any(source, quality_terms) or _contains_any(clause, quality_terms)
    if quality_terms and not quality_visible:
        reasons.append("quality_label_not_visible_in_span_or_clause")
        score -= 0.15
    if entity_terms and not entity_visible:
        # Organ headings often supply the entity for terse flora clauses, so this is review-weighted
        # but not an automatic rejection.
        reasons.append("entity_label_not_visible_in_span_or_clause")
        score -= 0.10

    competing_hits = _matching_terms(source, competing_entity_terms)
    other_po_hits = (
        _other_po_mentions(source, po_lex, assertion.po_id)
        if (language or "").lower().startswith("en")
        else []
    )
    if (competing_hits or other_po_hits) and not _contains_any(source, entity_terms):
        reasons.append("source_span_mentions_different_entity")
        score -= 0.35

    if parser_check is not None and source_norm and source_norm in segment_norm:
        parse_ok = parser_check(clause, entity_label, quality_label)
        if parse_ok is False:
            reasons.append("dependency_binding_disagrees")
            score -= 0.35
        elif parse_ok is True:
            reasons.append("dependency_binding_agrees")
            score += 0.05

    score = max(0.0, min(1.0, score))
    status = "accept" if score >= 0.75 and "source_span_not_verbatim" not in reasons else "review"
    return CompositionDecision(
        assertion=assertion,
        status=status,
        confidence=round(score, 3),
        reasons=tuple(reasons),
        entity_label=entity_label,
        quality_label=quality_label,
        clause=clause,
        assertion_index=assertion_index,
    )


def check_segment(
    segment_text: str,
    assertions: Iterable[Assertion],
    parser_check: ParserCheck | None = None,
    language: str = "",
    auto_parser: bool = True,
) -> list[CompositionDecision]:
    """Check all assertions for a segment using the configured PO/PATO lexicons."""
    po_lex, pato_lex = load_lexicons()
    assertions = list(assertions)
    parser = parser_check
    if parser is None and auto_parser:
        spec = parser_spec("auto", language)
        parser = spec.check if spec else None
    return [
        check_assertion(
            segment_text,
            assertion,
            po_lex,
            pato_lex,
            parser_check=parser,
            competing_entity_terms=(
                term
                for other_idx, other in enumerate(assertions)
                if other_idx != idx
                for term in _terms_for_id(po_lex, other.po_id)
            ),
            assertion_index=idx,
            language=language,
        )
        for idx, assertion in enumerate(assertions)
    ]


def _assertions_from_json(obj: dict) -> list[Assertion]:
    out = []
    text = obj.get("text", "")
    rows = (
        obj.get("assertions")
        or obj.get("predictions")
        or obj.get("predicted_assertions")
        or []
    )
    for a in rows:
        source_text = a.get("source_text", "")
        source_start = a.get("source_start")
        source_end = a.get("source_end")
        if source_start is None and source_end is None and source_text:
            starts = [match.start() for match in re.finditer(re.escape(source_text), text)]
            if len(starts) == 1:
                source_start = starts[0]
                source_end = source_start + len(source_text)
        out.append(Assertion(
            po_id=a.get("po_id", ""),
            pato_id=a.get("pato_id", ""),
            negated=bool(a.get("negated", False)),
            negation_scope=a.get("negation_scope", "") or "",
            organ=obj.get("organ", ""),
            source_text=source_text,
            source_start=source_start,
            source_end=source_end,
            bearer_start=a.get("bearer_start"),
            bearer_end=a.get("bearer_end"),
            modality_start=a.get("modality_start"),
            modality_end=a.get("modality_end"),
            extractor=a.get("extractor", ""),
            value_low=a.get("value_low"),
            value_high=a.get("value_high"),
            value_low_inclusive=a.get("value_low_inclusive", True),
            value_high_inclusive=a.get("value_high_inclusive", True),
            unit=a.get("unit", "") or "",
            value_text=a.get("value_text", "") or "",
            trait=a.get("trait", "") or "",
            modifier=a.get("modifier", "") or "",
            source_statement_id=a.get("source_statement_id", "") or "",
            frequency_qualifier=a.get("frequency_qualifier", "unspecified") or "unspecified",
            epistemic_modality=a.get("epistemic_modality", "asserted") or "asserted",
            value_qualifier=a.get("value_qualifier", "exact") or "exact",
            degree_qualifier=a.get("degree_qualifier", "unmodified") or "unmodified",
            modality_text=a.get("modality_text", "") or "",
            season_contexts=tuple(a.get("season_contexts", []) or []),
            season_operator=a.get("season_operator", "atomic") or "atomic",
            cardinality=str(a.get("cardinality", "") or ""),
            confidence=a.get("confidence"),
            raw_entity_text=a.get("raw_entity_text", "") or a.get("entity_text", ""),
            raw_quality_text=a.get("raw_quality_text", "") or a.get("quality_text", ""),
            entity_mention_id=a.get("entity_mention_id", ""),
            quality_mention_ids=tuple(a.get("quality_mention_ids", []) or []),
            value_operator=a.get("value_operator", "atomic") or "atomic",
            value_term_ids=tuple(a.get("value_terms", []) or a.get("value_term_ids", []) or []),
            bearer_context_qualities=tuple(a.get("bearer_context_qualities", []) or []),
            developmental_stage_contexts=tuple(
                a.get("developmental_stage_contexts", []) or []
            ),
            developmental_stage_operator=(
                a.get("developmental_stage_operator", "atomic") or "atomic"
            ),
            normalization_status=a.get("normalization_status", ""),
            mapping_provenance=tuple(a.get("mapping_provenance", []) or []),
        ))
    return out


def _assertion_to_json(a: Assertion, decision: CompositionDecision | None = None) -> dict:
    obj = {
        "po_id": a.po_id,
        "pato_id": a.pato_id,
        "negated": a.negated,
        "negation_scope": a.negation_scope,
        "organ": a.organ,
        "source_text": a.source_text,
        "source_start": a.source_start,
        "source_end": a.source_end,
        "bearer_start": a.bearer_start,
        "bearer_end": a.bearer_end,
        "modality_start": a.modality_start,
        "modality_end": a.modality_end,
        "extractor": a.extractor,
        "value_low": a.value_low,
        "value_high": a.value_high,
        "value_low_inclusive": a.value_low_inclusive,
        "value_high_inclusive": a.value_high_inclusive,
        "unit": a.unit,
        "value_text": a.value_text,
        "trait": a.trait,
        "modifier": a.modifier,
        "source_statement_id": a.source_statement_id,
        "frequency_qualifier": a.frequency_qualifier,
        "epistemic_modality": a.epistemic_modality,
        "value_qualifier": a.value_qualifier,
        "degree_qualifier": a.degree_qualifier,
        "modality_text": a.modality_text,
        "season_contexts": list(a.season_contexts),
        "season_operator": a.season_operator,
        "cardinality": a.cardinality,
        "confidence": a.confidence,
        "raw_entity_text": a.raw_entity_text,
        "raw_quality_text": a.raw_quality_text,
        "entity_mention_id": a.entity_mention_id,
        "quality_mention_ids": list(a.quality_mention_ids),
        "value_operator": a.value_operator,
        "value_terms": list(a.value_term_ids),
        "bearer_context_qualities": list(a.bearer_context_qualities),
        "developmental_stage_contexts": list(a.developmental_stage_contexts),
        "developmental_stage_operator": a.developmental_stage_operator,
        "normalization_status": a.normalization_status,
        "mapping_provenance": list(a.mapping_provenance),
    }
    if decision is not None:
        obj["composition"] = {
            "status": decision.status,
            "confidence": decision.confidence,
            "reasons": list(decision.reasons),
            "entity_label": decision.entity_label,
            "quality_label": decision.quality_label,
            "clause": decision.clause,
        }
    return obj


def _segment_base(obj: dict) -> dict:
    base = {
        "source": obj.get("source", ""),
        "source_id": obj.get("source_id", ""),
        "taxon": obj.get("taxon", ""),
        "taxon_family": obj.get("taxon_family", ""),
        "taxon_rank": obj.get("taxon_rank", ""),
        "organ": obj.get("organ", ""),
        "language": obj.get("language", ""),
        # These offsets are part of TextSegment identity and provenance.  Dropping them makes
        # repeated short descriptions indistinguishable downstream.
        "char_start": obj.get("char_start", 0),
        "char_end": obj.get("char_end", len(obj.get("text", ""))),
        "source_segment_index": obj.get("source_segment_index", 0),
        "source_statements": obj.get("source_statements", []),
        "term_mentions": obj.get("term_mentions", []),
        "unresolved_spans": obj.get("unresolved_spans", []),
        "text": obj.get("text", ""),
    }
    # Taxon identifiers are optional input provenance.  Preserve an identifier exactly when an
    # upstream normalization step supplied one, but do not create empty identifier fields for the
    # corpus' current name-only taxon records.  The source-assertion OWL builder recognizes these
    # three aliases in this order.
    for key in ("taxon_iri", "taxon_id", "taxon_curie"):
        if key in obj:
            base[key] = obj[key]
    return base


def split_segment(obj: dict, decisions: list[CompositionDecision]) -> tuple[dict, dict]:
    """Return Phase 7-ready accepted and review JSONL segment objects."""
    base = _segment_base(obj)
    accepted = {**base, "assertions": []}
    review = {**base, "assertions": []}
    for d in decisions:
        row = _assertion_to_json(d.assertion, d)
        if d.accepted:
            accepted["assertions"].append(row)
        else:
            review["assertions"].append(row)
    return accepted, review


def run_file(
    path: Path,
    out: Path,
    limit: int | None = None,
    parser_mode: str = "auto",
    accepted_out: Path | None = None,
    review_out: Path | None = None,
) -> dict:
    """Run composition checks and optionally split accepted/review queues.

    ``out`` is the audit trail with every decision. ``accepted_out`` and ``review_out`` are
    Phase-7-ready JSONL files containing the original segment metadata and assertion rows annotated
    with composition provenance.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    if accepted_out:
        accepted_out.parent.mkdir(parents=True, exist_ok=True)
    if review_out:
        review_out.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    statuses: Counter[str] = Counter()
    unresolved_spans = 0
    parser_by_lang: dict[str, ParserSpec | None] = {}
    with (
        Path(path).open(encoding="utf-8") as inp,
        out.open("w", encoding="utf-8") as fh,
        (accepted_out.open("w", encoding="utf-8") if accepted_out else nullcontext()) as accepted_fh,
        (review_out.open("w", encoding="utf-8") if review_out else nullcontext()) as review_fh,
    ):
        for line in inp:
            if limit is not None and n >= limit:
                break
            if not line.strip():
                continue
            obj = json.loads(line)
            lang = obj.get("language", "")
            if lang not in parser_by_lang:
                parser_by_lang[lang] = parser_spec(parser_mode, lang)
            spec = parser_by_lang[lang]
            decisions = check_segment(
                obj.get("text", ""),
                _assertions_from_json(obj),
                parser_check=spec.check if spec else None,
                language=lang,
                auto_parser=False,
            )
            statuses.update(d.status for d in decisions)
            unresolved_spans += len(obj.get("unresolved_spans", []) or [])
            rec = {
                **_segment_base(obj),
                "decisions": [asdict(d) for d in decisions],
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            accepted_seg, review_seg = split_segment(obj, decisions)
            if accepted_fh is not None and (
                accepted_seg["assertions"] or accepted_seg["unresolved_spans"]
            ):
                accepted_fh.write(json.dumps(accepted_seg, ensure_ascii=False) + "\n")
            if review_fh is not None and (
                review_seg["assertions"] or review_seg["unresolved_spans"]
            ):
                review_fh.write(json.dumps(review_seg, ensure_ascii=False) + "\n")
            n += 1
    return {
        "segments": n,
        "assertions": sum(statuses.values()),
        "unresolved_spans": unresolved_spans,
        "statuses": dict(statuses),
        "parser_languages": {
            lang: bool(spec) for lang, spec in sorted(parser_by_lang.items())
        },
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Phase 6 composition cross-check.")
    ap.add_argument("input", type=Path, help="JSONL with text and grounded assertions")
    ap.add_argument("-o", "--out", type=Path, default=Path("gold/composition_checks.jsonl"))
    ap.add_argument("--accepted-out", type=Path,
                    help="write accepted assertions as Phase-7-ready JSONL")
    ap.add_argument("--review-out", type=Path,
                    help="write review-queue assertions as Phase-7-ready JSONL")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--parser", choices=["auto", "off", "spacy", "stanza"], default="auto",
                    help="dependency parser mode; auto soft-fails to deterministic checks")
    args = ap.parse_args()
    summary = run_file(
        args.input,
        args.out,
        limit=args.limit,
        parser_mode=args.parser,
        accepted_out=args.accepted_out,
        review_out=args.review_out,
    )
    print(json.dumps({**summary, "out": str(args.out)}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
