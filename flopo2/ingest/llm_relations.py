"""Locate the endpoints of alternatives and continua with an LLM, for qualitative value relations.

``ncvc_annotate.build_relation`` turns "ovate to oblong" into a qualitative value relation when
the transcribed quality and its alternative are found verbatim around a connector.  The rows it
cannot resolve ("ovoid to globose" transcribed as "ovate", "yellow, rarely white", "purple, then
turning black when ripe") are sent to the model, which returns the verbatim from/connector/to
spans, a plain botanical term for each endpoint, and the interpretation.  Nothing is accepted on
the model's word: ``ncvc_annotate`` re-locates the spans verbatim and in order in the source text,
grounds both terms through the normal rules and lexicons, and requires a shared PATO attribute.

Output: ``local-corpora/saudi-flora/llm-relations.jsonl`` keyed by (source_id, row); cached.
"""

from __future__ import annotations

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flopo2.ingest.collenette_llm import DEFAULT_BASE_URL, DEFAULT_KEY_FILE, DEFAULT_MODEL, _key, call, parse_json

CACHE = Path("local-corpora/saudi-flora/llm-relations.jsonl")
CHAIN_CACHE = Path("local-corpora/saudi-flora/llm-relation-chains.jsonl")
REASONS = {"taxon_level_alternatives_or_continuum", "explicit_disjunction"}

PROMPT = """A botanical description states two alternative or intermediate values of one quality of a
plant part. Identify them exactly.

Plant part: {entity}
Transcribed quality: {quality}
Sentence: "{sentence}"
Phrase: "{phrase}"

Return JSON:
{{"from_text": "<verbatim words of the first value, copied from the sentence>",
  "connector_text": "<verbatim words between the two values, e.g. 'to', 'or', 'tending to', ', rarely', ', then turning'>",
  "to_text": "<verbatim words of the second value>",
  "from_term": "<the first value as one standard botanical quality term, e.g. ovoid, yellow, shrub>",
  "to_term": "<the second value as one standard botanical quality term>",
  "interpretation": "continuum | taxon_level_alternatives | temporal_transition"}}
Use "continuum" for X to Y or X tending to Y (intermediate values occur), "taxon_level_alternatives"
for X or Y / X, rarely Y (either occurs in the taxon), "temporal_transition" for X becoming/turning Y
(one changes into the other with time or maturity). from_text, connector_text and to_text must be
consecutive in the sentence in this order. If the phrase does not state exactly two values of
the same quality (e.g. three values, or two different qualities such as 'yellow and green' meaning
both colours together), return {{"skip": "<reason>"}}."""


CHAIN_PROMPT = """A botanical description lists three or more alternative or intermediate values of one
quality of a plant part. Split the phrase into its values, in order, exactly as written.

Plant part: {entity}
Transcribed quality: {quality}
Sentence: "{sentence}"
Phrase: "{phrase}"

Return JSON:
{{"values": [{{"text": "<verbatim words of value 1>", "term": "<value 1 as one standard botanical quality term>"}}, ...],
  "connectors": [{{"text": "<verbatim words between value 1 and value 2, e.g. ', ' or ' or ' or ' to '>",
                   "interpretation": "continuum | taxon_level_alternatives | temporal_transition"}}, ...]}}
There is one connector between each pair of consecutive values; values and connectors must be
consecutive in the sentence in this order. "X to Y" is a continuum, "X, Y or Z" are alternatives in
the taxon, "X becoming Y" is a temporal transition. If the values belong to different qualities or
the phrase is not a list of values, return {{"skip": "<reason>"}}."""


def _sentence(text: str, phrase: str) -> str:
    at = text.find(phrase)
    if at < 0:
        return text[:400]
    left = max(text.rfind(".", 0, at) + 1, 0)
    right = text.find(".", at + len(phrase))
    return text[left : right + 1 if right >= 0 else len(text)].strip()


def collect(corpora: list[tuple[Path, Path]]) -> list[dict]:
    """Rows to resolve from (annotated JSONL, dispositions TSV) pairs."""

    items = []
    for corpus, dispositions in corpora:
        texts = {}
        for line in corpus.open(encoding="utf-8"):
            record = json.loads(line)
            if record.get("language") == "en" and record.get("organ") == "description":
                texts[record["source_id"]] = record["text"]
        with dispositions.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row["reason"] not in REASONS:
                    continue
                text = texts.get(row["source_id"], "")
                items.append(
                    {
                        "source_id": row["source_id"],
                        "row": int(row["row"]),
                        "entity": row["entity_en"],
                        "quality": row["quality_en"],
                        "phrase": row["source_en"],
                        "sentence": _sentence(text, row["source_en"]),
                    }
                )
    return items


def resolve(item: dict, *, base_url: str, model: str, key: str) -> dict:
    prompt = PROMPT.format(**{k: str(v).replace('"', "'") for k, v in item.items()})
    try:
        content, _usage = call(prompt, base_url=base_url, model=model, key=key, thinking=False, max_tokens=300)
        answer = parse_json(content)
    except Exception as exc:  # noqa: BLE001 - recorded, retried on the next run
        return {"source_id": item["source_id"], "row": item["row"], "error": str(exc)[:200]}
    return {"source_id": item["source_id"], "row": item["row"], "model": model, **answer}


def resolve_chain(item: dict, *, base_url: str, model: str, key: str) -> dict:
    prompt = CHAIN_PROMPT.format(**{k: str(v).replace('"', "'") for k, v in item.items() if k in {"entity", "quality", "sentence", "phrase"}})
    try:
        content, _usage = call(prompt, base_url=base_url, model=model, key=key, thinking=False, max_tokens=500)
        answer = parse_json(content)
    except Exception as exc:  # noqa: BLE001
        return {"source_id": item["source_id"], "row": item["row"], "error": str(exc)[:200]}
    return {"source_id": item["source_id"], "row": item["row"], "model": model, **answer}


def load(path: Path = CACHE) -> dict[tuple[str, int], dict]:
    out: dict[tuple[str, int], dict] = {}
    if path.exists():
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
            if "error" not in row:
                out[(row["source_id"], int(row["row"]))] = row
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pairs", nargs="+", type=Path, help="annotated.jsonl dispositions.tsv [...]")
    parser.add_argument("--out", type=Path, default=CACHE)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    args = parser.parse_args(argv)
    pairs = list(zip(args.pairs[0::2], args.pairs[1::2]))
    done = load(args.out)
    todo = [i for i in collect(pairs) if (i["source_id"], i["row"]) not in done]
    key = _key(args.key_file)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as sink, ThreadPoolExecutor(args.workers) as pool:
        for row in pool.map(lambda i: resolve(i, base_url=args.base_url, model=args.model, key=key), todo):
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
    print(f"{len(todo)} rows sent to {args.model}; {len(load(args.out))} cached answers")

    # Rows the pairwise answer could not take (three or more values): split them as chains.
    answers = load(args.out)
    chains_done = load(CHAIN_CACHE)
    chain_todo = [
        i for i in collect(pairs)
        if (i["source_id"], i["row"]) not in chains_done
        and "skip" in answers.get((i["source_id"], i["row"]), {})
    ]
    with CHAIN_CACHE.open("a", encoding="utf-8") as sink, ThreadPoolExecutor(args.workers) as pool:
        for row in pool.map(lambda i: resolve_chain(i, base_url=args.base_url, model=args.model, key=key), chain_todo):
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
    print(f"{len(chain_todo)} multi-value rows sent; {len(load(CHAIN_CACHE))} cached chain answers")


if __name__ == "__main__":
    main()
