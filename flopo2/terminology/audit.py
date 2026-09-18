"""Freeze reproducible terminology baselines without copying source-corpus text."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from flopo2.terminology.annotate import TerminologyIndex


ELIGIBLE_RELATIONS = {"", "skos:exactMatch", "skos:closeMatch"}
ELIGIBLE_SCORE = 0.72

DEFAULT_INPUTS = (
    "config/botanical_terminology.tsv",
    "config/terminology_sources.tsv",
    "config/po_lexicon.tsv",
    "config/pato_lexicon.tsv",
    "config/flopo_id_registry.tsv",
    "config/oak_botanical_lexmatch_rules.yaml",
    "curation/botanical_evidence.tsv",
    "curation/botanical_concept_proposals.tsv",
    "ont/plant_ontology.obo",
    "ont/quality.obo",
    "ontology/flopo.owl",
    "ontology/flopo-value-extensions.ttl",
    "ontology/botanical-terminology.sssom.tsv",
    "BOTANICAL_TERMINOLOGY_CURATION_PLAN.md",
    "flopo2/TERMINOLOGY.md",
)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, root: Path) -> dict[str, object]:
    stat = path.stat()
    try:
        display = path.relative_to(root).as_posix()
    except ValueError:
        display = path.as_posix()
    return {
        "path": display,
        "bytes": stat.st_size,
        "sha256": sha256_file(path),
    }


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def registry_statistics(path: Path) -> dict[str, object]:
    rows = read_tsv(path)
    groups: dict[tuple[str, str], str] = {}
    status_rank = {"none": 0, "source_definition_excluded": 1, "included": 2}
    row_status = Counter()
    sources = Counter()
    relations = Counter()
    review_statuses = Counter()
    roles = Counter()

    for row in rows:
        definition = (row.get("definition") or "").strip()
        notes = row.get("notes") or ""
        if definition:
            status = "included"
        elif "definition_excluded" in notes:
            status = "source_definition_excluded"
        else:
            status = "none"
        row_status[status] += 1
        key = ((row.get("normalized_form") or "").strip(), (row.get("language") or "").strip())
        previous = groups.get(key, "none")
        if status_rank[status] > status_rank[previous]:
            groups[key] = status
        elif key not in groups:
            groups[key] = status
        sources[row.get("source_id") or ""] += 1
        relations[row.get("mapping_relation") or ""] += 1
        review_statuses[row.get("review_status") or ""] += 1
        roles[row.get("semantic_role") or ""] += 1

    unique_status = Counter(groups.values())
    return {
        "rows": len(rows),
        "distinct_normalized_form_language": len(groups),
        "definition_rows": dict(sorted(row_status.items())),
        "definition_unique_groups": dict(sorted(unique_status.items())),
        "sources": dict(sorted(sources.items())),
        "semantic_roles": dict(sorted(roles.items())),
        "mapping_relations": dict(sorted(relations.items())),
        "review_statuses": dict(sorted(review_statuses.items())),
    }


def source_manifest_statistics(path: Path) -> dict[str, object]:
    rows = read_tsv(path)
    return {
        "rows": len(rows),
        "enabled": sum((row.get("enabled") or "") in {"1", "true", "True"} for row in rows),
        "redistributable": sum(
            (row.get("redistributable") or "") in {"1", "true", "True"} for row in rows
        ),
        "definition_policies": dict(
            sorted(Counter(row.get("definition_policy") or "" for row in rows).items())
        ),
    }


def review_queue_statistics(path: Path) -> dict[str, object]:
    rows = read_tsv(path)
    corpus_rows = [row for row in rows if int(row.get("corpus_frequency") or 0) > 0]
    return {
        "rows": len(rows),
        "corpus_attested_rows": len(corpus_rows),
        "distinct_corpus_attested_surface_language": len(
            {(row.get("surface_form") or "", row.get("language") or "") for row in corpus_rows}
        ),
        "corpus_frequency_sum": sum(int(row.get("corpus_frequency") or 0) for row in corpus_rows),
    }


def unresolved_corpus_statistics(
    corpus: Path,
    index: TerminologyIndex,
    threshold: float = ELIGIBLE_SCORE,
) -> dict[str, object]:
    causes = Counter()
    namespaces = Counter()
    target_ids = Counter()
    surfaces = Counter()
    registry_terms: set[str] = set()
    total_longest = eligible = 0

    with corpus.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            mentions = index.annotate(
                row.get("text", ""),
                language=row.get("language", ""),
                organ_context=row.get("organ", ""),
                keep_overlaps=True,
            )
            for mention in mentions:
                if not mention.longest_match:
                    continue
                total_longest += 1
                if not mention.candidates:
                    cause = "nil"
                    namespace = "NIL"
                    target_id = ""
                else:
                    top = mention.candidates[0]
                    if top.score >= threshold and top.mapping_relation in ELIGIBLE_RELATIONS:
                        eligible += 1
                        continue
                    if top.score < threshold:
                        cause = "low_score"
                    else:
                        cause = "non_equivalent_relation"
                    namespace = top.namespace or top.target_id.split("_", 1)[0]
                    target_id = top.target_id
                causes[cause] += 1
                namespaces[namespace] += 1
                if target_id:
                    target_ids[target_id] += 1
                surfaces[mention.normalized_form] += 1
                registry_terms.update(mention.registry_term_ids)

    missing = sum(causes.values())
    return {
        "eligibility_score_threshold": threshold,
        "eligible_relations": sorted(ELIGIBLE_RELATIONS),
        "longest_mentions": total_longest,
        "eligible_mentions": eligible,
        "missing_mentions": missing,
        "eligible_rate": round(eligible / total_longest, 6) if total_longest else 0.0,
        "missing_rate": round(missing / total_longest, 6) if total_longest else 0.0,
        "causes": dict(sorted(causes.items())),
        "candidate_namespaces": dict(sorted(namespaces.items())),
        "distinct_missing_surfaces": len(surfaces),
        "distinct_registry_terms": len(registry_terms),
        "missing_surfaces": surfaces.most_common(),
        "top_missing_surfaces": surfaces.most_common(100),
        "top_candidate_targets": target_ids.most_common(100),
    }


def obo_header(path: Path) -> dict[str, str]:
    fields = {
        "format-version",
        "data-version",
        "date",
        "ontology",
        "saved-by",
        "auto-generated-by",
    }
    values: dict[str, str] = {}
    with path.open(encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            if line.startswith("["):
                break
            if ": " not in line:
                continue
            key, value = line.split(": ", 1)
            if key in fields and key not in values:
                values[key] = value
    return values


def flopo_release_metadata(path: Path) -> dict[str, str]:
    patterns = {
        "ontology_iri": re.compile(r'<owl:Ontology rdf:about="([^"]+)"'),
        "version_iri": re.compile(r'<owl:versionIRI rdf:resource="([^"]+)"'),
        "version_info": re.compile(r"<owl:versionInfo>(.*?)</owl:versionInfo>"),
        "modified": re.compile(r"<dcterms:modified[^>]*>(.*?)</dcterms:modified>"),
    }
    values: dict[str, str] = {}
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            for key, pattern in patterns.items():
                if key in values:
                    continue
                match = pattern.search(line)
                if match:
                    values[key] = match.group(1)
            if len(values) == len(patterns):
                break
    return values


def git_metadata(root: Path) -> dict[str, object]:
    def run(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    return {
        "commit": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "status_porcelain": run("status", "--short").splitlines(),
    }


def build_manifest(
    root: Path,
    registry: Path,
    source_manifest: Path,
    corpus: Path,
    coverage: Path,
    review_queue: Path,
    analyze_corpus: bool = True,
) -> dict[str, object]:
    root = root.resolve()
    paths = [root / value for value in DEFAULT_INPUTS]
    paths.extend((corpus, coverage, review_queue))
    deduplicated = {path.resolve(): path.resolve() for path in paths if path.exists()}

    report: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "command": sys.argv,
        "git": git_metadata(root),
        "inputs": [file_record(path, root) for path in sorted(deduplicated)],
        "registry": registry_statistics(registry),
        "source_manifest": source_manifest_statistics(source_manifest),
        "review_queue": review_queue_statistics(review_queue),
        "coverage": json.loads(coverage.read_text(encoding="utf-8")),
        "ontology_versions": {
            "po": obo_header(root / "ont/plant_ontology.obo"),
            "pato": obo_header(root / "ont/quality.obo"),
            "flopo": flopo_release_metadata(root / "ontology/flopo.owl"),
        },
    }
    if analyze_corpus:
        report["unresolved"] = unresolved_corpus_statistics(
            corpus, TerminologyIndex.load(registry)
        )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--registry", type=Path, default=Path("config/botanical_terminology.tsv")
    )
    parser.add_argument(
        "--source-manifest", type=Path, default=Path("config/terminology_sources.tsv")
    )
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("local-corpora/saudi-collenette/collenette-saudi-segments.jsonl"),
    )
    parser.add_argument(
        "--coverage",
        type=Path,
        default=Path("scratchpad/collenette-terminology-coverage.json"),
    )
    parser.add_argument(
        "--review-queue",
        type=Path,
        default=Path("scratchpad/terminology-review-saudi.tsv"),
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("scratchpad/botanical-terminology-baseline/manifest.json"),
    )
    parser.add_argument("--skip-corpus-analysis", action="store_true")
    args = parser.parse_args()

    report = build_manifest(
        args.root,
        args.registry,
        args.source_manifest,
        args.corpus,
        args.coverage,
        args.review_queue,
        analyze_corpus=not args.skip_corpus_analysis,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(args.out),
                "inputs": len(report["inputs"]),
                "registry_rows": report["registry"]["rows"],
                "missing_mentions": report.get("unresolved", {}).get("missing_mentions"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
