"""Validate downloaded terminology evidence against its provenance manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path


REQUIRED_FIELDS = (
    "evidence_id",
    "title",
    "doi_or_identifier",
    "url",
    "local_file",
    "sha256",
    "access_status",
    "claims_verified",
    "verification_date",
)


def validate_evidence_manifest(path: Path, root: Path = Path(".")) -> dict[str, object]:
    """Fail closed when an evidence row or downloaded file is incomplete or changed."""
    with Path(path).open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing_columns = [field for field in REQUIRED_FIELDS if field not in (reader.fieldnames or ())]
        if missing_columns:
            raise ValueError(f"{path}: missing columns {', '.join(missing_columns)}")
        rows = list(reader)

    seen: set[str] = set()
    access_statuses: Counter[str] = Counter()
    total_bytes = 0
    for line_number, row in enumerate(rows, start=2):
        evidence_id = row["evidence_id"].strip()
        if not evidence_id or evidence_id in seen:
            raise ValueError(f"{path}:{line_number}: empty or duplicate evidence_id")
        seen.add(evidence_id)
        for field in ("title", "url", "local_file", "access_status", "claims_verified"):
            if not row[field].strip():
                raise ValueError(f"{path}:{line_number}: empty {field}")
        try:
            date.fromisoformat(row["verification_date"].strip())
        except ValueError as error:
            raise ValueError(
                f"{path}:{line_number}: invalid verification_date"
            ) from error

        expected_hash = row["sha256"].strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise ValueError(f"{path}:{line_number}: invalid sha256")
        local_path = Path(row["local_file"])
        if not local_path.is_absolute():
            local_path = Path(root) / local_path
        if not local_path.is_file():
            raise ValueError(f"{path}:{line_number}: missing local_file {local_path}")
        actual_hash = hashlib.sha256(local_path.read_bytes()).hexdigest()
        if actual_hash != expected_hash:
            raise ValueError(
                f"{path}:{line_number}: sha256 mismatch for {row['local_file']}"
            )
        total_bytes += local_path.stat().st_size
        access_statuses[row["access_status"].strip()] += 1

    return {
        "manifest": Path(path).as_posix(),
        "evidence_rows": len(rows),
        "verified_files": len(rows),
        "verified_bytes": total_bytes,
        "access_statuses": dict(sorted(access_statuses.items())),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "manifest",
        type=Path,
        nargs="?",
        default=Path("curation/botanical_evidence.tsv"),
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--summary-out", type=Path)
    args = parser.parse_args()
    rendered = (
        json.dumps(
            validate_evidence_manifest(args.manifest, args.root),
            indent=2,
            ensure_ascii=False,
        )
        + "\n"
    )
    if args.summary_out:
        args.summary_out.parent.mkdir(parents=True, exist_ok=True)
        args.summary_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
