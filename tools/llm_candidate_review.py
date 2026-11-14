"""Review of flora candidates by a second model (Claude Opus through the ``claude-max`` CLI).

Four queues, built from the finished floras:

* ``values``   quality words without a term (``curation/candidates/*/value_term_candidates.tsv``)
* ``bearers``  part names without a term (``.../bearer_candidates.tsv``)
* ``unions``   pairs of qualities stated as alternatives across attributes, not yet in
               ``config/flora_union_pairs.tsv`` (``tools.list_union_pair_candidates``)
* ``patterns`` statements the annotator left unresolved for a structural reason (alternatives,
               stage, relation, count, bound, negation, process), sampled per reason
* ``definitions`` the FLOPO value classes already added (``config/flopo_flora_value_terms.tsv``):
               is the definition correct, in genus-differentia form, and under the right parent?

    python -m tools.llm_candidate_review prepare          # write the batches
    python -m tools.llm_candidate_review run [--workers 2]   # until done or the account is out of credit
    python -m tools.llm_candidate_review collect          # one TSV per queue from the answers

Each batch is one headless session with read-only tools (Read, Grep, Glob) in the repository, so
the reviewer looks terms up in the lexicons instead of recalling identifiers. The answers are
proposals: ``collect`` writes them to ``curation/opus-review-<date>/``; nothing is applied to
the ontology or the rule tables by this tool.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import random
import re
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

OUT = Path("curation/opus-review-2026-11-14")
REVIEWED = Path("curation/flopo-flora-candidate-review-2026-11-13.tsv")
BATCH = {"values": 30, "bearers": 30, "unions": 40, "patterns": 40, "definitions": 25}
# Opus where the answer is a judgment about botany and modelling; Sonnet for the yes/no pairs.
MODEL = {"unions": "sonnet"}
PATTERN_REASONS = (
    "taxon_level_alternatives_or_continuum", "atomic_clause_contains_disjunction", "explicit_disjunction",
    "developmental_stage_context", "relation_to_another_part",
    "no_ontology_term:comparison or relation stated without its second term",
    "count_or_non_length_measurement", "no_ontology_term:count", "count_container_not_grounded",
    "count_per_position", "process_or_event", "negation_cue_not_in_source_span", "measurement_missing_unit",
    "numeric_quality_not_pato_attribute", "upper_bound_cue_not_supported",
    "flopo_phenotype_class_without_eq_signature",
)
PER_REASON = 220  # sampled statements per reason over all floras

COMMON = """You are reviewing candidates for FLOPO, the Flora Phenotype Ontology, in its repository (the
current directory). Plant phenotypes are annotated as entity + quality: a bearer from the Plant
Ontology (PO) or a FLOPO anatomy class, and a quality from PATO or a FLOPO value class
(FLOPO:0991xxx). Look identifiers up, do not recall them:

- config/pato_lexicon.tsv (PATO id, label, synonyms), ont/quality.obo (definitions)
- config/po_lexicon.tsv (PO id, label, synonyms), ont/plant_ontology.obo
- config/flopo_flora_value_terms.tsv (FLOPO value classes already added, with definitions)
- curation/flopo-flora-candidate-review-2026-11-13.tsv (the previous review: its decisions are the
  model for yours; read some rows of each decision type first)
- docs/odp/README.md and docs/odp/*.md (the annotation patterns), config/flora_context_words.tsv,
  config/flora_union_pairs.tsv, config/flora_counted_parts.tsv

Use Grep on these files; do not read the large .obo files whole. Do not modify anything. Be a
careful botanist and ontologist: prefer an existing term to a new one, a rule to a term, and
"rejected" to a doubtful term. The data below is in JSON.

Answer with ONE fenced ```json block holding an array with one object per item, in the order
given, and nothing after it.
"""

PROMPTS = {
    "values": COMMON + """
TASK: quality words that floras use and that have no term. For each word decide:

- "rule:pato": the word means an existing PATO quality (target: "<label> (PATO_nnnnnnn)")
- "rule:flopo_value": it means an existing FLOPO value class (target: "<label> (FLOPO:0991nnn)")
- "rule:negated_value": it negates an existing quality ("unlobed" = not lobed)
- "rule:entity_presence" / "rule:entity_absence": it states that a part is present or absent
  ("lenticellate" = lenticel present; "ebracteate" = bract absent); target "<part> (PO id) present|absent"
- "rule:bearer": the word is a part, not a quality (target: the PO or FLOPO class)
- "pattern": the word needs an annotation pattern, not a term (a comparison, a count such as
  "few-flowered", a compound of two values such as "oblong-ovate", a stage, a position of a
  series); target: the pattern file under docs/odp or "new: <short name>"
- "new_class": a genuine botanical quality with no existing term; give label, parent (a PATO or
  FLOPO id that exists) and a genus-differentia definition in the style of the previous review
- "rejected": vague, not a quality, a transcription fragment, or meaningless without context

Fields per item: word, decision, target, label, parent, definition, synonyms (list), reason
(one or two sentences), confidence ("high" | "medium" | "low"). Leave unused fields "".
""",
    "bearers": COMMON + """
TASK: names of plant parts that floras use and that did not ground to a class. For each decide:

- "rule:bearer": it is (a synonym of, or a narrower name used for) an existing PO or FLOPO
  anatomy class; target "<label> (PO_nnnnnnn)"; say in reason whether exact or narrower
- "rule:bearer_part": it is a region or kind of an existing class that the patterns can express
  (a part of a qualified whole, a region such as apex/base/margin, a position in a series);
  target: the class and how
- "new_class": a real plant structure without a class, needed by several floras; give label,
  parent (an existing PO id as is_a, and part_of if clear, in "parent") and a definition; say
  whether it should be proposed to PO upstream
- "not_a_part": a quality, a taxon, a habitat, a substance or a fragment
- "rejected": ambiguous without context

Fields per item: word, decision, target, label, parent, definition, synonyms (list), reason,
confidence ("high" | "medium" | "low").
""",
    "unions": COMMON + """
TASK: read docs/odp/07-alternatives.md first. A flora wrote "A or B" of one part, and A and B
have no common attribute in PATO, so the usual union (alternative values of one attribute) does
not apply. A secondary pattern can state the alternative across attributes, but only for pairs a
reviewer accepts: the check that alternatives share an attribute catches wrong groundings.

- "accept": A and B are real alternatives of the same character in botany (erect or curved;
  woody or fleshy), and both groundings fit the example
- "reject": the pair shows a wrong grounding of A or B, a list of unrelated characters, or
  values of different parts
- "same_attribute": they are alternatives and should share an attribute; name the missing
  subclass link or common parent in target (a gap in PATO/FLOPO rather than a secondary union)

Fields per item: value_a, value_b, decision, target, reason, confidence.
""",
    "patterns": COMMON + """
TASK: statements that the annotator transcribed but could not annotate, with the reason it gave.
Read docs/odp/README.md and docs/annotation-context-patterns.md first: they list the patterns
that exist and what is still open. For each statement say what it would take to annotate it:

- "existing_pattern": a pattern in docs/odp covers it and the annotator missed it; target: the
  pattern file; in fix say what is missing (a cue word, a table row, a grounding rule)
- "missing_term": the structure is fine, a term is missing; target: the word and what it means
- "new_pattern": no pattern covers it; target: a short, reusable name for the pattern (use the
  same name for the same construction across items); in fix sketch the representation
  (slots, and the OWL or RDF side) in two or three sentences
- "not_annotatable": not a phenotype of the taxon (distribution, use, taxonomy, comparison with
  another taxon), or too vague
- "transcription_error": the transcribed entity or quality does not match the text

Fields per item: id, decision, target, fix, reason, confidence ("high" | "medium" | "low").
""",
    "definitions": COMMON + """
TASK: FLOPO value classes that are already in the ontology, with their parent and definition.
Check each against botanical usage (the definitions of standard glossaries as you know them) and
against PATO (ont/quality.obo: the parent's definition, and whether PATO already has the term):

- "keep": the definition is correct and well formed
- "rewrite": the meaning is right but the text should change (not genus-differentia, circular,
  too narrow or too wide, names the wrong bearer, unclear); give the new text in definition, in
  the form "A <parent label> quality inhering in a bearer by virtue of the bearer's ..." used by
  PATO and by the other rows
- "problem": the class itself is doubtful: wrong parent (give the right one in parent), duplicate
  of an existing PATO class (target), two meanings in one class, or a synonym that does not fit

Fields per item: flopo_id, label, decision, definition, parent, target, reason, confidence.
""",
}


def _labels() -> dict[str, str]:
    labels: dict[str, str] = {}
    for path in ("config/po_lexicon.tsv", "config/pato_lexicon.tsv"):
        with open(path, encoding="utf-8") as handle:
            labels.update((row["id"], row["label"]) for row in csv.DictReader(handle, delimiter="\t"))
    with open("config/flopo_flora_value_terms.tsv", encoding="utf-8") as handle:
        labels.update((row["flopo_id"].replace(":", "_"), row["label"]) for row in csv.DictReader(handle, delimiter="\t"))
    return labels


def _candidates(file_name: str, key: str, extra: str) -> list[dict]:
    with REVIEWED.open(encoding="utf-8") as handle:
        done = {row["word"] for row in csv.DictReader(handle, delimiter="\t")}
    labels = _labels()
    merged: dict[str, dict] = {}
    for path in sorted(glob.glob(f"curation/candidates/*/{file_name}")):
        with open(path, encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                word = row[key]
                if word in done or not word.strip():
                    continue
                item = merged.setdefault(word, {"word": word, "floras": 0, "statements": 0, "seen": Counter(), "examples": []})
                item["floras"] += 1
                item["statements"] += int(row["count"])
                item["seen"].update({v: int(row["count"]) for v in row[extra].split("|")[:5] if v})
                item["examples"].extend(e.strip() for e in row["example_phrases"].split(" ; ")[:2])
    items = sorted(merged.values(), key=lambda i: (-min(i["floras"], 10), -i["statements"]))
    for item in items:
        seen = [f"{labels.get(v, v)} ({v})" if v in labels else v for v, _ in item.pop("seen").most_common(6)]
        item["with"] = seen
        item["examples"] = list(dict.fromkeys(item["examples"]))[:6]
    return [i for i in items if i["floras"] >= 2 or i["statements"] >= 10]


def _unions() -> list[dict]:
    path = Path("local-corpora/cache/union_pairs_all.tsv")
    subprocess.run([sys.executable, "-m", "tools.list_union_pair_candidates", "-o", str(path)], check=True,
                   capture_output=True)
    with path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return [{k: row[k] for k in ("value_a", "value_b", "label_a", "label_b", "example", "rows", "floras")} for row in rows]


def _definitions() -> list[dict]:
    labels = _labels()
    with open("config/flopo_flora_value_terms.tsv", encoding="utf-8") as handle:
        rows = [row for row in csv.DictReader(handle, delimiter="\t") if not row.get("replaced_by")]
    return [{"flopo_id": r["flopo_id"], "label": r["label"], "parent": r["parent"],
             "parent_label": labels.get(r["parent"].replace(":", "_"), ""), "definition": r["definition"],
             "exact_synonyms": r["exact_synonyms"], "related_synonyms": r["related_synonyms"],
             "bearers": [labels.get(b.replace(":", "_"), b) for b in r["bearers"].split("|") if b][:6],
             "status": r["status"]} for r in rows]


def _patterns(seed: int = 20261114) -> list[dict]:
    """Reservoir sample of unresolved statements per reason, over all floras."""

    rng = random.Random(seed)
    sample: dict[str, list] = defaultdict(list)
    seen: Counter = Counter()
    for path in sorted(glob.glob("local-corpora/*/derived/*-annotated.jsonl")):
        source = Path(path).name.removesuffix("-annotated.jsonl")
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                if '"unresolved_spans": []' in line:
                    continue
                record = json.loads(line)
                text = record.get("text") or ""
                for span in record.get("unresolved_spans") or []:
                    reason = span.get("reason") or ""
                    if reason not in PATTERN_REASONS:
                        continue
                    seen[reason] += 1
                    start, end = int(span.get("start") or 0), int(span.get("end") or 0)
                    item = {
                        "flora": source, "taxon": record.get("taxon", ""), "reason": reason,
                        "statement": span.get("surface_form", ""),
                        "transcribed_entity": span.get("transcribed_entity", ""),
                        "transcribed_quality": span.get("transcribed_quality", ""),
                        "context": text[max(0, start - 160):end + 120],
                    }
                    bucket = sample[reason]
                    if len(bucket) < PER_REASON:
                        bucket.append(item)
                    else:
                        slot = rng.randrange(seen[reason])
                        if slot < PER_REASON:
                            bucket[slot] = item
    items = [item for reason in PATTERN_REASONS for item in sample[reason]]
    rng.shuffle(items)
    for index, item in enumerate(items):
        item["id"] = f"P{index:05d}"
    (OUT / "patterns-population.json").write_text(json.dumps(seen, indent=1), encoding="utf-8")
    return items


def prepare(queues: list[str]) -> None:
    builders = {
        "values": lambda: _candidates("value_term_candidates.tsv", "candidate_label", "bearers"),
        "bearers": lambda: _candidates("bearer_candidates.tsv", "candidate_bearer", "qualities_seen"),
        "unions": _unions, "patterns": _patterns, "definitions": _definitions,
    }
    for queue in queues:
        folder = OUT / "batches" / queue
        folder.mkdir(parents=True, exist_ok=True)
        items = builders[queue]()
        size = BATCH[queue]
        for number, start in enumerate(range(0, len(items), size)):
            path = folder / f"{number:04d}.json"
            if not path.exists():
                path.write_text(json.dumps(items[start:start + size], ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{queue}: {len(items)} items, {-(-len(items) // size)} batches")


_JSON_BLOCK = re.compile(r"```json\s*(.*?)```", re.S)
_OUT_OF_CREDIT = re.compile(r"usage limit|limit reached|out of (extra )?usage|credit balance|rate.?limit|overloaded|quota", re.I)


def _review(queue: str, batch: Path, command: str, model: str, timeout: int) -> str:
    """'done' | 'limit' | 'failed'; writes <batch>.answer.json (the parsed array) and .meta.json."""

    prompt = PROMPTS[queue] + "\nITEMS:\n" + batch.read_text(encoding="utf-8")
    try:
        done = subprocess.run(
            [command, "-p", "--model", model, "--tools", "Read,Grep,Glob", "--output-format", "json"],
            input=prompt, capture_output=True, text=True, timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired:
        return "failed"
    try:
        envelope = json.loads(done.stdout)
    except json.JSONDecodeError:
        envelope = {"is_error": True, "result": (done.stdout + done.stderr)[-2000:]}
    result = str(envelope.get("result") or "")
    meta = {k: envelope.get(k) for k in ("is_error", "subtype", "num_turns", "duration_ms", "total_cost_usd")}
    meta["models"] = sorted(envelope.get("modelUsage") or {})
    if envelope.get("is_error") or done.returncode:
        meta["error"] = result[-600:]
        batch.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
        return "limit" if _OUT_OF_CREDIT.search(result) else "failed"
    blocks = _JSON_BLOCK.findall(result)
    try:
        answer = json.loads(blocks[-1] if blocks else result)
    except json.JSONDecodeError:
        batch.with_suffix(".raw.txt").write_text(result, encoding="utf-8")
        return "failed"
    batch.with_suffix(".answer.json").write_text(json.dumps(answer, ensure_ascii=False, indent=1), encoding="utf-8")
    batch.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return "done"


def run(queues: list[str], workers: int, command: str, model: str, timeout: int, limit: int | None) -> None:
    pending = {q: sorted(p for p in (OUT / "batches" / q).glob("[0-9]*.json")
                         if p.name.count(".") == 1 and not p.with_suffix(".answer.json").exists()) for q in queues}
    order = []  # round robin over the queues, so each gets its share before the credit ends
    while any(pending.values()):
        order.extend((q, pending[q].pop(0)) for q in queues if pending[q])
    order = order[:limit] if limit else order
    log = OUT / "run.log"
    stop = False

    def work(job: tuple[str, Path]) -> None:
        nonlocal stop
        if stop:
            return
        queue, batch = job
        started = time.time()
        use = model or MODEL.get(queue, "opus")
        status = _review(queue, batch, command, use, timeout)
        if status == "failed" and not stop:
            status = _review(queue, batch, command, use, timeout)
        if status == "limit":
            stop = True
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {queue}/{batch.name} {status} {time.time() - started:.0f} s\n")

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(work, order))
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} "
                     f"{'stopped: the account is out of credit' if stop else 'all batches done'}\n")


def collect(queues: list[str]) -> None:
    for queue in queues:
        rows = []
        for answer in sorted((OUT / "batches" / queue).glob("*.answer.json")):
            items = {str(i.get("word") or i.get("id") or i.get("flopo_id") or f"{i.get('value_a')}|{i.get('value_b')}"): i
                     for i in json.loads(answer.with_name(answer.name.replace(".answer", "")).read_text(encoding="utf-8"))}
            for row in json.loads(answer.read_text(encoding="utf-8")):
                if not isinstance(row, dict):
                    continue
                key = str(row.get("word") or row.get("id") or row.get("flopo_id") or f"{row.get('value_a')}|{row.get('value_b')}")
                given = items.get(key, {})
                merged = {**{k: v for k, v in given.items() if k not in ("examples", "with", "context")}, **row,
                          "example": " ; ".join(given.get("examples") or [])[:300] or given.get("example", "")
                          or given.get("context", "")[:300], "batch": answer.name[:4]}
                rows.append({k: "|".join(v) if isinstance(v, list) else v for k, v in merged.items()})
        if not rows:
            continue
        fields = list(dict.fromkeys(k for row in rows for k in row))
        with (OUT / f"{queue}.tsv").open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, delimiter="\t", lineterminator="\n", fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        print(f"{queue}: {len(rows)} reviewed; " + ", ".join(f"{k} {v}" for k, v in Counter(r.get('decision', '') for r in rows).most_common()))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["prepare", "run", "collect"])
    parser.add_argument("--queues", default="values,patterns,definitions,bearers,unions")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--command", default="claude-max")
    parser.add_argument("--model", help="one model for every queue (default: opus, sonnet for unions)")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--limit", type=int, help="at most this many batches (for a trial)")
    args = parser.parse_args(argv)
    queues = args.queues.split(",")
    OUT.mkdir(parents=True, exist_ok=True)
    if args.action == "prepare":
        prepare(queues)
    elif args.action == "run":
        run(queues, args.workers, args.command, args.model, args.timeout, args.limit)
    else:
        collect(queues)


if __name__ == "__main__":
    main()
