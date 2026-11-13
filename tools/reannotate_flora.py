#!/usr/bin/env python3
"""Re-annotate finished floras after a change to the ontology, rules or annotator.

The Qwen caches of a flora (transcription, re-reads, term rules, relations) do not depend on the
ontology, so a change to the terms, the rule tables or ``ncvc_annotate`` only needs the last,
deterministic part of ``flopo2.ingest.pipeline`` again: the final annotation, the data-model
validation and the candidate staging. No endpoint is used.

    python -m tools.reannotate_flora powo-tong eflora-andes     # these floras
    python -m tools.reannotate_flora --done                     # every flora with a done marker

One line per flora goes to local-corpora/run-logs/reannotate.log.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

LOGS = Path("local-corpora/run-logs")


def reannotate(source: str) -> dict:
    from flopo2.ingest import flora_annotate, flora_candidates
    from flopo2.verify import annotation_class_check
    from flopo2.verify.data_model import validate_jsonl

    started = time.time()
    corpus = Path("local-corpora") / source
    derived = corpus / "derived"
    before = {}
    summary_path = derived / f"{source}-summary.json"
    if summary_path.exists():
        before = json.loads(summary_path.read_text(encoding="utf-8"))
    summary = flora_annotate.run(source, corpus / "raw" / f"{source}-qwen.jsonl", derived)
    try:  # ELK check of the annotation classes (flopo2.verify.annotation_class_check)
        class_check = annotation_class_check.check(source, derived / f"{source}-annotated.jsonl", derived)
    except Exception as exc:  # noqa: BLE001
        class_check = {"unsatisfiable": None, "note": f"failed: {type(exc).__name__}: {exc}"}
    errors = int(validate_jsonl(derived / f"{source}-annotated.jsonl", stage="gated").get("errors", 0))
    candidates = flora_candidates.extract_for_source(source, derived)
    result = {
        "source": source,
        "status": "done",
        "elapsed_s": round(time.time() - started, 1),
        "records": summary.get("records", 0),
        "rows": summary.get("rows", 0),
        "assertions": summary.get("assertions", 0),
        "assertions_before": before.get("assertions"),
        "unresolved_spans": summary.get("unresolved_spans", 0),
        "unresolved_before": before.get("unresolved_spans"),
        "data_model_errors": errors,
        "unsatisfiable_classes": class_check.get("unsatisfiable"),
        "class_check": class_check,
        "candidates": candidates,
    }
    steps = derived / ".pipeline-steps"
    if steps.is_dir():  # keep the pipeline's cached result in step with the corpus
        (steps / "result.json").write_text(json.dumps(result, default=str) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sources", nargs="*")
    parser.add_argument("--done", action="store_true", help="every flora with a done marker")
    args = parser.parse_args(argv)
    sources = list(args.sources)
    if args.done:
        sources += sorted(p.name for p in (LOGS / "done").iterdir() if p.name not in sources)
    for source in sources:
        try:
            result = reannotate(source)
            line = (f"{source}: assertions {result['assertions_before']} -> {result['assertions']}, "
                    f"unresolved {result['unresolved_before']} -> {result['unresolved_spans']}, "
                    f"data-model errors {result['data_model_errors']}, "
                    f"unsatisfiable classes {result['unsatisfiable_classes']}, {result['elapsed_s']:.0f} s")
        except Exception as exc:  # noqa: BLE001  (one flora must not stop the others)
            line = f"{source}: FAILED {type(exc).__name__}: {exc}"
        with (LOGS / "reannotate.log").open("a", encoding="utf-8") as handle:
            handle.write(f"== {datetime.now().astimezone().isoformat(timespec='seconds')} {line}\n")
        print(line, flush=True)


if __name__ == "__main__":
    main()
