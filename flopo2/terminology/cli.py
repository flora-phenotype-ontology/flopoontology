"""Command-line entry point for the botanical terminology workflow."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flopo2.terminology.adjudicate import adjudicate_registry
from flopo2.terminology.annotate import TerminologyIndex
from flopo2.terminology.catalog import load_catalog
from flopo2.terminology.evaluate import evaluate_alignment
from flopo2.terminology.registry import build_registry, read_registry, write_registry
from flopo2.terminology.retrieve import SentenceTransformerEncoder
from flopo2.terminology.sources import load_source_manifest
from flopo2.terminology.sssom import write_sssom
from flopo2.terminology.workflows import (
    coverage_report,
    resplit_alignment_gold,
    sample_alignment_gold,
    sample_low_yield_segments,
    apply_review_queue,
    write_review_queue,
)


def _dense(model: str | None):
    return SentenceTransformerEncoder(model) if model else None


def main() -> None:
    parser = argparse.ArgumentParser(description="FLOPO botanical terminology alignment")
    parser.add_argument("--registry", type=Path, default=Path("config/botanical_terminology.tsv"))
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="build/update the reviewable registry")
    build.add_argument("--manifest", type=Path, default=Path("config/terminology_sources.tsv"))
    build.add_argument("--root", type=Path, default=Path("."))
    build.add_argument("--dense-model")

    sources = sub.add_parser("sources", help="report source and licensing status")
    sources.add_argument("--manifest", type=Path, default=Path("config/terminology_sources.tsv"))

    annotate = sub.add_parser("annotate", help="pre-annotate botanical terminology in text")
    annotate.add_argument("text", nargs="?")
    annotate.add_argument("--file", type=Path)
    annotate.add_argument("--language", default="en")
    annotate.add_argument("--organ", default="")
    annotate.add_argument("--longest-only", action="store_true")

    coverage = sub.add_parser("coverage", help="measure terminology coverage of segment JSONL")
    coverage.add_argument("corpus", type=Path)
    coverage.add_argument("-o", "--out", type=Path)
    coverage.add_argument("--update-frequencies", action="store_true")

    queue = sub.add_parser("review-queue", help="write frequency-prioritized mapping review TSV")
    queue.add_argument("-o", "--out", type=Path, default=Path("scratchpad/terminology-review.tsv"))

    apply_review = sub.add_parser("apply-review", help="apply explicit human decisions to registry")
    apply_review.add_argument("review", type=Path)
    apply_review.add_argument("--curator-orcid", required=True)
    apply_review.add_argument("--date", required=True, help="ISO mapping date")
    apply_review.add_argument("-o", "--out", type=Path)

    sample = sub.add_parser("sample-alignment-gold", help="sample normalization gold template")
    sample.add_argument("-o", "--out", type=Path, default=Path("gold/terminology_gold_400.tsv"))
    sample.add_argument("-n", type=int, default=400)
    sample.add_argument("--corpus-n", type=int)
    sample.add_argument("--seed", type=int, default=20260714)

    resplit = sub.add_parser(
        "resplit-alignment-gold",
        help="prevent curated surface, translation, and target leakage across splits",
    )
    resplit.add_argument("gold", type=Path)
    resplit.add_argument("-o", "--out", type=Path, required=True)
    resplit.add_argument("--seed", type=int, default=20260714)

    low = sub.add_parser("sample-low-yield", help="sample low-yield Saudi extraction gold")
    low.add_argument("corpus", type=Path)
    low.add_argument("assertions", type=Path)
    low.add_argument("-o", "--out", type=Path, default=Path("scratchpad/saudi-low-yield-200.jsonl"))
    low.add_argument("-n", type=int, default=200)
    low.add_argument("--seed", type=int, default=20260714)

    evaluate = sub.add_parser("evaluate", help="score a curated normalization gold TSV")
    evaluate.add_argument("gold", type=Path)
    evaluate.add_argument("--top-k", type=int, default=10)
    evaluate.add_argument("--split", choices=("train", "dev", "test"))
    evaluate.add_argument("--auto-threshold", type=float, default=0.95)

    sssom = sub.add_parser("sssom", help="export reviewed mappings as SSSOM")
    sssom.add_argument("-o", "--out", type=Path, default=Path("ontology/botanical-terminology.sssom.tsv"))
    sssom.add_argument("--include-auto", action="store_true")

    adjudicate = sub.add_parser("adjudicate", help="write constrained LLM proposals for review")
    adjudicate.add_argument("--model", default="openai/gpt-oss-120b")
    adjudicate.add_argument("--limit", type=int)
    adjudicate.add_argument("-o", "--out", type=Path)

    args = parser.parse_args()
    if args.command == "build":
        entries = build_registry(
            manifest=args.manifest,
            output=args.registry,
            root=args.root,
            dense_encoder=_dense(args.dense_model),
        )
        print(json.dumps({"registry": str(args.registry), "entries": len(entries)}, indent=2))
    elif args.command == "sources":
        rows = []
        for source in load_source_manifest(args.manifest):
            rows.append(
                {
                    "source_id": source.source_id,
                    "enabled": source.enabled,
                    "license": source.license,
                    "license_status": source.license_status,
                    "redistributable": source.redistributable,
                    "definition_policy": source.definition_policy,
                }
            )
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    elif args.command == "annotate":
        text = args.file.read_text(encoding="utf-8") if args.file else (args.text or "")
        index = TerminologyIndex.load(args.registry)
        mentions = index.annotate(
            text, args.language, args.organ, keep_overlaps=not args.longest_only
        )
        print(json.dumps([mention.to_dict() for mention in mentions], indent=2, ensure_ascii=False))
    elif args.command == "coverage":
        index = TerminologyIndex.load(args.registry)
        report = coverage_report(
            args.corpus,
            index,
            update_registry=args.registry if args.update_frequencies else None,
        )
        rendered = json.dumps(report, indent=2, ensure_ascii=False)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
    elif args.command == "review-queue":
        count = write_review_queue(read_registry(args.registry), args.out)
        print(json.dumps({"rows": count, "out": str(args.out)}, indent=2))
    elif args.command == "apply-review":
        entries = read_registry(args.registry)
        result = apply_review_queue(
            entries, args.review, load_catalog(), args.curator_orcid, args.date
        )
        output = args.out or args.registry
        write_registry(entries, output)
        result["out"] = str(output)
        print(json.dumps(result, indent=2))
    elif args.command == "sample-alignment-gold":
        count = sample_alignment_gold(
            read_registry(args.registry), args.out, args.n, args.corpus_n, args.seed
        )
        print(json.dumps({"rows": count, "out": str(args.out)}, indent=2))
    elif args.command == "resplit-alignment-gold":
        print(json.dumps(resplit_alignment_gold(args.gold, args.out, args.seed), indent=2))
    elif args.command == "sample-low-yield":
        count = sample_low_yield_segments(
            args.corpus, args.assertions, args.out, args.n, args.seed
        )
        print(json.dumps({"rows": count, "out": str(args.out)}, indent=2))
    elif args.command == "evaluate":
        print(
            json.dumps(
                evaluate_alignment(
                    args.gold,
                    args.registry,
                    args.top_k,
                    args.auto_threshold,
                    args.split,
                ),
                indent=2,
            )
        )
    elif args.command == "sssom":
        count = write_sssom(read_registry(args.registry), args.out, args.include_auto)
        print(json.dumps({"mappings": count, "out": str(args.out)}, indent=2))
    elif args.command == "adjudicate":
        from flopo2.extract.router import OpenRouterClient

        entries = read_registry(args.registry)
        result = adjudicate_registry(entries, load_catalog(), OpenRouterClient(), args.model, args.limit)
        output = args.out or args.registry.with_name(args.registry.stem + "-proposed.tsv")
        write_registry(entries, output)
        result["out"] = str(output)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
