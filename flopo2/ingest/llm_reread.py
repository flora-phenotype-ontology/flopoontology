"""Re-read unmatched trait rows with an LLM and correct the transcription.

The transcriptions sometimes put more than a quality into ``quality_en`` ("medium tree growth
form", "pitcher-shaped (urceolate)", "longitudinally fissured"), a plant part ("head", "corona"),
a count ("four petals"), alternatives ("petiolate or sessile"), or a statement that is not an
entity-quality trait at all ("flowers before the leaves appear").  Such rows end as
``no_ontology_term_for_quality`` or ``missing_or_unsupported_bearer`` although the ontology may
have the term.

Each such row is sent to the model with its sentence.  The model returns corrected rows, each a
plant part, one glossary-style quality word, a kind and a verbatim evidence span.  Nothing is
accepted on the model's word: ``ncvc_annotate.apply_rereads`` keeps a corrected row only when its
evidence is verbatim in the description, and the row then goes through the normal rules,
lexicons, anchoring and FLOPO gates.  Rows of the other kinds keep the original row and get a
precise reason (count, relation to another part, process, not a plant trait).

Output: ``local-corpora/saudi-flora/llm-rereads.jsonl`` keyed by (source_id, row); cached.
"""

from __future__ import annotations

import argparse
import csv
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flopo2.ingest.collenette_llm import DEFAULT_BASE_URL, DEFAULT_KEY_FILE, DEFAULT_MODEL, _key, call, parse_json
from flopo2.ingest.llm_relations import _sentence

CACHE = Path("local-corpora/saudi-flora/llm-rereads.jsonl")
PROMPT_ID = "reread_v1"
REASONS = {"no_ontology_term_for_quality", "missing_or_unsupported_bearer"}
KINDS = {"quality", "structure", "alternatives", "count", "relation", "process", "not_a_trait"}
# Kinds that keep the original row, with the reason they are not annotated.
KIND_REASONS = {
    "count": "count_or_non_length_measurement",
    "relation": "relation_to_another_part",
    "process": "process_or_event",
    "not_a_trait": "not_a_plant_trait",
}

PROMPT = """A trait row was extracted from a botanical description, but its plant part or quality
could not be matched to an ontology term. Often the row is malformed. Re-read the sentence and
return the correct row or rows for the phrase.

Taxon: {taxon}
Sentence: "{sentence}"
Extracted row: plant part "{entity}", quality "{quality}", evidence "{phrase}"

Each returned row has:
- "part": the plant part the quality is true of, a singular noun (whole plant, leaf, leaflet,
  bark, branch, stem, flower, corolla, calyx, sepal, petal, fruit, seed, inflorescence, spine ...).
  "A tree", "an herb", "a shrub" describe the whole plant.
- "quality": ONE quality as a botanist would write it in a glossary, usually one adjective:
  fissured, beaked, fibrous, urceolate, scale-like, umbrella-shaped, palm-like, solitary.
  * The quality is never a plant part. "leaves petiolate" is part leaf, quality petiolate.
  * Move degree, direction and frequency words out of the quality into "modifier":
    "longitudinally fissured" is quality fissured, modifier longitudinally.
  * When the text glosses a word ("pitcher-shaped (urceolate)"), use the standard term (urceolate).
  * Keep comparisons as written ("palm-like", "broom-like", "comb-like").
  * A habit is a quality of the whole plant: "a medium tree" is whole plant / tree, plus
    whole plant / medium-sized.
- "kind", one of:
  quality      the part has the quality;
  structure    the phrase names a kind of structure that is present (a head, a pod, a corona):
               part is that structure, quality "present";
  alternatives two or more values of the same quality ("petiolate or sessile", "annual or
               biennial"): first value in quality, the others in "alternatives";
  count        a number of parts ("four petals", "3-5 seeds", "five-parted");
  relation     the part is described relative to another part or a position ("extending to
               the fruit", "attached in the leaf axil");
  process      behaviour or an event ("flowers before the leaves appear", "exudes milky latex
               when broken", "grows until fruiting");
  not_a_trait  grazing, use, ecology, or text that is not about the plant.
- "evidence": the words of the sentence that state this row, copied EXACTLY (a verbatim
  substring of the sentence, including the quality word).
Return only rows for the extracted phrase, not for the rest of the sentence.
Return JSON: {{"rows": [{{"part": "", "quality": "", "kind": "", "alternatives": [], "modifier": "", "evidence": ""}}]}}"""


def collect(corpora: list[tuple[Path, Path]]) -> list[dict]:
    """Unmatched original rows from (annotated JSONL, dispositions TSV) pairs."""

    items = []
    for corpus, dispositions in corpora:
        texts, taxa = {}, {}
        for line in corpus.open(encoding="utf-8"):
            record = json.loads(line)
            if record.get("language") == "en" and record.get("organ") == "description":
                texts[record["source_id"]] = record["text"]
                taxa[record["source_id"]] = record.get("taxon", "")
        with dispositions.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row["reason"] not in REASONS or row.get("reread_from"):
                    continue
                text = texts.get(row["source_id"], "")
                items.append(
                    {
                        "source_id": row["source_id"],
                        "row": int(row["row"]),
                        "taxon": row.get("taxon") or taxa.get(row["source_id"], ""),
                        "entity": row["entity_en"],
                        "quality": row["quality_en"],
                        "phrase": row["source_en"],
                        "sentence": _sentence(text, row["source_en"]),
                    }
                )
    return items


def _clean(answer: dict) -> list[dict]:
    rows = []
    for row in answer.get("rows") or []:
        if not isinstance(row, dict):
            continue
        kind = str(row.get("kind") or "").strip()
        if kind not in KINDS:
            continue
        rows.append(
            {
                "part": str(row.get("part") or "").strip(),
                "quality": str(row.get("quality") or "").strip(),
                "kind": kind,
                "alternatives": [str(a).strip() for a in row.get("alternatives") or [] if str(a).strip()],
                "modifier": str(row.get("modifier") or "").strip(),
                "evidence": str(row.get("evidence") or "").strip(),
            }
        )
    return rows


def reread(item: dict, *, base_url: str, model: str, key: str) -> dict:
    prompt = PROMPT.format(**{k: str(v).replace('"', "'") for k, v in item.items()})
    head = {"source_id": item["source_id"], "row": item["row"], "entity": item["entity"],
            "quality": item["quality"], "phrase": item["phrase"]}
    try:
        content, _usage = call(prompt, base_url=base_url, model=model, key=key, thinking=False, max_tokens=600)
        answer = parse_json(content)
    except Exception as exc:  # noqa: BLE001 - recorded, retried on the next run
        return {**head, "error": str(exc)[:200]}
    return {**head, "model": model, "prompt_id": PROMPT_ID, "rows": _clean(answer)}


def load(path: Path = CACHE) -> dict[tuple[str, int], dict]:
    """Cached answers by (source_id, row); an answer for a row whose transcription changed is dropped."""

    out: dict[tuple[str, int], dict] = {}
    if path.exists():
        for line in path.open(encoding="utf-8"):
            row = json.loads(line)
            if "error" not in row:
                out[(row["source_id"], int(row["row"]))] = row
    return out


def matches(answer: dict, phenotype: dict) -> bool:
    return (answer.get("entity"), answer.get("quality"), answer.get("phrase")) == (
        phenotype.get("entity_en", ""), phenotype.get("quality_en", ""), phenotype.get("source_en", ""),
    )


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
    todo = [
        i for i in collect(pairs)
        if (i["source_id"], i["row"]) not in done
        or not matches(done[(i["source_id"], i["row"])], {"entity_en": i["entity"], "quality_en": i["quality"], "source_en": i["phrase"]})
    ]
    key = _key(args.key_file)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("a", encoding="utf-8") as sink, ThreadPoolExecutor(args.workers) as pool:
        for row in pool.map(lambda i: reread(i, base_url=args.base_url, model=args.model, key=key), todo):
            sink.write(json.dumps(row, ensure_ascii=False) + "\n")
            sink.flush()
    print(f"{len(todo)} rows sent to {args.model}; {len(load(args.out))} cached answers")


if __name__ == "__main__":
    main()
