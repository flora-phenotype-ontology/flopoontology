"""Quantify missing terminology mentions explained by numeric measurement grammar."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from flopo2.extract.measurement import parse_measurements
from flopo2.terminology.annotate import TerminologyIndex


def _eligible(mention, score_threshold: float) -> bool:
    return bool(
        mention.candidates
        and mention.candidates[0].score >= score_threshold
        and mention.candidates[0].mapping_relation
        in {"", "skos:exactMatch", "skos:closeMatch"}
    )


def measurement_recovery(
    corpus: Path,
    terminology: TerminologyIndex,
    score_threshold: float = 0.72,
) -> dict[str, object]:
    """Hold terminology spans fixed and count missing mentions inside parsed measurements."""

    longest_mentions = eligible_mentions = recovered = 0
    recovered_surfaces: Counter[str] = Counter()
    recovered_attributes: Counter[str] = Counter()
    parsed_measurements = segments_with_measurements = 0

    with corpus.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            measurements = parse_measurements(
                row.get("text", ""), row.get("language", "")
            )
            parsed_measurements += len(measurements)
            if measurements:
                segments_with_measurements += 1
            mentions = terminology.annotate(
                row.get("text", ""),
                row.get("language", ""),
                row.get("organ", ""),
                keep_overlaps=True,
            )
            for mention in mentions:
                if not mention.longest_match:
                    continue
                longest_mentions += 1
                if _eligible(mention, score_threshold):
                    eligible_mentions += 1
                    continue
                supporting = next(
                    (
                        measurement
                        for measurement in measurements
                        if measurement.start <= mention.start
                        and mention.end <= measurement.end
                    ),
                    None,
                )
                if supporting is None:
                    continue
                recovered += 1
                recovered_surfaces[mention.normalized_form] += 1
                recovered_attributes[supporting.attribute_id] += 1

    missing = longest_mentions - eligible_mentions
    return {
        "score_threshold": score_threshold,
        "longest_mentions": longest_mentions,
        "eligible_mentions": eligible_mentions,
        "missing_mentions": missing,
        "parsed_measurements": parsed_measurements,
        "segments_with_measurements": segments_with_measurements,
        "measurement_grammar_recovered_mentions": recovered,
        "measurement_grammar_recovered_surfaces": recovered_surfaces.most_common(),
        "measurement_grammar_recovered_attributes": recovered_attributes.most_common(),
        "missing_after_measurement_grammar": missing - recovered,
        "recognized_rate_after_measurement_grammar": (
            round((eligible_mentions + recovered) / longest_mentions, 6)
            if longest_mentions
            else 0.0
        ),
        "policy": {
            "meaning": (
                "recovered means the missing term mention is contained in a deterministic "
                "number+unit+attribute span"
            ),
            "not_counted_as_complete_assertion": (
                "the measurement still requires contextual PO bearer binding"
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument(
        "--registry", type=Path, default=Path("config/botanical_terminology.tsv")
    )
    parser.add_argument("--score-threshold", type=float, default=0.72)
    parser.add_argument("-o", "--out", type=Path, required=True)
    args = parser.parse_args()
    report = measurement_recovery(
        args.corpus,
        TerminologyIndex.load(args.registry),
        args.score_threshold,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
