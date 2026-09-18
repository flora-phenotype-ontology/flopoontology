"""Project represented OWL disjunction assertions from a gated flora JSONL artifact."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from flopo2.annotation.provenance import ensure_source_statements


def project_disjunctions(input_path: Path, output_path: Path) -> dict[str, object]:
    """Retain every ``one_of`` assertion and exactly its supporting source statements."""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = assertions = 0
    statuses: Counter[str] = Counter()
    attributes: Counter[str] = Counter()
    arities: Counter[int] = Counter()
    with Path(input_path).open(encoding="utf-8") as source, output_path.open(
        "w", encoding="utf-8"
    ) as output:
        for line in source:
            if not line.strip():
                continue
            record = ensure_source_statements(json.loads(line))
            selected = [
                assertion
                for assertion in record.get("assertions", []) or []
                if (assertion.get("value_operator", "atomic") or "atomic") == "one_of"
            ]
            if not selected:
                continue
            statement_ids = {
                assertion.get("source_statement_id", "") for assertion in selected
            }
            record["assertions"] = selected
            record["source_statements"] = [
                statement
                for statement in record.get("source_statements", []) or []
                if statement.get("statement_id", "") in statement_ids
            ]
            # This is a represented-disjunction projection. Unresolved evidence remains in the
            # complete source artifact and is intentionally not duplicated here.
            record["unresolved_spans"] = []
            record["term_mentions"] = []
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            records += 1
            assertions += len(selected)
            for assertion in selected:
                statuses[(assertion.get("gate") or {}).get("status", "unvalidated")] += 1
                attributes[str(assertion.get("pato_id", ""))] += 1
                arities[len(set(assertion.get("value_terms", []) or []))] += 1

    return {
        "input": str(input_path),
        "output": str(output_path),
        "records": records,
        "assertions": assertions,
        "gate_statuses": dict(sorted(statuses.items())),
        "attributes": dict(sorted(attributes.items())),
        "arities": {str(key): value for key, value in sorted(arities.items())},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(project_disjunctions(args.input, args.output), indent=2))


if __name__ == "__main__":
    main()
