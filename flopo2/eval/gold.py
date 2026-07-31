"""Gold-standard sampling and I/O for the evaluation harness (Phase 4).

The gold standard is a stratified sample of flora text segments, manually annotated by botanists
with grounded (PO, PATO) assertions. This module:

  * **stratifies and samples** segments across source × organ-group × language so the gold set is
    balanced (the Asteraceae study showed error is organ- and language-dependent), deterministically
    so the locked test split is reproducible;
  * emits a **blank annotation template** (segments with empty ``assertions``) for curators; and
  * **loads** completed gold files into :class:`~flopo2.eval.scoring.Assertion` objects for scoring.

Gold file format = JSONL, one object per segment::

    {"source","source_id","taxon","organ","language","text",
     "assertions":[{"po_id","pato_id","negated","value_low","value_high","unit","value_text","source_text"}]}
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path

from flopo2.eval.scoring import Assertion
from flopo2.ingest.models import TextSegment

# Coarse organ groups so stratification isn't fragmented across the long tail of `char class`
# values. Mapped from common FlorML/fdac organ labels (EN + FR).
ORGAN_GROUPS = {
    "habit": "habit", "arbuste": "habit", "herbe": "habit", "tree": "habit",
    "leaves": "leaf", "leaf": "leaf", "feuilles": "leaf", "lamina": "leaf", "petiole": "leaf",
    "stipules": "leaf", "veins": "leaf",
    "flowers": "flower", "fleurs": "flower", "corolla": "flower", "petals": "flower",
    "sepals": "flower", "calyx": "flower", "stamens": "flower", "staminodes": "flower",
    "anthers": "flower", "ovary": "flower", "stigma": "flower", "inflorescences": "inflorescence",
    "fruits": "fruit", "fruit": "fruit", "gousses": "fruit", "seeds": "seed", "graines": "seed",
}


def organ_group(organ: str) -> str:
    return ORGAN_GROUPS.get(organ.lower(), "other")


def _stable_rank(seg: TextSegment) -> str:
    """Deterministic per-segment sort key (so sampling is reproducible across runs/machines)."""
    h = hashlib.sha1(f"{seg.source}|{seg.source_id}|{seg.organ}|{seg.char_start}".encode())
    return h.hexdigest()


def stratified_sample(
    segments: Iterable[TextSegment], n: int, min_chars: int = 40
) -> list[TextSegment]:
    """Pick ``n`` segments balanced across (source, organ_group, language), deterministically.

    Round-robins across strata (so no single flora/organ dominates) and within each stratum takes
    segments in stable-hash order. Skips very short segments unlikely to carry traits.
    """
    strata: dict[tuple[str, str, str], list[TextSegment]] = defaultdict(list)
    for s in segments:
        if len(s.text) < min_chars:
            continue
        strata[(s.source, organ_group(s.organ), s.language)].append(s)
    for key in strata:
        strata[key].sort(key=_stable_rank)

    ordered_keys = sorted(strata)
    chosen: list[TextSegment] = []
    max_len = max((len(v) for v in strata.values()), default=0)
    for idx in range(max_len):
        if len(chosen) >= n:
            break
        for k in ordered_keys:
            if idx < len(strata[k]):
                chosen.append(strata[k][idx])
                if len(chosen) >= n:
                    break
    return chosen


def write_annotation_template(segments: Iterable[TextSegment], path: Path) -> int:
    """Write a blank annotation template (empty ``assertions``) for curators. Returns count."""
    n = 0
    with Path(path).open("w", encoding="utf-8") as fh:
        for s in segments:
            obj = {
                "source": s.source,
                "source_id": s.source_id,
                "taxon": s.taxon.name_string,
                "organ": s.organ,
                "language": s.language,
                "text": s.text,
                "assertions": [],  # curator fills: po_id, pato_id, negated, value_*, unit, source_text
            }
            fh.write(json.dumps(obj, ensure_ascii=False) + "\n")
            n += 1
    return n


def _assertion_from_json(organ: str, d: dict) -> Assertion:
    return Assertion(
        po_id=d.get("po_id", ""),
        pato_id=d.get("pato_id", ""),
        negated=bool(d.get("negated", False)),
        negation_scope=d.get("negation_scope", "") or "",
        organ=d.get("organ", organ),
        source_text=d.get("source_text", ""),
        value_low=d.get("value_low"),
        value_high=d.get("value_high"),
        value_low_inclusive=d.get("value_low_inclusive", True),
        value_high_inclusive=d.get("value_high_inclusive", True),
        unit=d.get("unit", ""),
        value_text=d.get("value_text", ""),
        value_operator=d.get("value_operator", "atomic") or "atomic",
        value_term_ids=tuple(d.get("value_terms", []) or d.get("value_term_ids", []) or []),
        bearer_context_qualities=tuple(d.get("bearer_context_qualities", []) or []),
        developmental_stage_contexts=tuple(
            d.get("developmental_stage_contexts", []) or []
        ),
        developmental_stage_operator=(
            d.get("developmental_stage_operator", "atomic") or "atomic"
        ),
    )


def load_gold(path: Path) -> Iterator[tuple[str, list[Assertion]]]:
    """Yield (segment_text, [gold Assertion]) per annotated segment."""
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            organ = obj.get("organ", "")
            yield obj.get("text", ""), [
                _assertion_from_json(organ, a) for a in obj.get("assertions", [])
            ]
