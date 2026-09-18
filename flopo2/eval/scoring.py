"""Evaluation harness for trait extraction (Phase 4).

Scores predicted trait assertions against a manually-curated gold standard. Implements the metrics
the plan gates on — directly targeting the failure modes documented for LLM trait extraction
(Asteraceae study: 5.8% error, 16.7% rerun flip-rate, 13.6% related-part confusion, 3.5%
hallucination):

* **Exact P/R/F1** — (PO, PATO) tuple equality.
* **Hierarchical (lenient) P/R/F1** — credits a prediction whose PO/PATO is an ancestor or
  descendant of the gold term (right region, wrong granularity). The gap between exact and lenient
  quantifies the granularity-error problem. Needs an ``ancestors`` function (OAK in production;
  injectable + stubbable in tests).
* **Grounding confusion** — for predictions whose PO region is right, how often the specific PO
  term is wrong (the bract/phyllary signature), as a confusion counter over PO pairs.
* **Negation accuracy** — over matched pairs, fraction with the same polarity.
* **Hallucination rate** — fraction of predictions whose ``source_text`` is not verbatim in the
  source segment.
* **Self-consistency flip-rate** — across N repeated runs, fraction of assertion keys not present
  in every run (the 16.7% analogue), our primary stochasticity gate.

Breakdowns by organ and by trait type drive the hybrid per-trait-type engine selection (Phase 5).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

# An ancestors function maps a CURIE to the set of its ancestor CURIEs *including itself*.
AncestorsFn = Callable[[str], set[str]]


@dataclass(frozen=True)
class Assertion:
    """A normalized (predicted or gold) trait assertion for scoring."""

    po_id: str
    pato_id: str
    negated: bool = False
    negation_scope: str = ""
    organ: str = ""
    source_text: str = ""
    source_start: int | None = None
    source_end: int | None = None
    bearer_start: int | None = None
    bearer_end: int | None = None
    modality_start: int | None = None
    modality_end: int | None = None
    extractor: str = ""
    value_low: float | None = None
    value_high: float | None = None
    value_low_inclusive: bool = True
    value_high_inclusive: bool = True
    unit: str = ""
    value_text: str = ""
    trait: str = ""
    modifier: str = ""
    cardinality: str = ""
    confidence: float | None = None
    raw_entity_text: str = ""
    raw_quality_text: str = ""
    entity_mention_id: str = ""
    quality_mention_ids: tuple[str, ...] = ()
    value_operator: str = "atomic"
    value_term_ids: tuple[str, ...] = ()
    bearer_context_qualities: tuple[str, ...] = ()
    developmental_stage_contexts: tuple[dict[str, object], ...] = ()
    developmental_stage_operator: str = "atomic"
    normalization_status: str = ""
    mapping_provenance: tuple[str, ...] = ()
    source_statement_id: str = ""
    frequency_qualifier: str = "unspecified"
    epistemic_modality: str = "asserted"
    value_qualifier: str = "exact"
    degree_qualifier: str = "unmodified"
    modality_text: str = ""
    season_contexts: tuple[dict[str, object], ...] = ()
    season_operator: str = "atomic"

    @property
    def key(self) -> tuple[str, str]:
        return (self.po_id, self.pato_id)


def assertion_vote_key(a: "Assertion") -> tuple:
    """Complete semantic identity for self-consistency and ensemble voting.

    Two assertions may combine (vote as one) only when they denote the *same* phenotype. The
    historical keys carried bearer, quality, negation, and some categorical value information but
    differed between callers and omitted parts of the logical or quantitative semantics. Value
    terms are canonicalized because OWL intersections and unions are order-insensitive. Numeric
    identity (bounds, unit, and bound inclusivity) and negation scope are also part of the key, so
    logically incompatible assertions can never contribute to the same vote.
    """

    return (
        a.po_id,
        a.pato_id,
        a.negated,
        a.negation_scope,
        a.value_operator,
        tuple(sorted(a.value_term_ids or ())),
        a.value_low,
        a.value_high,
        a.unit,
        a.value_low_inclusive,
        a.value_high_inclusive,
    )


@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def as_dict(self) -> dict:
        return {
            "tp": self.tp, "fp": self.fp, "fn": self.fn,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


def _related(a: str, b: str, ancestors: AncestorsFn | None) -> bool:
    """True if a == b, or (with an ancestors fn) one subsumes the other."""
    if a == b:
        return True
    if ancestors is None or not a or not b:
        return False
    return a in ancestors(b) or b in ancestors(a)


def _match(
    preds: Sequence[Assertion],
    gold: Sequence[Assertion],
    ancestors: AncestorsFn | None,
) -> tuple[PRF, list[tuple[Assertion, Assertion]]]:
    """Greedy one-to-one match of preds↔gold. Exact if ``ancestors`` is None, else hierarchical."""
    unmatched_gold = list(gold)
    prf = PRF()
    pairs: list[tuple[Assertion, Assertion]] = []
    for p in preds:
        hit = None
        for g in unmatched_gold:
            if _related(p.po_id, g.po_id, ancestors) and _related(p.pato_id, g.pato_id, ancestors):
                hit = g
                break
        if hit is not None:
            prf.tp += 1
            pairs.append((p, hit))
            unmatched_gold.remove(hit)
        else:
            prf.fp += 1
    prf.fn = len(unmatched_gold)
    return prf, pairs


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


@dataclass
class EvalReport:
    exact: PRF = field(default_factory=PRF)
    lenient: PRF = field(default_factory=PRF)
    entity: PRF = field(default_factory=PRF)
    quality: PRF = field(default_factory=PRF)
    negation_correct: int = 0
    negation_total: int = 0
    hallucinations: int = 0
    predictions: int = 0
    grounding_confusion: Counter = field(default_factory=Counter)
    by_organ: dict[str, PRF] = field(default_factory=lambda: defaultdict(PRF))
    value_logic_correct: int = 0
    value_logic_total: int = 0
    disjunction_correct: int = 0
    disjunction_total: int = 0
    numeric_correct: int = 0
    numeric_total: int = 0

    @property
    def negation_accuracy(self) -> float:
        return self.negation_correct / self.negation_total if self.negation_total else 1.0

    @property
    def hallucination_rate(self) -> float:
        return self.hallucinations / self.predictions if self.predictions else 0.0

    @property
    def value_logic_accuracy(self) -> float:
        return self.value_logic_correct / self.value_logic_total if self.value_logic_total else 1.0

    @property
    def disjunction_accuracy(self) -> float:
        return self.disjunction_correct / self.disjunction_total if self.disjunction_total else 1.0

    @property
    def numeric_accuracy(self) -> float:
        return self.numeric_correct / self.numeric_total if self.numeric_total else 1.0

    def summary(self) -> dict:
        return {
            "exact": self.exact.as_dict(),
            "lenient": self.lenient.as_dict(),
            "entity": self.entity.as_dict(),
            "quality": self.quality.as_dict(),
            "negation_accuracy": round(self.negation_accuracy, 4),
            "hallucination_rate": round(self.hallucination_rate, 4),
            "predictions": self.predictions,
            "value_logic_accuracy": round(self.value_logic_accuracy, 4),
            "disjunction_accuracy": round(self.disjunction_accuracy, 4),
            "numeric_accuracy": round(self.numeric_accuracy, 4),
            "top_confusions": self.grounding_confusion.most_common(10),
            "by_organ": {k: v.as_dict() for k, v in sorted(self.by_organ.items())},
        }


def score_segment(
    preds: Sequence[Assertion],
    gold: Sequence[Assertion],
    segment_text: str = "",
    ancestors: AncestorsFn | None = None,
    report: EvalReport | None = None,
) -> EvalReport:
    """Accumulate metrics for one segment into ``report`` (created if None)."""
    r = report or EvalReport()
    r.predictions += len(preds)

    exact_prf, _ = _match(preds, gold, ancestors=None)
    r.exact.tp += exact_prf.tp
    r.exact.fp += exact_prf.fp
    r.exact.fn += exact_prf.fn

    entity_prf, _ = _match(
        [Assertion(p.po_id, "_") for p in preds],
        [Assertion(g.po_id, "_") for g in gold],
        ancestors=None,
    )
    r.entity.tp += entity_prf.tp
    r.entity.fp += entity_prf.fp
    r.entity.fn += entity_prf.fn
    quality_prf, _ = _match(
        [Assertion("_", p.pato_id) for p in preds],
        [Assertion("_", g.pato_id) for g in gold],
        ancestors=None,
    )
    r.quality.tp += quality_prf.tp
    r.quality.fp += quality_prf.fp
    r.quality.fn += quality_prf.fn

    len_prf, pairs = _match(preds, gold, ancestors=ancestors)
    r.lenient.tp += len_prf.tp
    r.lenient.fp += len_prf.fp
    r.lenient.fn += len_prf.fn

    for organ in {g.organ for g in gold} | {p.organ for p in preds}:
        op = [p for p in preds if p.organ == organ]
        og = [g for g in gold if g.organ == organ]
        oprf, _ = _match(op, og, ancestors=None)
        r.by_organ[organ].tp += oprf.tp
        r.by_organ[organ].fp += oprf.fp
        r.by_organ[organ].fn += oprf.fn

    # Negation accuracy + grounding confusion over hierarchically-matched pairs.
    for p, g in pairs:
        r.negation_total += 1
        if p.negated == g.negated:
            r.negation_correct += 1
        if p.po_id != g.po_id:  # right region (matched), wrong specific PO term
            r.grounding_confusion[(g.po_id, p.po_id)] += 1
        if g.value_term_ids or g.value_operator != "atomic":
            r.value_logic_total += 1
            logic_correct = (
                p.value_operator == g.value_operator
                and set(p.value_term_ids) == set(g.value_term_ids)
            )
            if logic_correct:
                r.value_logic_correct += 1
            if g.value_operator == "one_of":
                r.disjunction_total += 1
                if logic_correct:
                    r.disjunction_correct += 1
        if g.value_low is not None or g.value_high is not None or g.unit:
            r.numeric_total += 1
            if (
                p.value_low == g.value_low
                and p.value_high == g.value_high
                and p.value_low_inclusive == g.value_low_inclusive
                and p.value_high_inclusive == g.value_high_inclusive
                and _norm_text(p.unit) == _norm_text(g.unit)
            ):
                r.numeric_correct += 1

    # Hallucination: source span must appear verbatim in the segment text.
    if segment_text:
        seg = _norm_text(segment_text)
        for p in preds:
            if p.source_text and _norm_text(p.source_text) not in seg:
                r.hallucinations += 1
    return r


def score_dataset(
    items: Iterable[tuple[Sequence[Assertion], Sequence[Assertion], str]],
    ancestors: AncestorsFn | None = None,
) -> EvalReport:
    """Score (preds, gold, segment_text) triples across a dataset."""
    report = EvalReport()
    for preds, gold, text in items:
        score_segment(preds, gold, text, ancestors=ancestors, report=report)
    return report


def flip_rate(runs: Sequence[Sequence[Assertion]]) -> float:
    """Self-consistency flip-rate across N repeated extraction runs of the same input.

    Fraction of distinct semantic assertion keys that are NOT present in every run. 0.0 =
    perfectly reproducible; higher = more stochastic (the Asteraceae 16.7% analogue).
    """
    if len(runs) < 2:
        return 0.0
    keysets = [{assertion_vote_key(a) for a in run} for run in runs]
    union = set().union(*keysets)
    if not union:
        return 0.0
    stable = sum(1 for k in union if all(k in ks for ks in keysets))
    return round(1 - stable / len(union), 4)
