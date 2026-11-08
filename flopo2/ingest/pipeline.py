"""End-to-end multi-flora extraction, grounding, gating, validation, and FLOPO candidate staging.

Implements the 7-stage pipeline from ``docs/flora-annotation-playbook.md`` for any flora in
:data:`flopo2.ingest.external.FLORA_SOURCES`:

1. Segment ingestion (``flopo2.ingest.external.dump_segments``)
2. Qwen transcription on ``unimatrix01`` (``flopo2.ingest.flora_llm``)
3. Initial deterministic grounding & gating (``flopo2.ingest.flora_annotate``)
4. LLM re-read of malformed/unmatched rows (``flopo2.ingest.llm_reread``) + re-annotation
5. LLM lexical candidate matching for remaining unmatched words (``flopo2.ingest.llm_term_rules``)
6. LLM endpoint anchoring for qualitative relations & chains (``flopo2.ingest.llm_relations``)
7. Final deterministic annotation, ``flopo2.verify.data_model --stage gated`` validation, and
   per-flora FLOPO candidate staging (``flopo2.ingest.flora_candidates``).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from flopo2.ingest import flora_annotate, flora_candidates, flora_llm, llm_relations, llm_reread, llm_term_rules
from flopo2.ingest.collenette_llm import DEFAULT_BASE_URL, DEFAULT_KEY_FILE, DEFAULT_MODEL
from flopo2.ingest.external import FLORA_SOURCES, dump_segments
from flopo2.verify.data_model import validate_jsonl


def run_flora_pipeline(
    source: str,
    *,
    limit: int = 0,
    workers: int = 16,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    key_file: Path = DEFAULT_KEY_FILE,
    skip_llm_refinement: bool = False,
) -> dict:
    if source not in FLORA_SOURCES:
        raise ValueError(f"Unknown flora source {source!r}; choices: {sorted(FLORA_SOURCES)}")

    t0 = time.time()
    corpus_dir = Path("local-corpora") / source
    raw_dir = corpus_dir / "raw"
    derived_dir = corpus_dir / "derived"
    segments_path = raw_dir / f"{source}-segments.jsonl"
    qwen_path = raw_dir / f"{source}-qwen.jsonl"
    annotated_path = derived_dir / f"{source}-annotated.jsonl"
    dispositions_path = derived_dir / f"{source}-dispositions.tsv"

    # Stage 1: Dump segments if not already present (or if fewer than limit)
    dump_segments(source, out=segments_path, limit=limit)

    # Stage 2: Transcribe with Qwen on unimatrix01
    flora_llm_argv = [
        source,
        "--segments", str(segments_path),
        "--out", str(qwen_path),
        "--workers", str(workers),
        "--base-url", base_url,
        "--model", model,
        "--key-file", str(key_file),
    ]
    if limit:
        flora_llm_argv.extend(["--limit", str(limit)])
    flora_llm.main(flora_llm_argv)

    # Stage 3: Initial annotation
    flora_annotate.run(source, qwen_path, derived_dir)

    if not skip_llm_refinement:
        # Stage 4: LLM re-read of unmatched rows + re-annotation
        reread_cache = corpus_dir / "llm-rereads.jsonl"
        llm_reread.main([
            str(annotated_path),
            str(dispositions_path),
            "--out", str(reread_cache),
            "--workers", str(workers),
            "--base-url", base_url,
            "--model", model,
            "--key-file", str(key_file),
        ])
        flora_annotate.run(source, qwen_path, derived_dir)

        # Stage 5: LLM lexical term rules for remaining unmatched words (shared decision cache)
        term_rules_path = corpus_dir / "llm-term-rules.tsv"
        term_decisions_cache = Path("local-corpora/external-floras/llm-term-decisions.jsonl")
        llm_term_rules.main([
            str(dispositions_path),
            "--out", str(term_rules_path),
            "--cache", str(term_decisions_cache),
            "--workers", str(min(workers, 12)),
            "--base-url", base_url,
            "--model", model,
            "--key-file", str(key_file),
        ])

        # Stage 6: LLM qualitative value relations and chains
        rel_cache = corpus_dir / "llm-relations.jsonl"
        chain_cache = corpus_dir / "llm-relation-chains.jsonl"
        llm_relations.main([
            str(annotated_path),
            str(dispositions_path),
            "--out", str(rel_cache),
            "--chain-out", str(chain_cache),
            "--workers", str(workers),
            "--base-url", base_url,
            "--model", model,
            "--key-file", str(key_file),
        ])

        # Stage 7a: Final deterministic annotation with all caches & rules
        summary = flora_annotate.run(source, qwen_path, derived_dir)
    else:
        summary = json.loads((derived_dir / f"{source}-summary.json").read_text(encoding="utf-8"))

    # Stage 7b: Validate against the gated trait data model
    val_report = validate_jsonl(annotated_path, stage="gated")
    n_errors = int(val_report.get("errors", 0))
    print(
        f"[{source}] Stage 7: {summary.get('assertions', 0)} assertions, "
        f"data_model errors={n_errors}",
        flush=True,
    )

    # Stage 7c: Extract FLOPO addition candidates
    cand_summary = flora_candidates.extract_for_source(source, derived_dir)
    elapsed = round(time.time() - t0, 1)
    return {
        "source": source,
        "elapsed_s": elapsed,
        "records": summary.get("records", 0),
        "rows": summary.get("rows", 0),
        "assertions": summary.get("assertions", 0),
        "unresolved_spans": summary.get("unresolved_spans", 0),
        "data_model_errors": n_errors,
        "candidates": cand_summary,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("sources", nargs="+", help="Flora source key(s) to process")
    parser.add_argument("--limit", type=int, default=0, help="Max segments per flora (0 = all)")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--key-file", type=Path, default=DEFAULT_KEY_FILE)
    parser.add_argument("--skip-llm-refinement", action="store_true")
    args = parser.parse_args(argv)

    results = []
    for src in args.sources:
        res = run_flora_pipeline(
            src,
            limit=args.limit,
            workers=args.workers,
            base_url=args.base_url,
            model=args.model,
            key_file=args.key_file,
            skip_llm_refinement=args.skip_llm_refinement,
        )
        results.append(res)
    rollup = flora_candidates.build_rollup()
    print(json.dumps({"results": results, "rollup": rollup}, indent=1))


if __name__ == "__main__":
    main()
