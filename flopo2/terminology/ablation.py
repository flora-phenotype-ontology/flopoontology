"""Controlled extraction ablation for measuring the value of terminology priors."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flopo2.extract.engine import EngineConfig
from flopo2.extract.pilot import run_pilot

MODES = ("off", "ontology", "registry", "full")


def assess_acceptance(results: dict) -> dict:
    baseline = results["off"]
    full = results["full"]
    exact_delta = (
        full["overall"]["exact"]["f1"] - baseline["overall"]["exact"]["f1"]
    )
    lenient_delta = (
        full["overall"]["lenient"]["f1"] - baseline["overall"]["lenient"]["f1"]
    )
    hallucination_delta = (
        full["overall"]["hallucination_rate"]
        - baseline["overall"]["hallucination_rate"]
    )
    language_regressions = {}
    for language in set(baseline.get("by_language", {})) | set(full.get("by_language", {})):
        before = baseline.get("by_language", {}).get(language, {}).get("f1", 0.0)
        after = full.get("by_language", {}).get(language, {}).get("f1", 0.0)
        language_regressions[language] = round(after - before, 4)
    passed = (
        exact_delta >= 0.05
        and hallucination_delta <= 0.0
        and all(delta >= -0.02 for delta in language_regressions.values())
    )
    return {
        "passed": passed,
        "exact_f1_delta": round(exact_delta, 4),
        "lenient_f1_delta": round(lenient_delta, 4),
        "hallucination_rate_delta": round(hallucination_delta, 4),
        "language_f1_deltas": language_regressions,
        "thresholds": {
            "minimum_exact_f1_delta": 0.05,
            "maximum_hallucination_rate_delta": 0.0,
            "maximum_language_f1_regression": -0.02,
        },
    }


def run_ablation(
    silver: Path,
    model: str,
    registry: str,
    limit: int | None,
    concurrency: int,
    samples: int,
    temperature: float,
    ancestors=None,
) -> dict:
    results = {}
    for mode in MODES:
        config = EngineConfig(
            models=[model],
            grounding="spires",
            samples=samples,
            temperature=temperature,
            use_terminology=mode != "off",
            terminology_mode=mode,
            terminology_registry=registry,
        )
        results[mode] = run_pilot(
            silver,
            config,
            limit,
            ancestors=ancestors,
            concurrency=concurrency,
        )
    return {"results": results, "acceptance": assess_acceptance(results)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Ablate ontology/glossary terminology priors")
    parser.add_argument("--silver", type=Path, default=Path("gold/gold_standard_100.jsonl"))
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--registry", default="config/botanical_terminology.tsv")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--lenient", action="store_true")
    parser.add_argument("-o", "--out", type=Path, default=Path("gold/terminology_ablation.json"))
    args = parser.parse_args()
    ancestors = None
    if args.lenient:
        from flopo2.eval.hierarchy import build_ancestors

        ancestors = build_ancestors()
    report = run_ablation(
        args.silver,
        args.model,
        args.registry,
        args.limit,
        args.concurrency,
        args.samples,
        args.temperature,
        ancestors,
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
