from __future__ import annotations

import csv
import hashlib

import pytest

from flopo2.terminology.evidence import REQUIRED_FIELDS, validate_evidence_manifest


def _write_manifest(path, row):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_FIELDS, delimiter="\t")
        writer.writeheader()
        writer.writerow(row)


def test_evidence_manifest_verifies_download_hash_and_date(tmp_path):
    evidence_file = tmp_path / "source.pdf"
    evidence_file.write_bytes(b"verified evidence")
    manifest = tmp_path / "evidence.tsv"
    _write_manifest(
        manifest,
        {
            "evidence_id": "EVID:test",
            "title": "Test source",
            "doi_or_identifier": "DOI:10.1/test",
            "url": "https://example.org/test",
            "local_file": evidence_file.name,
            "sha256": hashlib.sha256(evidence_file.read_bytes()).hexdigest(),
            "access_status": "public",
            "claims_verified": "The source supports the test claim.",
            "verification_date": "2026-07-15",
        },
    )

    summary = validate_evidence_manifest(manifest, tmp_path)

    assert summary["evidence_rows"] == 1
    assert summary["verified_files"] == 1
    assert summary["verified_bytes"] == len(b"verified evidence")


def test_evidence_manifest_rejects_changed_download(tmp_path):
    evidence_file = tmp_path / "source.html"
    evidence_file.write_text("changed", encoding="utf-8")
    manifest = tmp_path / "evidence.tsv"
    _write_manifest(
        manifest,
        {
            "evidence_id": "EVID:test",
            "title": "Test source",
            "doi_or_identifier": "TEST:1",
            "url": "https://example.org/test",
            "local_file": evidence_file.name,
            "sha256": "0" * 64,
            "access_status": "public",
            "claims_verified": "A claim.",
            "verification_date": "2026-07-15",
        },
    )

    with pytest.raises(ValueError, match="sha256 mismatch"):
        validate_evidence_manifest(manifest, tmp_path)
