"""Propose normalization rules for unmatched quality/bearer words with an LLM over lexical candidates.

Input: a dispositions TSV (Collenette or NCVC layout: ``entity_en``, ``quality_en``,
``source_en``, ``reason``).  For every distinct quality word with reason
``no_ontology_term_for_quality`` and every bearer word with ``missing_or_unsupported_bearer``,
lexical retrieval (rapidfuzz over labels and exact synonyms) proposes up to 15 candidate PATO /
FLOPO value terms (qualities) or PO / FLOPO anatomy terms (bearers).  The model must choose one
candidate (``exact``, ``synonym`` or ``broader`` reading) or ``none``; it never invents an ID, and
a chosen ID must be among the candidates.

Output: a rule table in the format of ``flopo2/ingest/ncvc_normalization.tsv`` with
``review_status = llm_proposed`` and the model's reading in ``evidence``; the annotation step loads
it after the reviewed rules.  Re-running keeps existing decisions (cache by key).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from rapidfuzz import fuzz, process

from flopo2.ingest.collenette_llm import DEFAULT_BASE_URL, DEFAULT_KEY_FILE, DEFAULT_MODEL, _key, call, parse_json
from flopo2.ingest.ncvc_annotate import normalize_key
from flopo2.saudi.vocab import parse_obo
from flopo2.verify.gates import load_pato_attribute_terms

_FLOPO_BLOCK_RE = re.compile(
    r'<(owl:Class|rdf:Description) rdf:about="http://purl.obolibrary.org/obo/(FLOPO_\d+)">(.*?)</\1>', re.S
)
_PATTERN_WORDS = re.compile(
    r"spot|strip|streak|line|vein|edge|blotch|mark|flush|mottl|band|tip|eye|centre|center|throat|"
    r"guide|dot|freckl|tinge|tinged|zone|ring|patch",
    re.IGNORECASE,
)
_RELATIONAL_LABEL = re.compile(r"\b(?:to|by|of|with|from|than)$")
# Readings rejected on review of a sample of the model's choices (2026-10-06).
DENY = {
    ("quality", "widespread"),  # distribution, not the 'spreading' habit
    ("quality", "abundant, interlaced"),
    ("bearer", "wing"),  # fruit wing or wing petal: ambiguous
}


def _ancestors(terms, start: str) -> set[str]:
    seen, stack = set(), [start]
    while stack:
        term = terms.get(stack.pop())
        for parent in term.is_a if term else []:
            if parent not in seen:
                seen.add(parent)
                stack.append(parent)
    return seen


def nearest_attribute(terms, pato_id: str, attribute_ids: set[str]) -> str:
    frontier, seen = [pato_id], set()
    while frontier:
        current = frontier.pop(0)
        if current in attribute_ids:
            return current
        seen.add(current)
        term = terms.get(current.replace("_", ":", 1))
        frontier += [p.replace(":", "_", 1) for p in (term.is_a if term else []) if p.replace(":", "_", 1) not in seen]
    return pato_id


def flopo_local_terms(path: Path = Path("ontology/flopo.owl")) -> dict[str, tuple[str, str]]:
    """FLOPO value/anatomy classes (no EQ definition) -> (label, nearest PATO or PO ancestor)."""

    direct: dict[str, tuple[str, list[str]]] = {}
    for match in _FLOPO_BLOCK_RE.finditer(path.read_text(encoding="utf-8")):
        body = match.group(3)
        if "owl:equivalentClass" in body or "owl:deprecated" in body:
            continue
        label = re.search(r"<rdfs:label[^>]*>([^<]*)", body)
        parents = re.findall(r'<rdfs:subClassOf rdf:resource="http://purl.obolibrary.org/obo/([A-Za-z]+_\d+)"', body)
        if label and parents:
            direct[match.group(2)] = (label.group(1), parents)
    out = {}
    for local, (label, parents) in direct.items():
        seen, frontier = set(), list(parents)
        while frontier:
            parent = frontier.pop(0)
            if parent in seen:
                continue
            seen.add(parent)
            if parent.startswith(("PATO_", "PO_")):
                out[local] = (label, parent)
                break
            frontier.extend(direct.get(parent, ("", []))[1])
    return out

RULE_FIELDS = [
    "rule_id", "match_field", "match_key", "bearer_constraint", "kind", "po_id", "pato_id",
    "value_term", "flopo_class", "target_label", "evidence", "review_status",
]

PROMPT = """You map a word from a botanical description to an ontology term.

Field: {field}
Word: "{word}"
Used in the source like this:
{examples}

Candidate terms (id | label | synonyms | definition):
{candidates}

Choose the ONE candidate whose meaning matches the word as used in the examples:
- "exact": same meaning (spelling or form variants count, e.g. four-angled = quadrangular);
- "synonym": a botanical synonym with the same meaning (downy = pubescent);
- "broader": the candidate is a correct but more general description (many-branched -> branched);
- "none": no candidate is correct. Prefer "none" over a wrong or merely related term.
{field_note}
Return JSON: {{"id": "<candidate id or empty>", "match": "exact|synonym|broader|none", "note": "<short reason>"}}"""

QUALITY_NOTE = (
    "A quality must describe the plant part itself (shape, colour, surface, hairiness, habit, "
    "odour, taste, position, branching). Size words like tiny or dwarf map to decreased size."
)
BEARER_NOTE = (
    "A bearer is a plant structure. A part of a structure (corolla lobe, corolla throat) maps "
    "to that part if a candidate names it, otherwise 'broader' to the whole structure only if "
    "the quality is true of the whole (usually it is not: answer none)."
)


def _lexicon_tsv(path: Path) -> dict[str, tuple[str, list[str]]]:
    out = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            synonyms = [s for s in (row.get("synonyms") or "").split("|") if s]
            out[row["id"]] = (row.get("label", ""), synonyms)
    return out


def _definitions(obo: Path) -> dict[str, str]:
    defs, current = {}, None
    for line in obo.open(encoding="utf-8"):
        if line.startswith("id: "):
            current = line[4:].strip().replace(":", "_", 1)
        elif line.startswith("def: ") and current:
            defs[current] = line[5:].split('"')[1][:160]
    return defs


class Candidates:
    def __init__(self) -> None:
        pato = _lexicon_tsv(Path("config/pato_lexicon.tsv"))
        self.defs = _definitions(Path("ont/quality.obo")) | _definitions(Path("ont/plant_ontology.obo"))
        flopo_values, flopo_anatomy = {}, {}
        self.value_attribute: dict[str, str] = {}
        for local, (label, parent) in flopo_local_terms().items():
            if parent.startswith("PATO_"):
                flopo_values[local] = (label, [])
                self.value_attribute[local] = parent
            elif parent.startswith("PO_"):
                flopo_anatomy[local] = (label, [])
        pato_terms = parse_obo(Path("ont/quality.obo"))
        self.colour_terms = {
            t.replace(":", "_") for t in pato_terms if "PATO:0000014" in _ancestors(pato_terms, t)
        } | {k for k in flopo_values if k.startswith("FLOPO_0988")}
        self.attribute_ids = load_pato_attribute_terms(Path("config/pato_lexicon.tsv"))
        # The assertion's top-level PATO term must be an attribute (attribute_slim): climb is_a.
        for local, parent in list(self.value_attribute.items()):
            self.value_attribute[local] = nearest_attribute(pato_terms, parent, self.attribute_ids)
        po = {
            term.id.replace(":", "_", 1): (term.name, term.synonyms)
            for term in parse_obo(Path("ont/plant_ontology.obo")).values()
            if term.id.startswith("PO:")
        }
        self.tables = {"quality": pato | flopo_values, "bearer": po | flopo_anatomy}
        self.choices = {}
        for field, table in self.tables.items():
            strings = []
            for ident, (label, synonyms) in table.items():
                for text in [label, *synonyms]:
                    if text:
                        strings.append((text.lower(), ident))
            self.choices[field] = strings

    def top(self, field: str, word: str, limit: int = 15) -> list[str]:
        strings = self.choices[field]
        variants = {word, re.sub(r"(ing|ed|y)$", "", word), word.replace("-", " "), word.replace("-", "")}
        scored: dict[str, float] = {}
        for variant in variants:
            for _text, score, index in process.extract(
                variant, [s for s, _ in strings], scorer=fuzz.WRatio, limit=limit * 2
            ):
                ident = strings[index][1]
                scored[ident] = max(scored.get(ident, 0), score)
        return [i for i, _ in sorted(scored.items(), key=lambda kv: -kv[1])[:limit]]

    def describe(self, field: str, ident: str) -> str:
        label, synonyms = self.tables[field][ident]
        syn = "; ".join(synonyms[:4])
        return f"{ident} | {label} | {syn} | {self.defs.get(ident, '')}"


def collect(dispositions: list[Path]) -> dict[tuple[str, str], list[str]]:
    items: dict[tuple[str, str], list[str]] = defaultdict(list)
    for path in dispositions:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row["reason"] == "no_ontology_term_for_quality":
                    key = ("quality", normalize_key(row["quality_en"]))
                elif row["reason"] == "missing_or_unsupported_bearer":
                    key = ("bearer", normalize_key(row["entity_en"]))
                else:
                    continue
                if key[1]:
                    items[key].append(f'{row["entity_en"]} / {row["quality_en"]}: "{row["source_en"]}"')
    return items


def decide(item, examples, cands: Candidates, base_url, model, key) -> dict:
    field, word = item
    ids = cands.top(field, word)
    prompt = PROMPT.format(
        field="quality of a plant part" if field == "quality" else "plant structure (bearer)",
        word=word,
        examples="\n".join(f"- {e}" for e in examples[:3]),
        candidates="\n".join(cands.describe(field, i) for i in ids),
        field_note=QUALITY_NOTE if field == "quality" else BEARER_NOTE,
    )
    try:
        content, _usage = call(prompt, base_url=base_url, model=model, key=key, thinking=False, max_tokens=300)
        answer = parse_json(content)
    except Exception as exc:  # noqa: BLE001
        return {"field": field, "word": word, "id": "", "match": "error", "note": str(exc)[:200]}
    chosen = str(answer.get("id") or "").replace(":", "_")
    match = str(answer.get("match") or "none")
    note = str(answer.get("note", ""))[:200]
    rejected = guardrail(field, word, chosen, match, cands) if chosen in ids else "not a candidate"
    if match not in {"exact", "synonym", "broader"}:
        chosen, match = "", "none"
    elif rejected:
        chosen, match, note = "", "rejected", f"{rejected}; model said {answer.get('id')} {answer.get('match')}"
    elif not verify(field, word, examples, chosen, cands, base_url, model, key):
        chosen, match, note = "", "rejected", f"verifier disagreed; model said {answer.get('id')} {answer.get('match')}"
    return {"field": field, "word": word, "id": chosen, "match": match, "note": note}


def guardrail(field: str, word: str, chosen: str, match: str, cands: "Candidates") -> str:
    """Deterministic rejections of readings the review showed to be unsafe."""

    if (field, word) in DENY:
        return "rejected on review"
    if re.match(r"(?:semi|sub)[- ]?", word) and not re.match(r"(?:semi|sub)[- ]?", cands.tables[field][chosen][0]):
        return "a semi-/sub- word is not the unprefixed quality"
    if field == "bearer":
        return "" if match in {"exact", "synonym"} else "a broader bearer moves the quality to another structure"
    label = cands.tables["quality"][chosen][0]
    if re.search(r"\d", word):
        return "counts and numbers are not qualities"
    if chosen in cands.attribute_ids:
        return "an attribute is not a value"
    if chosen.startswith("FLOPO_") and cands.value_attribute.get(chosen) not in cands.attribute_ids:
        return "FLOPO value class without a PATO attribute"
    if _RELATIONAL_LABEL.search(label) or chosen in {"PATO_0001555", "PATO_0001772", "PATO_0005016"}:
        return "relational quality needs a second entity"
    if chosen in cands.colour_terms and _PATTERN_WORDS.search(word):
        return "a coloured pattern is not the colour of the whole bearer"
    return ""


VERIFY_PROMPT = """A botanical description says: {examples}
Question: in this usage, does the word "{word}" mean that the {field} is "{label}"{definition}?
Answer "yes" only if the term is correct (an exact synonym or a correct more general description).
Answer "no" if it is wrong, only related, refers to a different part, or describes a pattern.
Return JSON: {{"answer": "yes" or "no"}}"""


def verify(field, word, examples, chosen, cands, base_url, model, key) -> bool:
    label = cands.tables[field][chosen][0]
    definition = cands.defs.get(chosen, "")
    prompt = VERIFY_PROMPT.format(
        examples="; ".join(examples[:3]),
        word=word,
        field="plant part has the quality" if field == "quality" else "plant part is the structure",
        label=label,
        definition=f" (definition: {definition})" if definition else "",
    )
    try:
        content, _usage = call(prompt, base_url=base_url, model=model, key=key, thinking=False, max_tokens=50)
        return str(parse_json(content).get("answer", "")).lower().startswith("y")
    except Exception:  # noqa: BLE001
        return False


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dispositions", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, default=Path("flopo2/ingest/llm_term_rules.tsv"))
    parser.add_argument("--cache", type=Path, default=Path("local-corpora/saudi-flora/llm-term-decisions.jsonl"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--key-file", default=DEFAULT_KEY_FILE)
    args = parser.parse_args(argv)

    items = collect(args.dispositions)
    decisions: dict[tuple[str, str], dict] = {}
    if args.cache.exists():
        for line in args.cache.open(encoding="utf-8"):
            row = json.loads(line)
            if row["match"] != "error":
                decisions[(row["field"], row["word"])] = row
    todo = [item for item in items if item not in decisions]
    cands = Candidates()
    key = _key(args.key_file)
    args.cache.parent.mkdir(parents=True, exist_ok=True)
    with args.cache.open("a", encoding="utf-8") as cache, ThreadPoolExecutor(args.workers) as pool:
        for row in pool.map(lambda it: decide(it, items[it], cands, args.base_url, args.model, key), todo):
            decisions[(row["field"], row["word"])] = row
            cache.write(json.dumps(row, ensure_ascii=False) + "\n")
            cache.flush()

    rules = []
    counts: Counter[str] = Counter()
    for (field, word), row in sorted(decisions.items()):
        counts[f"{field}:{row['match']}"] += 1
        if not row["id"] or guardrail(field, word, row["id"], row["match"], cands):
            continue
        label = cands.tables[field][row["id"]][0]
        rule = dict.fromkeys(RULE_FIELDS, "")
        rule.update(
            rule_id=f"L{len(rules) + 1:04d}",
            match_field="quality" if field == "quality" else "bearer",
            match_key=word,
            kind="pato" if field == "quality" and row["id"].startswith("PATO_") else (
                "flopo_value" if field == "quality" else "bearer"
            ),
            target_label=label,
            evidence=f"{args.model} choice among lexical candidates: {row['match']} ({row['note']})",
            review_status="llm_proposed",
        )
        if field == "bearer":
            rule["po_id"] = row["id"]
        elif row["id"].startswith("PATO_"):
            rule["pato_id"] = row["id"]
        else:
            rule["value_term"] = row["id"]
            rule["pato_id"] = cands.value_attribute.get(row["id"], "PATO_0000014")
        rules.append(rule)
    with args.out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, RULE_FIELDS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rules)
    print(json.dumps({"items": len(items), "rules": len(rules), **counts}, indent=1))


if __name__ == "__main__":
    main()
