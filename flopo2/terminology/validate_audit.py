"""Mechanical validation for proposal-only Claude botanical audit runs."""

from __future__ import annotations

import argparse
from collections import Counter
import csv
import io
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from flopo2.terminology.normalize import fold


CURATOR_ORCID = "0000-0001-8149-5890"

SCHEMAS = {
    "01-po-new-classes.tsv": (
        "proposal_id", "preferred_label", "synonyms_with_scope", "current_term_or_synonym",
        "decision", "definition", "definition_sources", "direct_parent_ids", "part_of_ids",
        "has_part_ids", "other_axioms", "corpus_frequency", "short_examples",
        "competency_questions", "counterexamples", "upstream_release_checked", "confidence",
        "caveats",
    ),
    "02-po-narrow-promotions.tsv": (
        "proposal_id", "preferred_label", "synonyms_with_scope", "current_term_or_synonym",
        "decision", "definition", "definition_sources", "direct_parent_ids", "part_of_ids",
        "has_part_ids", "other_axioms", "corpus_frequency", "short_examples",
        "competency_questions", "counterexamples", "upstream_release_checked", "confidence",
        "caveats",
    ),
    "03-pato-new-classes.tsv": (
        "proposal_id", "preferred_label", "synonyms_with_scope", "decision", "definition",
        "operational_prototype_or_range", "definition_sources", "direct_parent_ids",
        "other_axioms", "corpus_frequency", "short_examples", "upstream_release_checked",
        "confidence", "caveats",
    ),
    "04-growth-form-placement.tsv": (
        "surface_form", "corpus_frequency", "decision", "definition", "definition_sources",
        "bearer_id", "quality_or_component_ids", "owl_expression", "mapping_relation",
        "confidence", "alternatives_rejected", "caveats",
    ),
    "05-mapping-sota-results.tsv": (
        "system", "version_or_paper", "task", "dataset", "precision", "recall", "f1",
        "recall_at_k", "supervision", "uses_llm", "uses_logic", "source_url", "limitations",
    ),
    "06-mapping-proposals.sssom.tsv": (
        "subject_id", "subject_label", "predicate_id", "object_id", "object_label",
        "mapping_justification", "mapping_date", "author_id", "confidence", "mapping_tool",
        "mapping_source", "comment",
    ),
    "06-new-class-or-noise.tsv": (
        "term_id", "surface_form", "corpus_frequency", "semantic_role", "decision",
        "intended_ontology", "proposed_label", "context_summary", "rationale", "evidence",
        "confidence", "caveats",
    ),
    "07-blockers.tsv": (
        "source_file", "proposal_id", "severity", "problem", "required_correction", "status",
    ),
}

REQUIRED_FILES = (
    "00-executive-summary.md",
    *SCHEMAS,
    "05-mapping-sota.md",
    "07-adversarial-review.md",
    "08-unresolved.tsv",
    "manifest.json",
)

PO_DECISIONS = {
    "new_po_class", "promote_narrow_synonym", "map_existing", "flopo_phenotype",
    "lexical_only", "noise", "uncertain",
}
PATO_DECISIONS = {
    "new_pato_class", "add_synonym", "map_existing", "flopo_composition",
    "contextual_scalar", "noise", "uncertain",
}
MAPPING_PREDICATES = {
    "skos:exactMatch", "skos:closeMatch", "skos:broadMatch", "skos:narrowMatch",
    "skos:relatedMatch", "flopo:compositionalMatch", "flopo:unmapped",
}
ID_PATTERN = re.compile(r"\b(PO|PATO|FLOPO)[:_]([0-9]{7})\b")


@dataclass
class ValidationReport:
    run_dir: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)
    missing_surface_count: int | None = None

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, object]:
        return {
            "run_dir": self.run_dir,
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "row_counts": self.row_counts,
            "missing_surface_count": self.missing_surface_count,
        }


def read_proposal_tsv(path: Path) -> tuple[list[str], list[dict[str, str]], list[str]]:
    metadata: list[str] = []
    body: list[str] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for line in handle:
            if not body and (not line.strip() or line.startswith("#")):
                if line.startswith("#"):
                    metadata.append(line.rstrip("\r\n"))
                continue
            body.append(line)
    if not body:
        return [], [], metadata
    reader = csv.DictReader(io.StringIO("".join(body)), delimiter="\t")
    rows = list(reader)
    return list(reader.fieldnames or ()), rows, metadata


def ontology_obo_paths(root: Path, additional: Iterable[Path] = ()) -> tuple[Path, ...]:
    paths = [root / "ont/plant_ontology.obo", root / "ont/quality.obo"]
    paths.extend(Path(path) for path in additional)
    return tuple(dict.fromkeys(path.resolve() for path in paths if path.exists()))


def known_ontology_ids(root: Path, additional_obos: Iterable[Path] = ()) -> set[str]:
    known: set[str] = set()
    for path in ontology_obo_paths(root, additional_obos):
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.startswith("id: "):
                    continue
                value = line[4:].strip()
                match = ID_PATTERN.fullmatch(value)
                if match:
                    known.add(f"{match.group(1)}_{match.group(2)}")
    owl = root / "ontology/flopo.owl"
    if owl.exists():
        with owl.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                for match in ID_PATTERN.finditer(line):
                    known.add(f"{match.group(1)}_{match.group(2)}")
    registry = root / "config/botanical_terminology.tsv"
    if registry.exists():
        text = registry.read_text(encoding="utf-8", errors="replace")
        for match in ID_PATTERN.finditer(text):
            known.add(f"{match.group(1)}_{match.group(2)}")
    return known


def existing_exact_forms(
    root: Path, additional_obos: Iterable[Path] = ()
) -> dict[str, set[str]]:
    """Index preferred labels and EXACT synonyms in the pinned PO/PATO OBO files."""
    forms: dict[str, set[str]] = {}
    for path in ontology_obo_paths(root, additional_obos):
        current_id = ""
        with path.open(encoding="utf-8", errors="replace") as handle:
            for raw in handle:
                line = raw.rstrip("\n")
                if line == "[Term]":
                    current_id = ""
                elif line.startswith("["):
                    current_id = ""
                elif line.startswith("id: "):
                    match = ID_PATTERN.fullmatch(line[4:].strip())
                    current_id = canonical_id(match) if match else ""
                elif current_id and line.startswith("name: "):
                    normalized = fold(line[6:].strip())
                    if normalized:
                        forms.setdefault(normalized, set()).add(current_id)
                elif current_id and line.startswith("synonym: ") and " EXACT " in line:
                    match = re.search(r'^synonym: "((?:\\.|[^"\\])*)"', line)
                    normalized = fold(match.group(1).replace('\\"', '"')) if match else ""
                    if normalized:
                        forms.setdefault(normalized, set()).add(current_id)
    return forms


def canonical_id(match: re.Match[str]) -> str:
    return f"{match.group(1)}_{match.group(2)}"


def check_confidence(
    report: ValidationReport, filename: str, row_number: int, value: str
) -> None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        report.errors.append(f"{filename}:{row_number}: confidence is not numeric: {value!r}")
        return
    if not 0.0 <= number <= 1.0:
        report.errors.append(f"{filename}:{row_number}: confidence outside [0,1]: {number}")


def check_ids(
    report: ValidationReport,
    filename: str,
    row_number: int,
    row: dict[str, str],
    known: set[str],
) -> None:
    for field_name, value in row.items():
        if field_name in {"definition", "short_examples", "context_summary", "rationale", "comment"}:
            continue
        for match in ID_PATTERN.finditer(value or ""):
            value_id = canonical_id(match)
            if value_id in known:
                continue
            message = f"{filename}:{row_number}: {field_name} contains unknown ID {value_id}"
            if filename == "06-mapping-proposals.sssom.tsv" and field_name == "object_id":
                report.errors.append(message)
            else:
                report.warnings.append(message + " (verify against recorded upstream release)")


def validate_table(
    run_dir: Path,
    filename: str,
    report: ValidationReport,
    known: set[str],
    exact_forms: dict[str, set[str]],
) -> list[dict[str, str]]:
    path = run_dir / filename
    fields, rows, metadata = read_proposal_tsv(path)
    expected = list(SCHEMAS[filename])
    if filename == "06-mapping-proposals.sssom.tsv":
        missing_fields = [field_name for field_name in expected if field_name not in fields]
        if missing_fields:
            report.errors.append(
                f"{filename}: missing required SSSOM fields {missing_fields!r}; got {fields!r}"
            )
    elif fields != expected:
        report.errors.append(f"{filename}: header mismatch; expected {expected!r}, got {fields!r}")
    report.row_counts[filename] = len(rows)

    if filename == "06-mapping-proposals.sssom.tsv" and not metadata:
        report.errors.append(f"{filename}: missing SSSOM metadata comments")

    seen_keys: set[str] = set()
    key_field = "proposal_id" if "proposal_id" in fields else ""
    for offset, row in enumerate(rows, start=2 + len(metadata)):
        if None in row:
            report.errors.append(f"{filename}:{offset}: too many TSV fields")
        if key_field:
            key = (row.get(key_field) or "").strip()
            if not key:
                report.errors.append(f"{filename}:{offset}: empty {key_field}")
            elif key in seen_keys:
                report.errors.append(f"{filename}:{offset}: duplicate {key_field} {key}")
            seen_keys.add(key)
        if "confidence" in fields:
            check_confidence(report, filename, offset, row.get("confidence") or "")
        check_ids(report, filename, offset, row, known)

        if filename in {"01-po-new-classes.tsv", "02-po-narrow-promotions.tsv"}:
            decision = row.get("decision") or ""
            if decision not in PO_DECISIONS:
                report.errors.append(f"{filename}:{offset}: invalid PO decision {decision!r}")
            if decision in {"new_po_class", "promote_narrow_synonym"}:
                for required in ("definition", "definition_sources", "direct_parent_ids"):
                    if not (row.get(required) or "").strip():
                        report.errors.append(
                            f"{filename}:{offset}: {decision} requires {required}"
                        )
            if decision == "new_po_class":
                existing = exact_forms.get(fold(row.get("preferred_label") or ""), set())
                if existing:
                    report.errors.append(
                        f"{filename}:{offset}: new class label is already an exact PO/PATO form of "
                        f"{sorted(existing)!r}"
                    )
        elif filename == "03-pato-new-classes.tsv":
            decision = row.get("decision") or ""
            if decision not in PATO_DECISIONS:
                report.errors.append(f"{filename}:{offset}: invalid PATO decision {decision!r}")
            if decision == "new_pato_class":
                for required in (
                    "definition", "operational_prototype_or_range", "definition_sources",
                    "direct_parent_ids",
                ):
                    if not (row.get(required) or "").strip():
                        report.errors.append(
                            f"{filename}:{offset}: {decision} requires {required}"
                        )
                existing = exact_forms.get(fold(row.get("preferred_label") or ""), set())
                if existing:
                    report.errors.append(
                        f"{filename}:{offset}: new class label is already an exact PO/PATO form of "
                        f"{sorted(existing)!r}"
                    )
        elif filename == "06-mapping-proposals.sssom.tsv":
            predicate = row.get("predicate_id") or ""
            if predicate not in MAPPING_PREDICATES:
                report.errors.append(f"{filename}:{offset}: unsupported predicate {predicate!r}")
            if CURATOR_ORCID in (row.get("author_id") or ""):
                report.errors.append(f"{filename}:{offset}: LLM proposal uses curator ORCID")
            if "propos" not in (row.get("comment") or "").casefold():
                report.errors.append(f"{filename}:{offset}: comment does not mark row proposed")
            if predicate != "flopo:unmapped" and not (row.get("object_id") or "").strip():
                report.errors.append(f"{filename}:{offset}: mapped row has no object_id")
    return rows


def expected_surfaces(baseline_manifest: Path | None) -> set[str]:
    if baseline_manifest is None or not baseline_manifest.exists():
        return set()
    data = json.loads(baseline_manifest.read_text(encoding="utf-8"))
    values = data.get("unresolved", {}).get("missing_surfaces", [])
    return {fold(str(surface)) for surface, _frequency in values if fold(str(surface))}


def validate_run(
    run_dir: Path,
    root: Path,
    baseline_manifest: Path | None = None,
    ontology_obos: Iterable[Path] = (),
) -> ValidationReport:
    report = ValidationReport(run_dir=str(run_dir))
    if not run_dir.is_dir():
        report.errors.append("run directory does not exist")
        return report
    for filename in REQUIRED_FILES:
        path = run_dir / filename
        if not path.is_file():
            report.errors.append(f"missing required file: {filename}")
        elif path.stat().st_size == 0:
            report.errors.append(f"empty required file: {filename}")

    if report.errors:
        return report

    known = known_ontology_ids(root, ontology_obos)
    exact_forms = existing_exact_forms(root, ontology_obos)
    tables: dict[str, list[dict[str, str]]] = {}
    for filename in SCHEMAS:
        tables[filename] = validate_table(run_dir, filename, report, known, exact_forms)

    unresolved_fields, unresolved_rows, _ = read_proposal_tsv(run_dir / "08-unresolved.tsv")
    report.row_counts["08-unresolved.tsv"] = len(unresolved_rows)
    if not unresolved_fields:
        report.errors.append("08-unresolved.tsv: missing header")

    for filename in ("00-executive-summary.md", "05-mapping-sota.md", "07-adversarial-review.md"):
        if len((run_dir / filename).read_text(encoding="utf-8").strip()) < 100:
            report.errors.append(f"{filename}: content is too short to be a substantive deliverable")

    try:
        manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        report.errors.append(f"manifest.json: invalid JSON: {error}")
        manifest = {}
    if not isinstance(manifest, dict):
        report.errors.append("manifest.json: top level must be an object")
    else:
        manifest_text = json.dumps(manifest).casefold()
        for token in ("model", "run", "input", "output", "agent"):
            if token not in manifest_text:
                report.warnings.append(f"manifest.json: no field appears to record {token!r}")

    expected = expected_surfaces(baseline_manifest)
    if expected:
        mapping_counts = Counter(
            fold(row.get("subject_label") or "")
            for row in tables["06-mapping-proposals.sssom.tsv"]
            if fold(row.get("subject_label") or "")
        )
        classified_counts = Counter(
            fold(row.get("surface_form") or "")
            for row in tables["06-new-class-or-noise.tsv"]
            if fold(row.get("surface_form") or "")
        )
        mapping_surfaces = set(mapping_counts)
        classified_surfaces = set(classified_counts)
        observed = mapping_surfaces | classified_surfaces

        for table_name, counts in (
            ("06-mapping-proposals.sssom.tsv", mapping_counts),
            ("06-new-class-or-noise.tsv", classified_counts),
        ):
            duplicates = sorted(surface for surface, count in counts.items() if count > 1)
            if duplicates:
                preview = ", ".join(duplicates[:20])
                report.errors.append(
                    f"{table_name}: {len(duplicates)} duplicate normalized surface(s)"
                    f" (first: {preview})"
                )

        overlap = sorted(mapping_surfaces & classified_surfaces)
        if overlap:
            preview = ", ".join(overlap[:20])
            report.errors.append(
                f"06 tables are not a partition: {len(overlap)} surface(s) occur in both"
                f" (first: {preview})"
            )

        unexpected = sorted(observed - expected)
        if unexpected:
            preview = ", ".join(unexpected[:20])
            report.errors.append(
                f"06 tables contain {len(unexpected)} off-baseline surface(s)"
                f" (first: {preview})"
            )

        missing = sorted(expected - observed)
        report.missing_surface_count = len(missing)
        if missing:
            preview = ", ".join(missing[:20])
            report.errors.append(
                f"corpus surface coverage incomplete: {len(missing)} of {len(expected)} missing"
                f" (first: {preview})"
            )
    else:
        report.warnings.append("surface coverage not checked: baseline has no full missing-surface list")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dirs", type=Path, nargs="+")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--baseline-manifest", type=Path)
    parser.add_argument(
        "--ontology-obo",
        type=Path,
        action="append",
        default=[],
        help="additional current/pinned PO or PATO OBO file (repeatable)",
    )
    parser.add_argument("-o", "--out", type=Path)
    args = parser.parse_args()

    reports = [
        validate_run(
            path,
            args.root.resolve(),
            args.baseline_manifest,
            args.ontology_obo,
        )
        for path in args.run_dirs
    ]
    payload = {
        "valid": all(report.valid for report in reports),
        "runs": [report.to_dict() for report in reports],
    }
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    if not payload["valid"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
