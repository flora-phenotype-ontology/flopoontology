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
import sys
import time
from pathlib import Path

from flopo2.ingest import flora_annotate, flora_candidates, flora_llm, llm_relations, llm_reread, llm_term_rules
from flopo2.ingest.collenette_llm import DEFAULT_BASE_URL, DEFAULT_KEY_FILE, DEFAULT_MODEL
from flopo2.ingest.external import FLORA_SOURCES, dump_segments
from flopo2.verify.data_model import validate_jsonl


STEP_DIR = ".pipeline-steps"


def _signature(paths: list[Path]) -> dict:
    out = {}
    for path in paths:
        try:
            stat = path.stat()
            out[str(path)] = [stat.st_size, stat.st_mtime_ns]
        except FileNotFoundError:
            out[str(path)] = None
    return out


class _StepMarkers:
    """Completion markers for the pipeline's steps.

    A step counts as done while the caches it depends on are unchanged since it last completed, so
    a rerun (after a crash, a preemption or a lost endpoint) skips the hour-long annotation passes
    of a large flora and goes straight to the first unfinished step. The markers do not see changes
    to the ontology, lexicons or code: pass ``redo`` after such changes.
    """

    def __init__(self, derived_dir: Path, redo: bool) -> None:
        self.dir = derived_dir / STEP_DIR
        self.dir.mkdir(parents=True, exist_ok=True)
        if redo:
            for marker in self.dir.glob("*.json"):
                marker.unlink()

    def done(self, name: str, inputs: list[Path]) -> bool:
        marker = self.dir / f"{name}.json"
        return marker.exists() and json.loads(marker.read_text(encoding="utf-8")) == _signature(inputs)

    def mark(self, name: str, inputs: list[Path]) -> None:
        (self.dir / f"{name}.json").write_text(json.dumps(_signature(inputs)) + "\n", encoding="utf-8")


def _transcription_todo(segments_path: Path, qwen_path: Path) -> int:
    """Segments without a successful transcription (error rows are superseded by later good rows)."""

    ok = set()
    if qwen_path.exists():
        with qwen_path.open(encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "error" not in row:
                    ok.add(row.get("source_id"))
    with segments_path.open(encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip() and json.loads(line).get("source_id") not in ok)


def run_flora_pipeline(
    source: str,
    *,
    limit: int = 0,
    workers: int = 16,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    key_file: Path = DEFAULT_KEY_FILE,
    skip_llm_refinement: bool = False,
    steps: str = "all",
    redo: bool = False,
) -> dict:
    """Run the pipeline's steps in order, skipping completed ones.

    ``steps`` restricts which kind of step may run: ``"llm"`` (steps that call the Qwen endpoint),
    ``"cpu"`` (deterministic steps) or ``"all"``. The run stops at the first unfinished step of the
    other kind and returns ``{"status": "needs-llm"}`` or ``{"status": "needs-cpu"}``, so a GPU
    endpoint is held only while LLM steps run (``tools/orix_flora_lane.py``).
    """

    if source not in FLORA_SOURCES:
        raise ValueError(f"Unknown flora source {source!r}; choices: {sorted(FLORA_SOURCES)}")
    if steps not in {"all", "llm", "cpu"}:
        raise ValueError(f"steps must be all, llm or cpu, not {steps!r}")

    t0 = time.time()
    corpus_dir = Path("local-corpora") / source
    raw_dir = corpus_dir / "raw"
    derived_dir = corpus_dir / "derived"
    segments_path = raw_dir / f"{source}-segments.jsonl"
    qwen_path = raw_dir / f"{source}-qwen.jsonl"
    annotated_path = derived_dir / f"{source}-annotated.jsonl"
    dispositions_path = derived_dir / f"{source}-dispositions.tsv"
    reread_cache = corpus_dir / "llm-rereads.jsonl"
    term_rules_path = corpus_dir / "llm-term-rules.tsv"
    term_decisions_cache = Path("local-corpora/external-floras/llm-term-decisions.jsonl")
    rel_cache = corpus_dir / "llm-relations.jsonl"
    chain_cache = corpus_dir / "llm-relation-chains.jsonl"
    endpoint = ["--base-url", base_url, "--model", model, "--key-file", str(key_file)]
    markers = _StepMarkers(derived_dir, redo or bool(limit))

    def transcribe() -> None:
        argv = [source, "--segments", str(segments_path), "--out", str(qwen_path), "--workers", str(workers), *endpoint]
        if limit:
            argv.extend(["--limit", str(limit)])
        flora_llm.main(argv)

    def annotate() -> dict:
        return flora_annotate.run(source, qwen_path, derived_dir)

    def reread() -> None:
        llm_reread.main([str(annotated_path), str(dispositions_path), "--out", str(reread_cache),
                         "--workers", str(workers), *endpoint])

    def term_rules() -> None:
        llm_term_rules.main([str(dispositions_path), "--out", str(term_rules_path), "--cache", str(term_decisions_cache),
                             "--workers", str(min(workers, 12)), *endpoint])

    def relations() -> None:
        llm_relations.main([str(annotated_path), str(dispositions_path), "--out", str(rel_cache),
                            "--chain-out", str(chain_cache), "--workers", str(workers), *endpoint])

    # (name, kind, depends-on caches, action). Each step reads what the steps before it wrote; its
    # marker keys on the caches upstream of it, since the annotated corpus is rewritten by every
    # annotation pass.
    plan = [("annotate-initial", "cpu", [qwen_path], annotate)]
    if not skip_llm_refinement:
        plan += [
            ("reread", "llm", [qwen_path], reread),
            ("annotate-reread", "cpu", [qwen_path, reread_cache], annotate),
            ("term-rules", "llm", [qwen_path, reread_cache], term_rules),
            ("relations", "llm", [qwen_path, reread_cache], relations),
            ("annotate-final", "cpu", [qwen_path, reread_cache, term_rules_path, rel_cache, chain_cache], annotate),
        ]

    # Stage 1: segments (cheap when present).
    dump_segments(source, out=segments_path, limit=limit)
    # Stage 2: Qwen transcription; pending while a segment lacks a good transcription and no
    # attempt has been made on the cache as it stands (segments that fail every retry would
    # otherwise hold the flora back for good; rerunning the step retries them).
    if limit or (_transcription_todo(segments_path, qwen_path) and not markers.done("transcribe", [qwen_path])):
        if steps == "cpu":
            return {"source": source, "status": "needs-llm", "next_step": "transcribe"}
        transcribe()
        markers.mark("transcribe", [qwen_path])
    # Stages 3-7a: annotation passes and the LLM refinements.
    for name, kind, inputs, action in plan:
        if markers.done(name, inputs):
            continue
        if steps not in {"all", kind}:
            return {"source": source, "status": f"needs-{kind}", "next_step": name}
        print(f"[{source}] step {name}", flush=True)
        action()
        markers.mark(name, inputs)

    summary = json.loads((derived_dir / f"{source}-summary.json").read_text(encoding="utf-8"))
    result_path = derived_dir / STEP_DIR / "result.json"
    if markers.done("candidates", [annotated_path]) and result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    if steps == "llm":  # validation and candidate staging are deterministic
        return {"source": source, "status": "needs-cpu", "next_step": "candidates"}

    # Stage 7a: ELK check of the annotation classes; contradictory ones are set to review
    from flopo2.verify import annotation_class_check

    try:
        class_check = annotation_class_check.check(source, annotated_path, derived_dir)
    except Exception as exc:  # noqa: BLE001  (the check must not lose a finished flora)
        class_check = {"unsatisfiable": None, "note": f"failed: {type(exc).__name__}: {exc}"}
    print(f"[{source}] Stage 7a: annotation classes unsatisfiable={class_check.get('unsatisfiable')} "
          f"taxa with a contradiction={class_check.get('taxon_contradictions')} "
          f"{class_check.get('note', '')}", flush=True)

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
    result = {
        "source": source,
        "status": "done",
        "elapsed_s": elapsed,
        "records": summary.get("records", 0),
        "rows": summary.get("rows", 0),
        "assertions": summary.get("assertions", 0),
        "unresolved_spans": summary.get("unresolved_spans", 0),
        "data_model_errors": n_errors,
        "unsatisfiable_classes": class_check.get("unsatisfiable"),
        "taxon_contradictions": class_check.get("taxon_contradictions"),
        "class_check": class_check,
        "candidates": cand_summary,
    }
    result_path.write_text(json.dumps(result, default=str) + "\n", encoding="utf-8")
    markers.mark("candidates", [annotated_path])
    return result


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
    parser.add_argument("--steps", choices=["all", "llm", "cpu"], default="all",
                        help="run only LLM or only deterministic steps; exit 10 when an LLM step is next, "
                             "11 when a deterministic one is")
    parser.add_argument("--redo", action="store_true",
                        help="ignore the step markers (after ontology, lexicon or code changes)")
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
            steps=args.steps,
            redo=args.redo,
        )
        results.append(res)
    pending = {r["status"] for r in results} - {"done"}
    if pending:
        print(json.dumps({"results": results}, indent=1))
        sys.exit(10 if "needs-llm" in pending else 11)
    rollup = flora_candidates.build_rollup()
    print(json.dumps({"results": results, "rollup": rollup}, indent=1))


if __name__ == "__main__":
    main()
