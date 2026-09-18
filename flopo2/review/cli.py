"""Resumable offline CLI for unresolved-span machine review."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from flopo2.review.adversarial import build_adversarial_batches
from flopo2.review.batches import build_batches, build_stratified_pilot_batch
from flopo2.review.consensus import build_consensus
from flopo2.review.dispatch import collect_completed_decisions, dispatch_batch
from flopo2.review.inventory import build_inventory, model_spec
from flopo2.review.models import CampaignManifest
from flopo2.review.report import campaign_report, write_report
from flopo2.review.responses import ingest_response, write_response_schemas


def _manifest(path: Path) -> CampaignManifest:
    return CampaignManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _pair(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected ID=PATH")
    key, path = value.split("=", 1)
    if not key or not path:
        raise argparse.ArgumentTypeError("expected ID=PATH")
    return key, Path(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    inventory = sub.add_parser("inventory", help="freeze Stage 13 residual occurrences")
    inventory.add_argument("--input", type=Path, required=True)
    inventory.add_argument("--occurrences", type=Path, required=True)
    inventory.add_argument("--clusters", type=Path, required=True)
    inventory.add_argument("--evidence", type=Path, required=True)
    inventory.add_argument("--manifest", type=Path, required=True)
    inventory.add_argument("--ontology", type=Path, action="append", required=True)
    inventory.add_argument("--authority", type=Path, action="append", default=[])
    inventory.add_argument("--prompt", type=_pair, action="append", required=True)
    inventory.add_argument(
        "--models",
        type=Path,
        required=True,
        help="JSON array of reviewer_id/provider/model/model_family/role objects",
    )
    consensus = sub.add_parser("consensus", help="combine decision JSONL files")
    consensus.add_argument("--manifest", type=Path, required=True)
    consensus.add_argument("--occurrences", type=Path, required=True)
    consensus.add_argument("--clusters", type=Path, required=True)
    consensus.add_argument("--evidence", type=Path, required=True)
    consensus.add_argument("--reviews", type=Path, action="append", required=True)
    consensus.add_argument("--adjudications", type=Path, action="append", default=[])
    consensus.add_argument("--output", type=Path, required=True)
    consensus.add_argument("--exceptions", type=Path, required=True)
    consensus.add_argument("--ledger", type=Path, required=True)
    batches = sub.add_parser("batches", help="build immutable provider-neutral review packets")
    batches.add_argument("--manifest", type=Path, required=True)
    batches.add_argument("--clusters", type=Path, required=True)
    batches.add_argument("--output-dir", type=Path, required=True)
    batches.add_argument("--batch-size", type=int, default=20)
    batches.add_argument("--max-bytes", type=int, default=120_000)
    batches.add_argument("--order", choices=["priority", "cluster_id"], default="priority")
    pilot = sub.add_parser("pilot-batch", help="build one bounded cluster per residual reason")
    pilot.add_argument("--manifest", type=Path, required=True)
    pilot.add_argument("--clusters", type=Path, required=True)
    pilot.add_argument("--output-dir", type=Path, required=True)
    pilot.add_argument("--per-reason", type=int, default=1)
    pilot.add_argument("--max-bytes", type=int, default=120_000)
    adversarial_batches = sub.add_parser(
        "adversarial-batches", help="build packets containing exact reusable-class proposals"
    )
    adversarial_batches.add_argument("--manifest", type=Path, required=True)
    adversarial_batches.add_argument("--occurrences", type=Path, required=True)
    adversarial_batches.add_argument("--clusters", type=Path, required=True)
    adversarial_batches.add_argument("--evidence", type=Path, required=True)
    adversarial_batches.add_argument("--reviews", type=Path, action="append", required=True)
    adversarial_batches.add_argument("--output-dir", type=Path, required=True)
    adversarial_batches.add_argument("--batch-size", type=int, default=10)
    adversarial_batches.add_argument("--max-bytes", type=int, default=120_000)
    report = sub.add_parser("report", help="verify conservation and summarize dispositions")
    report.add_argument("--manifest", type=Path, required=True)
    report.add_argument("--occurrences", type=Path, required=True)
    report.add_argument("--clusters", type=Path, required=True)
    report.add_argument("--evidence", type=Path, required=True)
    report.add_argument("--consensus", type=Path, required=True)
    report.add_argument("--ledger", type=Path, required=True)
    report.add_argument("--output", type=Path, required=True)
    schemas = sub.add_parser("schemas", help="write structured-output schemas for LLM runners")
    schemas.add_argument("--reviews", type=Path, required=True)
    schemas.add_argument("--adjudications", type=Path, required=True)
    ingest = sub.add_parser("ingest", help="validate a provider response and emit decision JSONL")
    ingest.add_argument("--response", type=Path, required=True)
    ingest.add_argument("--role", choices=["reviewer", "adjudicator"], required=True)
    ingest.add_argument("--output", type=Path, required=True)
    dispatch = sub.add_parser("dispatch", help="run or resume one hash-bound provider batch")
    dispatch.add_argument("--manifest", type=Path, required=True)
    dispatch.add_argument("--batch-index", type=Path, required=True)
    dispatch.add_argument("--batch", type=Path, required=True)
    dispatch.add_argument("--reviewer-id", required=True)
    dispatch.add_argument("--prompt-id", required=True)
    dispatch.add_argument("--checkpoint-root", type=Path, required=True)
    dispatch.add_argument("--cwd", type=Path, default=Path.cwd())
    dispatch.add_argument(
        "--backend", choices=["auto", "claude", "codex", "openrouter"], default="auto"
    )
    dispatch.add_argument("--timeout", type=float)
    dispatch.add_argument(
        "--max-output-tokens",
        type=int,
        help="hard provider completion-token cap (recommended for paid OpenRouter runs)",
    )
    dispatch.add_argument(
        "--openrouter-response-mode",
        choices=["json_schema", "json_object"],
        default="json_schema",
        help="provider response constraint; json_object embeds the strict schema in the prompt",
    )
    dispatch.add_argument("--claude-executable", default="claude")
    dispatch.add_argument("--codex-executable", default="codex")
    collect = sub.add_parser(
        "collect", help="merge one reviewer's complete hash-bound batch checkpoints"
    )
    collect.add_argument("--manifest", type=Path, required=True)
    collect.add_argument("--batch-index", type=Path, required=True)
    collect.add_argument("--checkpoint-root", type=Path, required=True)
    collect.add_argument("--reviewer-id", required=True)
    collect.add_argument("--output", type=Path, required=True)
    collect.add_argument(
        "--allow-partial",
        action="store_true",
        help="collect only complete checkpoints and report every missing batch/item",
    )
    collect.add_argument("--report", type=Path)
    collect.add_argument("--cwd", type=Path, default=Path.cwd())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "inventory":
        raw_models = json.loads(args.models.read_text(encoding="utf-8"))
        models = [model_spec(**row) for row in raw_models]
        manifest = build_inventory(
            stage13_path=args.input,
            occurrence_path=args.occurrences,
            cluster_path=args.clusters,
            evidence_path=args.evidence,
            manifest_path=args.manifest,
            ontology_paths=args.ontology,
            authority_paths=args.authority,
            prompt_paths=dict(args.prompt),
            models=models,
        )
        print(manifest.model_dump_json(indent=2))
        return 0
    if args.command == "consensus":
        counts = build_consensus(
            manifest=_manifest(args.manifest),
            occurrence_path=args.occurrences,
            cluster_path=args.clusters,
            evidence_path=args.evidence,
            review_paths=args.reviews,
            adjudication_paths=args.adjudications,
            consensus_path=args.output,
            exception_path=args.exceptions,
            ledger_path=args.ledger,
        )
        print(json.dumps(counts, sort_keys=True))
        return 0
    if args.command == "batches":
        result = build_batches(
            _manifest(args.manifest),
            args.clusters,
            args.output_dir,
            batch_size=args.batch_size,
            max_bytes=args.max_bytes,
            order=args.order,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.command == "schemas":
        write_response_schemas(args.reviews, args.adjudications)
        return 0
    if args.command == "pilot-batch":
        result = build_stratified_pilot_batch(
            _manifest(args.manifest),
            args.clusters,
            args.output_dir,
            per_reason=args.per_reason,
            max_bytes=args.max_bytes,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.command == "adversarial-batches":
        result = build_adversarial_batches(
            manifest=_manifest(args.manifest),
            occurrence_path=args.occurrences,
            cluster_path=args.clusters,
            evidence_path=args.evidence,
            review_paths=args.reviews,
            output_dir=args.output_dir,
            batch_size=args.batch_size,
            max_bytes=args.max_bytes,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.command == "ingest":
        count = ingest_response(args.response, args.output, role=args.role)
        print(json.dumps({"decisions": count, "output": str(args.output)}, sort_keys=True))
        return 0
    if args.command == "dispatch":
        result = dispatch_batch(
            manifest_path=args.manifest,
            batch_index_path=args.batch_index,
            batch_path=args.batch,
            reviewer_id=args.reviewer_id,
            prompt_id=args.prompt_id,
            checkpoint_root=args.checkpoint_root,
            cwd=args.cwd,
            backend=args.backend,
            timeout=args.timeout,
            max_output_tokens=args.max_output_tokens,
            openrouter_response_mode=args.openrouter_response_mode,
            claude_executable=args.claude_executable,
            codex_executable=args.codex_executable,
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] in {"completed", "skipped"} else 1
    if args.command == "collect":
        result = collect_completed_decisions(
            manifest_path=args.manifest,
            batch_index_path=args.batch_index,
            checkpoint_root=args.checkpoint_root,
            reviewer_id=args.reviewer_id,
            output_path=args.output,
            cwd=args.cwd,
            allow_partial=args.allow_partial,
            report_path=args.report,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    report = campaign_report(
        _manifest(args.manifest),
        args.occurrences,
        args.clusters,
        args.evidence,
        args.consensus,
        args.ledger,
    )
    write_report(args.output, report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
