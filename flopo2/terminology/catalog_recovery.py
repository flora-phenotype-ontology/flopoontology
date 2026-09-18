"""Compare PO/PATO-only runtime forms with the complete released FLOPO form catalog."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from flopo2.terminology.annotate import TerminologyIndex
from flopo2.terminology.catalog import OntologyCatalog, load_catalog
from flopo2.terminology.registry import read_registry


def _eligible(mention, score_threshold: float) -> bool:
    return bool(
        mention.candidates
        and mention.candidates[0].score >= score_threshold
        and mention.candidates[0].mapping_relation
        in {"", "skos:exactMatch", "skos:closeMatch"}
    )


def compare_catalog_coverage(
    corpus: Path,
    registry: Path,
    catalog: OntologyCatalog | None = None,
    score_threshold: float = 0.72,
) -> dict[str, object]:
    """Measure end-to-end changes and recovery while holding old mention spans fixed."""
    catalog = catalog or load_catalog()
    registry_entries = read_registry(registry)
    ontology_entries = TerminologyIndex._catalog_entries(catalog)
    baseline = TerminologyIndex(
        registry_entries
        + [entry for entry in ontology_entries if entry.target_namespace in {"PO", "PATO"}],
        catalog,
    )
    expanded = TerminologyIndex(registry_entries + ontology_entries, catalog)

    old_longest = old_eligible = new_longest = new_eligible = 0
    recovered_surfaces = Counter()
    recovered_targets = Counter()
    with corpus.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            arguments = (
                row.get("text", ""),
                row.get("language", ""),
                row.get("organ", ""),
            )
            old_mentions = baseline.annotate(*arguments, keep_overlaps=True)
            new_mentions = expanded.annotate(*arguments, keep_overlaps=True)
            new_by_span = {
                (mention.start, mention.end, mention.normalized_form): mention
                for mention in new_mentions
            }
            for mention in old_mentions:
                if not mention.longest_match:
                    continue
                old_longest += 1
                if _eligible(mention, score_threshold):
                    old_eligible += 1
                    continue
                replacement = new_by_span.get(
                    (mention.start, mention.end, mention.normalized_form)
                )
                if replacement and _eligible(replacement, score_threshold):
                    recovered_surfaces[mention.normalized_form] += 1
                    recovered_targets[replacement.candidates[0].target_id] += 1
            for mention in new_mentions:
                if not mention.longest_match:
                    continue
                new_longest += 1
                if _eligible(mention, score_threshold):
                    new_eligible += 1

    def summary(longest: int, eligible: int) -> dict[str, int | float]:
        return {
            "longest_mentions": longest,
            "eligible_mentions": eligible,
            "missing_mentions": longest - eligible,
            "eligible_rate": round(eligible / longest, 6) if longest else 0.0,
        }

    return {
        "score_threshold": score_threshold,
        "baseline_catalog_namespaces": ["PO", "PATO"],
        "expanded_catalog_namespaces": ["FLOPO", "PATO", "PO"],
        "baseline": summary(old_longest, old_eligible),
        "expanded": summary(new_longest, new_eligible),
        "fixed_baseline_span_recovered_mentions": sum(recovered_surfaces.values()),
        "distinct_recovered_surfaces": len(recovered_surfaces),
        "recovered_surfaces": recovered_surfaces.most_common(),
        "recovered_targets": recovered_targets.most_common(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "corpus",
        type=Path,
        default=Path("local-corpora/saudi-collenette/collenette-saudi-segments.jsonl"),
        nargs="?",
    )
    parser.add_argument(
        "--registry", type=Path, default=Path("config/botanical_terminology.tsv")
    )
    parser.add_argument("--score-threshold", type=float, default=0.72)
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=Path("scratchpad/botanical-terminology-catalog-recovery.json"),
    )
    args = parser.parse_args()
    result = compare_catalog_coverage(
        args.corpus, args.registry, score_threshold=args.score_threshold
    )
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
