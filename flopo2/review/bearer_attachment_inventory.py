"""Inventory for the bearer-attachment review campaign (curator decision 2026-09-18).

Targets are unresolved spans that the deterministic recovery passes block *only* because the
bearer cannot be attached syntactically:

* ``explicit_disjunction`` spans whose closed-table union passes every non-bearer guard of
  :mod:`flopo2.verify.recover_claude_explicit_disjunction` but whose residual reason is
  ``no_clause_head_bearer`` or ``unsafe_gap_between_head_and_union``;
* ``missing_or_unsupported_bearer`` spans that :mod:`flopo2.verify.recover_claude_missing_bearer`
  retains as ``no_clause_head_or_mapped_heading``, or whose head/heading/carry-over filler check
  is blocked by a nested organ cue (``bearer_cue:*``), where the clause names a sub-part head
  (lobes, lip, dorsal sepal, rachis, tube, disc).

For each target the runner derives the quality (fixed; never reviewed) and a closed candidate
list of bearer identifiers (organ mentions in the clause, reviewed sub-part composites such as
``lobes`` + calyx heading -> calyx lobe, the previous clause head, the record heading).  The
reviewer only picks one candidate identifier or ``hold``.  Spans whose bearer would be a
leaf/leaflet *surface* are listed separately and never reviewed here.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from flopo2.extract import baseline
from flopo2.verify import recover_claude_explicit_disjunction as disj
from flopo2.verify.recover_claude_missing_bearer import Recoverer

HOLD = "hold"
SCHEMA_VERSION = "flopo-bearer-attachment-item-v1"
DISJUNCTION_REASONS = frozenset({"no_clause_head_bearer", "unsafe_gap_between_head_and_union"})
MISSING_REASONS = frozenset(
    {
        "no_clause_head_or_mapped_heading",
        "unwhitelisted_head_to_span_filler",
        "heading_prefix_not_whitelisted",
        "carry_over_clause_prefix_not_whitelisted",
        "carry_over_previous_clause_not_whitelisted",
    }
)
RECEPTACLE = "PO_0009064"

# Sub-part heads named in the brief.  Each maps a parent organ family to the bearer class.
SUBPART_PATTERNS: dict[str, re.Pattern[str]] = {
    "lobe": re.compile(r"(?<![\w-])lob(?:e|es|us|i)(?![\w'’-])", re.IGNORECASE),
    "tube": re.compile(r"(?<![\w-])tubes?(?![\w'’-])", re.IGNORECASE),
    "lip": re.compile(
        r"(?<![\w-])(?:lips?|l[èe]vres?|labell(?:um|a|e|es))(?![\w'’-])", re.IGNORECASE
    ),
    "rachis": re.compile(r"(?<![\w-])(?:r(?:h)?achis|r(?:h)?achides)(?![\w'’-])", re.IGNORECASE),
    "disc": re.compile(r"(?<![\w-])(?:discs?|disks?|disques?)(?![\w'’-])", re.IGNORECASE),
    "sepal_position": re.compile(
        r"(?<![\w-])(?:(?:dorsal|lateral|median|upper|lower|outer|inner)\s+sepals?|"
        r"s[ée]pales?\s+(?:dorsa|lat[ée]ra|m[ée]dia|sup[ée]rieur|inf[ée]rieur|externe|interne)"
        r"\w*)(?![\w'’-])",
        re.IGNORECASE,
    ),
}
SEPAL = "PO_0009031"
CALYX, COROLLA, PERIANTH, FLOWER = "PO_0009060", "PO_0009059", "PO_0009058", "PO_0009046"
LEAF_IDS = frozenset({"PO_0025034", "PO_0009025", "PO_0020039", "PO_0025060"})
LEAFLET_IDS = frozenset({"PO_0020049", "FLOPO_0986002"})
INFLORESCENCE_IDS = frozenset(
    {"PO_0009049", "PO_0030123", "PO_0030115", "PO_0030117", "PO_0030129", "PO_0030124",
     "PO_0030128", "PO_0030121", "PO_0025601", "PO_0025598"}
)
CALYX_LOBE, COROLLA_LOBE, PERIANTH_LOBE = "FLOPO_0986005", "FLOPO_0986006", "FLOPO_0986004"
LEAF_LOBE = "PO_0025517"
COROLLA_TUBE, COROLLA_LIP, ORCHID_LABELLUM = "FLOPO_0985018", "FLOPO_0985017", "FLOPO_0980978"
LEAF_RACHIS, INFLORESCENCE_AXIS = "PO_0020055", "PO_0020122"

# Leaf/leaflet surface scope is implemented by another pass; such spans are only listed.
SURFACE_CUE = re.compile(
    r"(?<![\w-])(?:surfaces?|faces?|dessus|dessous|above|beneath|below|underneath|undersides?|"
    r"abaxial\w*|adaxial\w*|upper\s+sides?|lower\s+sides?|both\s+sides|on\s+the\s+back|"
    r"supra|subtus|en\s+dessus|en\s+dessous)(?![\w'’-])",
    re.IGNORECASE,
)
LEAF_WORD = re.compile(
    r"(?<![\w-])(?:leaf|leaves|leaflets?|lamina|laminae|blades?|feuilles?|folioles?|limbes?|"
    r"fronds?|pinnae?|pinnules?|pennes?)(?![\w'’-])",
    re.IGNORECASE,
)


# Relational adjectives naming the parent organ of a sub-part (``tube corollin``).
PARENT_ADJECTIVES = [
    ("PO_0009059", re.compile(r"(?<![\w-])corollin\w*", re.IGNORECASE)),
    ("PO_0009060", re.compile(r"(?<![\w-])calicin\w*|(?<![\w-])calycin\w*", re.IGNORECASE)),
    ("PO_0009058", re.compile(r"(?<![\w-])p[ée]rianthaire\w*", re.IGNORECASE)),
    ("PO_0009025", re.compile(r"(?<![\w-])foliaires?(?![\w-])", re.IGNORECASE)),
]
PREVIOUS_CLAUSES = 3


@dataclass(frozen=True)
class Mention:
    bearer_id: str
    start: int | None
    end: int | None
    surface: str
    basis: str


def _labels() -> dict[str, str]:
    labels: dict[str, str] = {}
    with Path("config/po_lexicon.tsv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            labels[row["id"]] = row["label"]
    with Path("config/flopo_id_registry.tsv").open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            local = row["flopo_iri"].rsplit("/", 1)[-1]
            labels.setdefault(local, row["label"])
    return labels


def _pato_labels() -> dict[str, str]:
    with Path("config/pato_lexicon.tsv").open(encoding="utf-8", newline="") as handle:
        return {row["id"]: row["label"] for row in csv.DictReader(handle, delimiter="\t")}


class CandidateBuilder:
    """Closed bearer candidate lists from explicit mentions, composites and headings."""

    def __init__(self, recoverer: Recoverer, labels: dict[str, str]) -> None:
        self.recoverer = recoverer
        self.labels = labels
        disj._BEARER_PATTERNS = disj._BEARER_PATTERNS or disj._bearer_patterns()
        if disj._PO_EXACT_HEADS is None:
            disj._PO_EXACT_HEADS = disj._load_po_exact_heads()
        self.extra = [
            *((po, pattern, "disjunction_head_cue") for po, pattern in disj._BEARER_PATTERNS),
            *((po, pattern, "contextual_cue") for po, pattern, _ in baseline.CONTEXTUAL_BEARER_PATTERNS),
        ]
        self.label_pattern = re.compile(r"[A-Za-z]+(?:[- ][A-Za-z]+){0,2}")

    def known(self, bearer_id: str) -> bool:
        return bearer_id in self.recoverer.po_ids or bearer_id in self.recoverer.flopo_ids

    def mentions(self, record: dict[str, Any], start: int, end: int) -> list[Mention]:
        """Explicit organ mentions in ``text[start:end]`` (longest match per start offset)."""

        text = str(record.get("text", "") or "")
        found: dict[tuple[int, str], Mention] = {}

        def add(bearer_id: str, m_start: int, m_end: int, basis: str) -> None:
            if bearer_id == RECEPTACLE or not self.known(bearer_id):
                return
            surface = text[m_start:m_end]
            if disj._LEAF_SCOPED_ONLY.match(surface):
                organ_po = baseline._organ_to_po(str(record.get("organ", "") or ""))
                if organ_po in disj._LEAF_RECORD_BEARERS:
                    bearer_id = "PO_0020039"
                elif surface.casefold().startswith("lamina"):
                    bearer_id = "PO_0025060"
                else:
                    return
            if bearer_id == "PO_0025324":
                family = str(record.get("taxon_family", "") or "").casefold()
                if family not in disj.PAPILIONOID_FAMILIES:
                    return
            key = (m_start, bearer_id)
            previous = found.get(key)
            if previous is None or (previous.end or 0) < m_end:
                found[key] = Mention(bearer_id, m_start, m_end, surface, basis)

        for entry in self.recoverer.heads:
            if not self.recoverer._entry_applies(entry, record):
                continue
            for match in entry.pattern.finditer(text, start, end):
                if match.end() > match.start():
                    add(entry.po_id, match.start(), match.end(), entry.source)
        for po_id, pattern, basis in self.extra:
            for match in pattern.finditer(text, start, end):
                add(po_id, match.start(), match.end(), basis)
        if str(record.get("language", "")) == "en":
            for match in re.finditer(r"[A-Za-z]+", text[start:end]):
                m_start = start + match.start()
                phrase = self.label_pattern.match(text, m_start, end)
                if not phrase:
                    continue
                words = re.split(r"([- ])", phrase.group(0))
                for count in range((len(words) + 1) // 2, 0, -1):
                    chunk = "".join(words[: 2 * count - 1])
                    for form in disj._singulars(disj._norm(chunk)):
                        ids = disj._PO_EXACT_HEADS.get(form)
                        if ids and len(ids) == 1 and form not in disj.GENERIC_PO_HEADS:
                            add(next(iter(ids)), m_start, m_start + len(chunk), "po_exact_label")
                            break
                    else:
                        continue
                    break
        # Drop mentions strictly contained in a longer mention of another id at the same text.
        rows = sorted(found.values(), key=lambda m: (m.start or 0, -(m.end or 0)))
        kept: list[Mention] = []
        for mention in rows:
            if any(
                (other.start or 0) <= (mention.start or 0)
                and (mention.end or 0) <= (other.end or 0)
                and ((other.end or 0) - (other.start or 0)) > ((mention.end or 0) - (mention.start or 0))
                for other in kept
            ):
                continue
            kept.append(mention)
        return kept

    def heading(self, record: dict[str, Any]) -> Mention | None:
        bearer = self.recoverer.heading_bearer(record)
        if bearer is None or bearer.po_id == RECEPTACLE or not self.known(bearer.po_id):
            return None
        return Mention(bearer.po_id, None, None, bearer.surface, "record_heading")

    def previous_clause_head(self, record: dict[str, Any], clause_start: int) -> Mention | None:
        """Nearest head of up to three preceding ``;`` clauses of the same sentence."""

        text = str(record.get("text", "") or "")
        position = clause_start
        for _ in range(PREVIOUS_CLAUSES):
            if position <= 1 or text[position - 1] != ";":
                return None
            previous, previous_start = baseline._clause_at(text, position - 1)
            if not previous.strip():
                return None
            head = self.recoverer.clause_head(record, previous, previous_start)
            if head is not None:
                if head.po_id == RECEPTACLE or not self.known(head.po_id):
                    return None
                return Mention(head.po_id, head.start, head.end, head.surface, "previous_clause_head")
            position = previous_start
        return None

    def parent_adjectives(self, record: dict[str, Any], start: int, end: int) -> list[Mention]:
        text = str(record.get("text", "") or "")
        return [
            Mention(po_id, match.start(), match.end(), match.group(0), "parent_adjective")
            for po_id, pattern in PARENT_ADJECTIVES
            for match in pattern.finditer(text, start, end)
        ]

    def composites(
        self, record: dict[str, Any], window_start: int, window_end: int, parents: list[Mention]
    ) -> tuple[list[Mention], list[str]]:
        """Sub-part heads in the window combined with parent organs (reviewed composite table)."""

        text = str(record.get("text", "") or "")
        family = str(record.get("taxon_family", "") or "").casefold()
        parent_ids = {mention.bearer_id for mention in parents}
        out: list[Mention] = []
        named: list[str] = []
        for kind, pattern in SUBPART_PATTERNS.items():
            for match in pattern.finditer(text, window_start, window_end):
                named.append(kind)
                span = (match.start(), match.end(), match.group(0))
                targets: list[str] = []
                if kind == "lobe":
                    if CALYX in parent_ids:
                        targets.append(CALYX_LOBE)
                    if COROLLA in parent_ids:
                        targets.append(COROLLA_LOBE)
                    if PERIANTH in parent_ids:
                        targets.append(PERIANTH_LOBE)
                    if parent_ids & LEAF_IDS:
                        targets.append(LEAF_LOBE)
                    if FLOWER in parent_ids and not targets:
                        targets.extend([CALYX_LOBE, COROLLA_LOBE, PERIANTH_LOBE])
                elif kind == "tube":
                    if COROLLA in parent_ids or FLOWER in parent_ids:
                        targets.append(COROLLA_TUBE)
                elif kind == "lip":
                    if family == "orchidaceae":
                        targets.append(ORCHID_LABELLUM)
                    elif COROLLA in parent_ids or FLOWER in parent_ids:
                        targets.append(COROLLA_LIP)
                elif kind == "rachis":
                    if parent_ids & (LEAF_IDS | LEAFLET_IDS):
                        targets.append(LEAF_RACHIS)
                    if parent_ids & INFLORESCENCE_IDS:
                        targets.append(INFLORESCENCE_AXIS)
                    if not targets:
                        targets.extend([LEAF_RACHIS, INFLORESCENCE_AXIS])
                elif kind == "sepal_position":
                    targets.append(SEPAL)
                for target in targets:
                    if self.known(target):
                        out.append(Mention(target, span[0], span[1], span[2], f"subpart_composite:{kind}"))
        return out, named

    def candidates(
        self,
        record: dict[str, Any],
        clause_start: int,
        value_start: int,
        value_end: int,
        member_end: int,
    ) -> dict[str, Any]:
        """Closed candidate list plus diagnostics (subparts named, surface scope)."""

        text = str(record.get("text", "") or "")
        in_clause = self.mentions(record, clause_start, value_start)
        after = self.mentions(record, value_end, member_end)
        previous = self.previous_clause_head(record, clause_start)
        heading = self.heading(record)
        parents = [
            *in_clause,
            *self.parent_adjectives(record, clause_start, value_start),
            *([previous] if previous else []),
            *([heading] if heading else []),
        ]
        composites, named = self.composites(record, clause_start, value_start, parents)
        ordered: list[Mention] = [*composites, *in_clause, *after]
        if previous:
            ordered.append(previous)
        if heading:
            ordered.append(heading)
        seen: dict[str, dict[str, Any]] = {}
        for mention in ordered:
            row = seen.get(mention.bearer_id)
            evidence = {
                "surface": mention.surface,
                "start": mention.start,
                "end": mention.end,
                "basis": mention.basis,
            }
            if row is None:
                seen[mention.bearer_id] = {
                    "bearer_id": mention.bearer_id,
                    "label": self.labels.get(mention.bearer_id, mention.bearer_id),
                    "evidence": [evidence],
                }
            elif evidence not in row["evidence"]:
                row["evidence"].append(evidence)
        scope_text = text[clause_start:member_end]
        leafy = bool(LEAF_WORD.search(scope_text)) or any(
            m.bearer_id in LEAF_IDS | LEAFLET_IDS for m in parents
        )
        surface = bool(SURFACE_CUE.search(scope_text)) and leafy
        return {"candidates": list(seen.values()), "subparts_named": sorted(set(named)), "leaf_surface": surface}


def _member_end(text: str, end: int, clause_end: int) -> int:
    match = re.compile(r"[,;:()\[\]]|\.(?:\s|$)").search(text, end, clause_end)
    return match.start() if match else clause_end


def _key(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": record.get("source"),
        "source_id": record.get("source_id"),
        "source_segment_index": record.get("source_segment_index"),
        "taxon": record.get("taxon"),
        "organ": record.get("organ"),
        "char_start": record.get("char_start"),
        "char_end": record.get("char_end"),
    }


def item_id(key: dict[str, Any], kind: str, start: int, end: int) -> str:
    payload = json.dumps([key, kind, start, end], sort_keys=True, ensure_ascii=False)
    return "bearer_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def _window(text: str, start: int, end: int, before: int = 260, after: int = 120) -> str:
    left = max(0, start - before)
    return (
        ("…" if left else "")
        + text[left:start]
        + "⟦"
        + text[start:end]
        + "⟧"
        + text[end : end + after]
        + ("…" if end + after < len(text) else "")
    )


def disjunction_items(
    record: dict[str, Any], builder: CandidateBuilder, pato_labels: dict[str, str]
) -> Iterator[tuple[str, dict[str, Any]]]:
    text = str(record.get("text", "") or "")
    unions: dict[tuple[int, int], dict[str, Any]] = {}
    for span in record.get("unresolved_spans", []) or []:
        if span.get("reason") != disj.TARGET_REASON:
            continue
        start, end = int(span["start"]), int(span["end"])
        candidate, reason = disj.find_candidate(record, start, end)
        if candidate is not None or reason not in DISJUNCTION_REASONS:
            continue
        union, why = disj.find_candidate(record, start, end, bearerless=True)
        if union is None:
            yield "residual", {"origin": f"explicit_disjunction:{reason}", "blocked": why}
            continue
        if not any(op.start <= start and end <= op.end for op in union.operands):
            yield "residual", {"origin": f"explicit_disjunction:{reason}", "blocked": "span_outside_operands"}
            continue
        entry = unions.setdefault((union.start, union.end), {"union": union, "spans": [], "reasons": set()})
        entry["spans"].append(span)
        entry["reasons"].add(reason)
    for (u_start, u_end), entry in sorted(unions.items()):
        union = entry["union"]
        if disj._overlaps_existing(record, union):
            for _ in entry["spans"]:
                yield "residual", {"origin": "explicit_disjunction", "blocked": "overlaps_existing_assertion"}
            continue
        clause_end = union.clause_end
        member_end = _member_end(text, u_end, clause_end)
        info = builder.candidates(record, union.clause_start, u_start, u_end, member_end)
        key = _key(record)
        item = {
            "schema_version": SCHEMA_VERSION,
            "item_id": item_id(key, "one_of", u_start, u_end),
            "target_kind": "explicit_disjunction_union",
            "origin_reasons": sorted(entry["reasons"]),
            "key": key,
            "language": record.get("language", ""),
            "taxon_family": record.get("taxon_family", ""),
            "value_start": u_start,
            "value_end": u_end,
            "value_text": text[u_start:u_end],
            "quality": {
                "attribute_id": disj.ATTRIBUTE_BY_SUBFAMILY[union.subfamily],
                "attribute_label": pato_labels.get(disj.ATTRIBUTE_BY_SUBFAMILY[union.subfamily], ""),
                "value_operator": "one_of",
                "value_terms": [op.pato_id for op in union.operands],
                "value_labels": [pato_labels.get(op.pato_id, op.pato_id) for op in union.operands],
                "subfamily": union.subfamily,
            },
            "clause_start": union.clause_start,
            "clause_end": clause_end,
            "clause": text[union.clause_start:clause_end].strip(),
            "context": _window(text, u_start, u_end),
            "record_heading": record.get("organ", ""),
            "spans": [
                {"start": s["start"], "end": s["end"], "reason": s["reason"],
                 "surface_form": s.get("surface_form", "")}
                for s in entry["spans"]
            ],
            **info,
        }
        yield "item", item


def missing_bearer_items(
    record: dict[str, Any], builder: CandidateBuilder, pato_labels: dict[str, str]
) -> Iterator[tuple[str, dict[str, Any]]]:
    text = str(record.get("text", "") or "")
    recoverer = builder.recoverer
    for span in record.get("unresolved_spans", []) or []:
        if span.get("reason") != "missing_or_unsupported_bearer":
            continue
        assertion, reason, _bearer = recoverer.evaluate(record, span)
        if assertion is not None or reason not in MISSING_REASONS:
            continue
        if reason != "no_clause_head_or_mapped_heading" and not recoverer.last_block.startswith(
            "bearer_cue:"
        ):
            continue
        start, end = int(span["start"]), int(span["end"])
        clause, clause_start = baseline._clause_at(text, start)
        clause_end = clause_start + len(clause)
        member_end = _member_end(text, end, clause_end)
        info = builder.candidates(record, clause_start, start, end, member_end)
        if not info["subparts_named"]:
            continue
        quality = str(span.get("candidate_pato_id", "") or "")
        key = _key(record)
        yield "item", {
            "schema_version": SCHEMA_VERSION,
            "item_id": item_id(key, "atomic", start, end),
            "target_kind": "missing_bearer_quality",
            "origin_reasons": [reason],
            "key": key,
            "language": record.get("language", ""),
            "taxon_family": record.get("taxon_family", ""),
            "value_start": start,
            "value_end": end,
            "value_text": text[start:end],
            "quality": {
                "attribute_id": quality,
                "attribute_label": pato_labels.get(quality, quality),
                "value_operator": "atomic",
                "value_terms": [],
                "value_labels": [],
                "subfamily": "",
            },
            "clause_start": clause_start,
            "clause_end": clause_end,
            "clause": clause.strip(),
            "context": _window(text, start, end),
            "record_heading": record.get("organ", ""),
            "spans": [
                {"start": span["start"], "end": span["end"], "reason": span["reason"],
                 "surface_form": span.get("surface_form", "")}
            ],
            **info,
        }


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def build_inventory(stage: Path, out_dir: Path, *, limit: int | None = None) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    builder = CandidateBuilder(Recoverer.from_config(), _labels())
    pato_labels = _pato_labels()
    counts: Counter[str] = Counter()
    with (
        (out_dir / "inventory.jsonl").open("w", encoding="utf-8") as items_out,
        (out_dir / "surface-skipped.jsonl").open("w", encoding="utf-8") as surface_out,
        (out_dir / "no-candidate.jsonl").open("w", encoding="utf-8") as none_out,
    ):
        for index, record in enumerate(iter_jsonl(stage)):
            if limit is not None and index >= limit:
                break
            for producer in (disjunction_items, missing_bearer_items):
                for status, row in producer(record, builder, pato_labels):
                    if status == "residual":
                        counts[f"residual:{row['origin']}:{row['blocked']}"] += 1
                        continue
                    kind = row["target_kind"]
                    spans = len(row["spans"])
                    counts[f"{kind}:spans"] += spans
                    if row["leaf_surface"]:
                        counts[f"{kind}:leaf_surface_skipped_spans"] += spans
                        surface_out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    elif not row["candidates"]:
                        counts[f"{kind}:no_candidate_spans"] += spans
                        none_out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    else:
                        counts[f"{kind}:items"] += 1
                        counts[f"{kind}:item_spans"] += spans
                        items_out.write(json.dumps(row, ensure_ascii=False) + "\n")
    report = {"stage": str(stage), "counts": dict(sorted(counts.items()))}
    (out_dir / "inventory-report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("stage", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    print(json.dumps(build_inventory(args.stage, args.out_dir, limit=args.limit), indent=2))


if __name__ == "__main__":
    main()
