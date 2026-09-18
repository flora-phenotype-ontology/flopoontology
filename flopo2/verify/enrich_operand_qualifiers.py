"""Attach per-operand degree qualifiers to stage assertions whose cue the old enum could not hold.

Before schema extension E2 the DegreeQualifier enum had no density/width/extent/texture/depth
values, so a cue such as ``± densely``, ``very sparsely`` or ``usually densely`` kept only its
approximation, intensity or frequency part at assertion level and the density word survived only
in ``modality_text``.  This pass writes a *correction* delta whose ``update_assertions`` entries
add ``value_operands`` to exactly those assertions:

* the operand covers ``<degree cue> <value>`` (``very sparsely pubescent``) and its qualifier cue
  is the degree phrase nearest the value (``very sparsely``, degree ``sparsely``);
* the operand value is the assertion's categorical value, verified against the closed baseline
  cue that matches the operand head; unions are split at ``or``/``ou`` and every operand head
  must match its value term in source order;
* density degrees are admitted only on pilosity/branching values (a density word before a colour,
  ``densely brown``, describes an indumentum colour and is reported, not enriched);
* assertion-level qualifiers, the source span and the FAC identity are unchanged (operands are
  provenance only; the applier re-checks the FAC IRI).

Assertions removed by an earlier correction delta are skipped, so the delta composes with the
stage-23 manifest.

    python -m flopo2.verify.enrich_operand_qualifiers BASE -o DELTA --report REPORT \
        --skip-correction scratchpad/.../correction-delta.jsonl [...]
"""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any

from flopo2.annotation.operands import DEGREE_AXIS, DEGREE_CUES, make_operand
from flopo2.extract import baseline

PROVENANCE = "operand_qualifiers:E2:enum_extension_enrichment"
FINE_AXES = frozenset({"width", "density", "extent", "texture", "depth"})
BRANCHED = "PATO_0000402"
_BRANCHED_FORM = re.compile(r"^(?:branched|ramifi[ée]e?s?)$", re.IGNORECASE)
_INTENSITY = r"(?:(?:very|rather|quite|très|tres|assez)\s+)?"
_FINE_CUES = sorted(
    (cue for cue, degree in DEGREE_CUES.items() if DEGREE_AXIS.get(degree) in FINE_AXES and cue != "peu"),
    key=len,
    reverse=True,
)
_DEGREE_PHRASE = re.compile(
    _INTENSITY + r"(?P<cue>" + "|".join(re.escape(cue) for cue in _FINE_CUES) + r")\b",
    re.IGNORECASE,
)
_CONNECTOR = re.compile(r"\s+(?:or|ou)\s+", re.IGNORECASE)
_FAMILY_BY_AXIS = {"density": {"pilosity", "branching"}, "texture": {"pilosity"},
                   "extent": {"pilosity"}, "width": {"shape"}, "depth": {"shape"}}
REMOVE_FIELDS = ("source_statement_id", "po_id", "pato_id", "source_start", "source_end")


def _identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(name) for name in REMOVE_FIELDS)


def _family(pato_id: str) -> str:
    if pato_id == BRANCHED:
        return "branching"
    return baseline.QUALITY_FAMILY.get(pato_id, "")


def _head_matches(surface: str, pato_id: str) -> bool:
    surface = surface.strip()
    if pato_id == BRANCHED:
        return bool(_BRANCHED_FORM.fullmatch(surface))
    return any(
        cue.pato_id == pato_id and cue.pattern.fullmatch(surface)
        for cue in baseline.QUALITY_PATTERNS
    )


def enrich(assertion: dict[str, Any], text: str) -> tuple[list[dict[str, Any]] | None, str]:
    """Return the operand list for one assertion, or ``(None, reason)``."""

    if assertion.get("qualitative_value_relation") or assertion.get("value_operands"):
        return None, "not_applicable"
    cue = str(assertion.get("modality_text", "") or "")
    m_start, m_end = assertion.get("modality_start"), assertion.get("modality_end")
    s_start, s_end = assertion.get("source_start"), assertion.get("source_end")
    if not cue or not all(isinstance(v, int) for v in (m_start, m_end, s_start, s_end)):
        return None, "no_anchored_cue"
    phrase = None
    for match in _DEGREE_PHRASE.finditer(text, m_start, m_end):
        phrase = match
    if phrase is None:
        return None, "no_fine_degree_cue"
    if phrase.end() != m_end:
        return None, "degree_not_adjacent_to_value"
    degree = DEGREE_CUES[phrase.group("cue").lower()]
    operator = assertion.get("value_operator", "atomic") or "atomic"
    terms = list(assertion.get("value_terms", []) or [])
    values = terms if operator != "atomic" else (terms or [assertion.get("pato_id", "")])
    if operator == "all_of":
        return None, "conjunction_not_supported"
    rest_start = m_end + (len(text[m_end:s_end]) - len(text[m_end:s_end].lstrip()))
    pieces: list[tuple[int, int]] = []
    cursor = rest_start
    if operator == "one_of":
        for match in _CONNECTOR.finditer(text, rest_start, s_end):
            pieces.append((cursor, match.start()))
            cursor = match.end()
    pieces.append((cursor, s_end))
    if len(pieces) != len(values):
        return None, "operand_count_mismatch"
    for (start, end), value in zip(pieces, values):
        if not _head_matches(text[start:end], value):
            return None, "operand_head_not_verified"
    if _family(values[0]) not in _FAMILY_BY_AXIS.get(DEGREE_AXIS[degree], set()):
        return None, f"degree_{DEGREE_AXIS[degree]}_on_{_family(values[0]) or 'other'}_value"
    operands = []
    for index, ((start, end), value) in enumerate(zip(pieces, values)):
        if index == 0:
            operands.append(
                make_operand(
                    0,
                    value,
                    text,
                    phrase.start(),
                    end,
                    qualifier_start=phrase.start(),
                    qualifier_end=phrase.end(),
                    degree_qualifier=degree,
                )
            )
        else:
            operands.append(make_operand(index, value, text, start, end))
    return operands, ""


def _removed_identities(paths: list[Path]) -> set[tuple[Any, ...]]:
    removed: set[tuple[Any, ...]] = set()
    for path in paths:
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    key = tuple(row["key"].get(name) for name in (
                        "source", "source_id", "source_segment_index", "taxon", "organ",
                        "char_start", "char_end"))
                    for removal in row.get("remove_assertions", []) or []:
                        removed.add((key, _identity(removal)))
    return removed


def run(base: Path, output: Path, skip: list[Path]) -> dict[str, Any]:
    removed = _removed_identities(skip)
    counts: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    output.parent.mkdir(parents=True, exist_ok=True)
    with Path(base).open(encoding="utf-8") as source, output.open("w", encoding="utf-8") as out:
        for line in source:
            record = json.loads(line)
            text = str(record.get("text", "") or "")
            key = {name: record.get(name) for name in (
                "source", "source_id", "source_segment_index", "taxon", "organ",
                "char_start", "char_end")}
            key_tuple = tuple(key.values())
            updates = []
            for assertion in record.get("assertions", []) or []:
                cue = str(assertion.get("modality_text", "") or "")
                if not cue or not _DEGREE_PHRASE.search(cue):
                    continue
                counts["candidates"] += 1
                if (key_tuple, _identity(assertion)) in removed:
                    counts["skipped:removed_by_earlier_correction"] += 1
                    continue
                operands, reason = enrich(assertion, text)
                if operands is None:
                    counts[f"skipped:{reason}"] += 1
                    rows.append({"status": "skipped", "reason": reason,
                                 "source_text": assertion.get("source_text", "")})
                    continue
                counts["enriched"] += 1
                counts[f"degree:{operands[0]['degree_qualifier']}"] += 1
                updates.append(
                    {
                        **{name: assertion.get(name) for name in REMOVE_FIELDS},
                        "set": {"value_operands": operands},
                        "add_mapping_provenance": [PROVENANCE],
                    }
                )
                rows.append({"status": "enriched", "key": key, "po_id": assertion.get("po_id"),
                             "source_text": assertion.get("source_text", ""),
                             "modality_text": cue,
                             "assertion_level": {k: assertion.get(k) for k in (
                                 "degree_qualifier", "value_qualifier", "frequency_qualifier")},
                             "operands": operands})
            if updates:
                out.write(json.dumps({"key": key, "update_assertions": updates},
                                     ensure_ascii=False) + "\n")
                counts["delta_lines"] += 1
    return {"base": str(base), "output": str(output), "counts": dict(sorted(counts.items())),
            "rows": rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("base", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--audit-sample", type=Path, help="seeded review sample TSV to write")
    parser.add_argument("--sample-size", type=int, default=60)
    parser.add_argument("--seed", type=int, default=20260918)
    parser.add_argument("--skip-correction", type=Path, action="append", default=[])
    args = parser.parse_args()
    report = run(args.base, args.output, args.skip_correction)
    rows = report.pop("rows")
    if args.report:
        args.report.write_text(
            json.dumps({**report, "rows": rows}, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
    if args.audit_sample:
        enriched = [row for row in rows if row["status"] == "enriched"]
        sample = random.Random(args.seed).sample(enriched, min(args.sample_size, len(enriched)))
        with args.audit_sample.open("w", encoding="utf-8") as handle:
            handle.write("source_text\tmodality_text\tassertion_level\toperands\tverdict\tnote\n")
            for row in sample:
                operands = " | ".join(
                    f"{op['text']}={op['value']}[{op['degree_qualifier']};cue={op.get('qualifier_text', '')}]"
                    for op in row["operands"]
                )
                handle.write(
                    f"{row['source_text']}\t{row['modality_text']}\t"
                    f"{json.dumps(row['assertion_level'])}\t{operands}\t\t\n"
                )
    print(json.dumps(report["counts"], indent=1))


if __name__ == "__main__":
    main()
