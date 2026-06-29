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
    organ: str = ""
    source_text: str = ""
    value_low: float | None = None
    value_high: float | None = None
    unit: str = ""
    value_text: str = ""

    @property
    def key(self) -> tuple[str, str]:
        return (self.po_id, self.pato_id)


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
    negation_correct: int = 0
    negation_total: int = 0
    hallucinations: int = 0
    predictions: int = 0
    grounding_confusion: Counter = field(default_factory=Counter)
    by_organ: dict[str, PRF] = field(default_factory=lambda: defaultdict(PRF))

    @property
    def negation_accuracy(self) -> float:
        return self.negation_correct / self.negation_total if self.negation_total else 1.0

    @property
    def hallucination_rate(self) -> float:
        return self.hallucinations / self.predictions if self.predictions else 0.0

    def summary(self) -> dict:
        return {
            "exact": self.exact.as_dict(),
            "lenient": self.lenient.as_dict(),
            "negation_accuracy": round(self.negation_accuracy, 4),
            "hallucination_rate": round(self.hallucination_rate, 4),
            "predictions": self.predictions,
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

    Fraction of distinct assertion keys (PO, PATO, negated) that are NOT present in every run.
    0.0 = perfectly reproducible; higher = more stochastic (the Asteraceae 16.7% analogue).
    """
    if len(runs) < 2:
        return 0.0
    keysets = [{(a.po_id, a.pato_id, a.negated) for a in run} for run in runs]
    union = set().union(*keysets)
    if not union:
        return 0.0
    stable = sum(1 for k in union if all(k in ks for ks in keysets))
    return round(1 - stable / len(union), 4)
