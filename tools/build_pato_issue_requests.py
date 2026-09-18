#!/usr/bin/env python3
"""Generate one GitHub issue body per FLOPO value candidate for PATO requests."""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def issue_body(row: dict) -> str:
    parents = []
    ids = [x for x in row["suggested_parent_pato_ids"].split("|") if x]
    labels = [x for x in row["suggested_parent_pato_labels"].split("|") if x]
    for pid, label in zip(ids, labels):
        parents.append(f"- `{pid}` {label}")
    parent_text = "\n".join(parents) if parents else "- needs curator decision"
    definition = (
        f"A phenotype value denoting {row['value_label']}, observed in botanical flora "
        "descriptions."
    )
    return f"""Request to add a PATO value term used in botanical phenotype annotation.

Proposed label:
`{row['value_label']}`

Proposed definition:
{definition}

Suggested parent class(es):
{parent_text}

Evidence from FLOPO rebuild:
- Frequency in current FLOPO candidate set: {row['frequency']}
- Contexts: {row['quality_contexts']}
- Examples: {row['examples']}

Rationale:
This value is currently needed as a categorical phenotype value in FLOPO v2. FLOPO will mint a local extension class temporarily, but it would be preferable to ground this directly to PATO if accepted.

Source workflow:
Generated from FLOPO value candidate table using PATO OBO as parent lookup.
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=Path, default=Path("scratchpad/flopo-value-candidates.tsv"))
    ap.add_argument("--out-dir", type=Path, default=Path("scratchpad/pato-issues"))
    ap.add_argument("--submit-script", type=Path, default=Path("scratchpad/create-pato-issues.sh"))
    ap.add_argument("--status", default="candidate")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    with args.candidates.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row["status"] != args.status:
                continue
            if not row["suggested_parent_pato_ids"]:
                continue
            rows.append(row)

    script_lines = ["#!/usr/bin/env bash", "set -euo pipefail", ""]
    for idx, row in enumerate(rows, start=1):
        filename = f"{idx:03d}-{slug(row['value_label'])}.md"
        path = args.out_dir / filename
        path.write_text(issue_body(row), encoding="utf-8")
        title = f"Add botanical phenotype value term: {row['value_label']}"
        script_lines.append(
            "gh issue create --repo pato-ontology/pato "
            f"--title {title!r} "
            f"--body-file {str(path)!r} "
            "--label term-request"
        )
    args.submit_script.write_text("\n".join(script_lines) + "\n", encoding="utf-8")
    args.submit_script.chmod(0o755)
    print(f"wrote {len(rows)} issue bodies to {args.out_dir}")
    print(f"submit script {args.submit_script}")


if __name__ == "__main__":
    main()
