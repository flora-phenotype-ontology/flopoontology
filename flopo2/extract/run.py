"""Run the OpenRouter extraction engine over an ingested TextSegment JSONL file."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from pathlib import Path

import httpx

from flopo2.extract.engine import EngineConfig, extract_segment
from flopo2.extract.ground import load_lexicons
from flopo2.extract.router import OpenRouterClient
from flopo2.terminology.annotate import load_terminology_index


def _assertion_to_json(assertion, po_labels: dict[str, str], pato_labels: dict[str, str]) -> dict:
    return {
        "po_id": assertion.po_id,
        "pato_id": assertion.pato_id,
        "po_label": po_labels.get(assertion.po_id, assertion.po_id),
        "pato_label": pato_labels.get(assertion.pato_id, assertion.pato_id),
        "negated": assertion.negated,
        "negation_scope": assertion.negation_scope,
        "organ": assertion.organ,
        "source_text": assertion.source_text,
        "source_start": assertion.source_start,
        "source_end": assertion.source_end,
        "bearer_start": assertion.bearer_start,
        "bearer_end": assertion.bearer_end,
        "modality_start": assertion.modality_start,
        "modality_end": assertion.modality_end,
        "value_low": assertion.value_low,
        "value_high": assertion.value_high,
        "value_low_inclusive": assertion.value_low_inclusive,
        "value_high_inclusive": assertion.value_high_inclusive,
        "unit": assertion.unit,
        "value_text": assertion.value_text,
        "trait": assertion.trait,
        "modifier": assertion.modifier,
        "source_statement_id": assertion.source_statement_id,
        "frequency_qualifier": assertion.frequency_qualifier,
        "epistemic_modality": assertion.epistemic_modality,
        "value_qualifier": assertion.value_qualifier,
        "degree_qualifier": assertion.degree_qualifier,
        "modality_text": assertion.modality_text,
        "season_contexts": list(assertion.season_contexts),
        "season_operator": assertion.season_operator,
        "cardinality": assertion.cardinality,
        "confidence": assertion.confidence,
        "raw_entity_text": assertion.raw_entity_text,
        "raw_quality_text": assertion.raw_quality_text,
        "entity_mention_id": assertion.entity_mention_id,
        "quality_mention_ids": list(assertion.quality_mention_ids),
        "value_operator": assertion.value_operator,
        "value_terms": list(assertion.value_term_ids),
        "bearer_context_qualities": list(assertion.bearer_context_qualities),
        "developmental_stage_contexts": list(assertion.developmental_stage_contexts),
        "developmental_stage_operator": assertion.developmental_stage_operator,
        "normalization_status": assertion.normalization_status,
        "mapping_provenance": list(assertion.mapping_provenance),
        "extractor": assertion.extractor or "openrouter",
    }


def _row_key(row: dict) -> str:
    return "\t".join([
        str(row.get("source", "")),
        str(row.get("source_id", "")),
        str(row.get("taxon", "")),
        str(row.get("organ", "")),
        str(row.get("char_start", "")),
        str(row.get("char_end", "")),
    ])


def _load_done(path: Path) -> set[str]:
    done: set[str] = set()
    if not path.exists():
        return done
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            done.add(_row_key(json.loads(line)))
    return done


def run_file(
    input_path: Path,
    out_path: Path,
    cfg: EngineConfig,
    limit: int | None = None,
    concurrency: int = 8,
    resume: bool = True,
    request_timeout: float = 30.0,
    max_seconds: float | None = None,
    provider: dict | None = None,
) -> dict:
    rows = [json.loads(line) for line in input_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if limit is not None:
        rows = rows[:limit]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = _load_done(out_path) if resume else set()
    rows = [row for row in rows if _row_key(row) not in done]

    po_lex, pato_lex = load_lexicons()
    terminology = (
        load_terminology_index(cfg.terminology_registry)
        if cfg.use_terminology and cfg.terminology_mode in {"registry", "full"}
        else None
    )
    timeout = httpx.Timeout(connect=8.0, read=request_timeout, write=8.0, pool=8.0)
    client = OpenRouterClient(
        timeout=timeout,
        max_connections=max(8, concurrency * 2),
        provider=provider,
    )
    start = time.time()
    written = 0
    assertion_count = 0
    failed = 0

    def work(row: dict) -> dict:
        try:
            assertions = extract_segment(client, cfg, row)
            rec = dict(row)
            if terminology:
                rec["term_mentions"] = [
                    mention.to_dict()
                    for mention in terminology.annotate(
                        row.get("text", ""),
                        language=row.get("language", ""),
                        organ_context=row.get("organ", ""),
                        keep_overlaps=True,
                    )
                ]
            rec["assertions"] = [
                _assertion_to_json(a, po_lex.id_to_label, pato_lex.id_to_label)
                for a in assertions
            ]
            return rec
        except Exception as exc:
            rec = dict(row)
            rec["assertions"] = []
            rec["extract_error"] = f"{type(exc).__name__}: {exc}"
            return rec

    mode = "a" if resume else "w"
    out = out_path.open(mode, encoding="utf-8")
    pool = ThreadPoolExecutor(max_workers=concurrency)
    timed_out = False
    try:
        futures = {pool.submit(work, row): row for row in rows}
        try:
            iterator = as_completed(futures, timeout=max_seconds)
            for fut in iterator:
                rec = fut.result()
                if rec.get("extract_error"):
                    failed += 1
                assertion_count += len(rec.get("assertions", []) or [])
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                out.flush()
                written += 1
                if written == 1 or written % 25 == 0:
                    elapsed = max(time.time() - start, 1e-6)
                    rate = written / elapsed
                    print(
                        f"{written}/{len(rows)} rows, assertions={assertion_count}, "
                        f"failed={failed}, cost=${client.usage.cost_usd:.4f}, "
                        f"rate={rate:.2f}/s",
                        flush=True,
                    )
        except TimeoutError:
            timed_out = True
            print(f"max_seconds reached after {written}/{len(rows)} completed rows", flush=True)
    finally:
        # ``ThreadPoolExecutor`` workers are non-daemon threads.  Merely requesting a non-waiting
        # shutdown leaves in-flight HTTP requests alive and the interpreter still waits for them
        # at exit, defeating ``--max-seconds``.  Closing the shared client interrupts those
        # requests; then wait for the bounded workers to unwind before returning a resumable file.
        try:
            client.close()
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
            out.close()

    return {
        "input_rows_remaining": len(rows),
        "rows_written": written,
        "assertions": assertion_count,
        "failed": failed,
        "timed_out": timed_out,
        "usage": {
            "calls": client.usage.calls,
            "cost_usd": round(client.usage.cost_usd, 4),
            "escalations": client.usage.escalations,
            "by_model": client.usage.by_model,
        },
        "out": str(out_path),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Run OpenRouter extraction over TextSegment JSONL.")
    ap.add_argument("input", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("scratchpad/openrouter_assertions.jsonl"))
    ap.add_argument("--models", nargs="+", default=["openai/gpt-oss-120b"])
    ap.add_argument("--grounding", choices=["spires", "graphrag"], default="spires")
    ap.add_argument("--samples", type=int, default=1)
    ap.add_argument("--temperature", type=float, default=0.3)
    ap.add_argument("--no-terminology", action="store_true")
    ap.add_argument(
        "--terminology-mode",
        choices=["off", "ontology", "registry", "full"],
        default="full",
    )
    ap.add_argument(
        "--terminology-registry",
        default="config/botanical_terminology.tsv",
    )
    ap.add_argument("--terminology-limit", type=int, default=30)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--request-timeout", type=float, default=30.0)
    ap.add_argument("--max-seconds", type=float)
    ap.add_argument("--provider-sort", choices=["price", "throughput", "latency"])
    ap.add_argument("--provider-order", nargs="+")
    ap.add_argument("--no-provider-fallbacks", action="store_true")
    ap.add_argument("--require-parameters", action="store_true")
    ap.add_argument("--no-resume", action="store_true")
    args = ap.parse_args()
    cfg = EngineConfig(
        models=args.models,
        grounding=args.grounding,
        samples=args.samples,
        temperature=args.temperature,
        use_terminology=not args.no_terminology,
        terminology_mode="off" if args.no_terminology else args.terminology_mode,
        terminology_registry=args.terminology_registry,
        terminology_limit=args.terminology_limit,
    )
    provider = {}
    if args.provider_sort:
        provider["sort"] = args.provider_sort
    if args.provider_order:
        provider["order"] = args.provider_order
    if args.no_provider_fallbacks:
        provider["allow_fallbacks"] = False
    if args.require_parameters:
        provider["require_parameters"] = True
    result = run_file(
        args.input,
        args.out,
        cfg,
        limit=args.limit,
        concurrency=args.concurrency,
        resume=not args.no_resume,
        request_timeout=args.request_timeout,
        max_seconds=args.max_seconds,
        provider=provider or None,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
