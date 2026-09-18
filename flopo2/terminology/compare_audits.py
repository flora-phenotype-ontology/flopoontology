"""Compare independently generated botanical audit decisions surface by surface."""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

from flopo2.terminology.normalize import fold
from flopo2.terminology.validate_audit import read_proposal_tsv


OBO_ID = re.compile(r"\b(PO|PATO|FLOPO)_([0-9]{7})\b")


@dataclass(frozen=True)
class Decision:
    outcome: str
    target: str
    confidence: str

    @property
    def signature(self) -> tuple[str, str]:
        return self.outcome, self.target


def _mapping_decision(row: dict[str, str]) -> Decision:
    return Decision(
        outcome=f"mapping:{row.get('predicate_id', '').strip()}",
        target=OBO_ID.sub(r"\1:\2", row.get("object_id", "").strip()),
        confidence=row.get("confidence", "").strip(),
    )


def _gap_decision(row: dict[str, str]) -> Decision:
    intended = row.get("intended_ontology", "").strip()
    label = row.get("proposed_label", "").strip()
    return Decision(
        outcome=f"gap:{row.get('decision', '').strip()}",
        target=": ".join(value for value in (intended, label) if value),
        confidence=row.get("confidence", "").strip(),
    )


def load_run_decisions(run_dir: Path) -> dict[str, Decision]:
    decisions: dict[str, Decision] = {}
    sources = (
        ("06-mapping-proposals.sssom.tsv", "subject_label", _mapping_decision),
        ("06-new-class-or-noise.tsv", "surface_form", _gap_decision),
    )
    for filename, surface_field, converter in sources:
        _fields, rows, _metadata = read_proposal_tsv(run_dir / filename)
        for row in rows:
            surface = fold(row.get(surface_field, ""))
            if not surface:
                raise ValueError(f"{run_dir}/{filename}: empty normalized surface")
            if surface in decisions:
                raise ValueError(f"{run_dir}: duplicate decision for normalized surface {surface!r}")
            decisions[surface] = converter(row)
    return decisions


def baseline_surfaces(path: Path) -> dict[str, int]:
    data = json.loads(path.read_text(encoding="utf-8"))
    values = data.get("unresolved", {}).get("missing_surfaces", [])
    return {fold(str(surface)): int(frequency) for surface, frequency in values}


def compare_runs(
    run_dirs: list[Path], baseline_manifest: Path
) -> tuple[list[dict[str, str | int]], dict[str, int]]:
    expected = baseline_surfaces(baseline_manifest)
    run_decisions = [load_run_decisions(run_dir) for run_dir in run_dirs]
    rows: list[dict[str, str | int]] = []
    summary = {"unanimous": 0, "disagreement": 0, "incomplete": 0}

    for surface, frequency in sorted(expected.items(), key=lambda item: (-item[1], item[0])):
        decisions = [run.get(surface) for run in run_decisions]
        present = [decision for decision in decisions if decision is not None]
        if len(present) != len(run_dirs):
            agreement = "incomplete"
        elif len({decision.signature for decision in present}) == 1:
            agreement = "unanimous"
        else:
            agreement = "disagreement"
        summary[agreement] += 1

        row: dict[str, str | int] = {
            "surface_form": surface,
            "corpus_frequency": frequency,
            "agreement": agreement,
        }
        for index, decision in enumerate(decisions, start=1):
            prefix = f"run_{index:02d}"
            row[f"{prefix}_outcome"] = decision.outcome if decision else ""
            row[f"{prefix}_target"] = decision.target if decision else ""
            row[f"{prefix}_confidence"] = decision.confidence if decision else ""
        rows.append(row)
    summary["total"] = len(rows)
    return rows, summary


def write_comparison(path: Path, rows: list[dict[str, str | int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError("comparison has no rows")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", type=Path, nargs="+")
    parser.add_argument("--baseline-manifest", type=Path, required=True)
    parser.add_argument("-o", "--out", type=Path, required=True)
    parser.add_argument("--summary-out", type=Path)
    args = parser.parse_args()

    rows, summary = compare_runs(args.run_dirs, args.baseline_manifest)
    write_comparison(args.out, rows)
    rendered = json.dumps(summary, indent=2, ensure_ascii=False) + "\n"
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
