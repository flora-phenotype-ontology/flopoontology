"""Resolve Saudi-flora taxon names to accepted World Flora Online taxa (via Global Names Verifier).

Each source spells names as printed (Collenette 1985: "Acacia tortilis"; NCVC 2024: "Vachellia
tortilis").  To merge sources per taxon, every printed name is verified against the WFO Plant List
(GNV data source 196) and keyed by the *accepted* WFO record.  The FLOPO taxon IRI is
``http://phenomebrowser.net/flopo/taxon/<accepted wfo id>`` (version suffix dropped); a name that
WFO does not know gets ``taxon/name/<slug>`` and keeps its printed spelling.

Results are cached in a JSON file so a rebuild makes no network calls.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path

GNV = "https://verifier.globalnames.org/api/v1/verifications"
WFO_SOURCE = 196
TAXON_NS = "http://phenomebrowser.net/flopo/taxon/"
_RANKS = {"family", "genus", "species", "subspecies", "variety", "form"}
_VERSION_RE = re.compile(r"-\d{4}-\d{2}$")


@dataclass
class ResolvedName:
    name: str
    match_type: str = "NoMatch"
    status: str = ""
    matched: str = ""
    accepted_name: str = ""
    accepted_authorship: str = ""
    wfo_id: str = ""
    accepted_wfo_id: str = ""
    family: str = ""
    order: str = ""

    @property
    def taxon_iri(self) -> str:
        if self.accepted_wfo_id:
            return TAXON_NS + self.accepted_wfo_id
        slug = re.sub(r"[^A-Za-z0-9]+", "_", self.name).strip("_")
        return TAXON_NS + "name/" + slug

    @property
    def label(self) -> str:
        return self.accepted_name or self.name


def clean_name(name: str) -> str:
    """Drop OCR noise and field-guide qualifiers that GNV cannot verify ("sp. nov. aff.")."""

    name = re.sub(r"\s+", " ", name).strip()
    name = re.sub(r"\b(?:sp\.\s*nov\.|aff\.|cf\.)\s*", "", name)
    name = re.sub(r"\bssp\.", "subsp.", name)
    return name.strip()


def _parse(result: dict, name: str) -> ResolvedName:
    best = result.get("bestResult") or {}
    resolved = ResolvedName(name=name, match_type=result.get("matchType", "NoMatch"))
    if not best:
        return resolved
    ranks = (best.get("classificationRanks") or "").split("|")
    path = (best.get("classificationPath") or "").split("|")
    lineage = dict(zip(ranks, path))
    current = best.get("currentName") or ""
    accepted = best.get("currentCanonicalSimple") or best.get("matchedCanonicalSimple") or ""
    resolved.status = best.get("taxonomicStatus", "")
    resolved.matched = best.get("matchedCanonicalSimple", "")
    resolved.accepted_name = accepted
    resolved.accepted_authorship = current[len(accepted) :].strip() if current.startswith(accepted) else ""
    resolved.wfo_id = _VERSION_RE.sub("", best.get("recordId", ""))
    resolved.accepted_wfo_id = _VERSION_RE.sub("", best.get("currentRecordId", ""))
    resolved.family = lineage.get("family", "")
    resolved.order = lineage.get("order", "")
    # A match only at genus level ("Barleria sp.") is not a species identity.
    if resolved.match_type in {"PartialExact", "PartialFuzzy"} and len(accepted.split()) < len(
        clean_name(name).split()[:2]
    ):
        resolved.accepted_wfo_id = ""
    return resolved


def resolve(names: list[str], cache_path: Path, batch: int = 200) -> dict[str, ResolvedName]:
    cache: dict[str, dict] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    todo = sorted({n for n in names if n and n not in cache})
    for start in range(0, len(todo), batch):
        chunk = todo[start : start + batch]
        payload = json.dumps(
            {
                "nameStrings": [clean_name(n) for n in chunk],
                "dataSources": [WFO_SOURCE],
                "withCapitalization": True,
            }
        ).encode("utf-8")
        request = urllib.request.Request(GNV, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            results = json.loads(response.read().decode("utf-8")).get("names", [])
        for name, result in zip(chunk, results):
            cache[name] = asdict(_parse(result, name))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return {n: ResolvedName(**cache[n]) for n in names if n in cache}


NAME_FIX_PROMPT = """This taxon name was read by OCR from S. Collenette, "An illustrated guide to the
flowers of Saudi Arabia" (1985), family {family}. The World Flora Online name check found {problem}.
Name as read: "{name}"
Start of the entry text: "{text}"

If it is a plant name with OCR errors (e.g. "Combretum mole" -> "Combretum molle", "Forskoalea" ->
"Forsskaolea", "hirsttta" -> "hirsuta"), give the corrected scientific name as printed in 1985
(genus + epithet, add "subsp."/"var." parts if present). If the text is not a taxon name (a
description fragment such as "An erect bushy herb"), answer "not a name".
Return JSON: {{"name": "<corrected name or empty>", "verdict": "corrected|unchanged|not a name"}}"""


def propose_name_fixes(problems: list[dict], cache_path: Path) -> dict[str, dict]:
    """Ask the LLM for OCR corrections of unresolved names; keep a fix only if WFO verifies it."""

    from flopo2.ingest.collenette_llm import DEFAULT_BASE_URL, DEFAULT_KEY_FILE, DEFAULT_MODEL, _key, call, parse_json

    fixes: dict[str, dict] = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    key = _key(DEFAULT_KEY_FILE)
    for item in problems:
        if item["name"] in fixes:
            continue
        prompt = NAME_FIX_PROMPT.format(**item)
        try:
            content, _ = call(prompt, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL, key=key, thinking=False, max_tokens=100)
            answer = parse_json(content)
        except Exception as exc:  # noqa: BLE001
            fixes[item["name"]] = {"verdict": "error", "note": str(exc)[:100]}
            continue
        fixes[item["name"]] = {"verdict": answer.get("verdict", ""), "proposed": answer.get("name", "")}
    proposed = sorted({f["proposed"] for f in fixes.values() if f.get("verdict") == "corrected" and f.get("proposed")})
    verified = resolve(proposed, cache_path.with_name("taxon-cache.json"))
    for name, fix in fixes.items():
        target = verified.get(fix.get("proposed", ""))
        fix["verified"] = bool(target and target.accepted_wfo_id and target.match_type == "Exact")
    cache_path.write_text(json.dumps(fixes, indent=1, ensure_ascii=False, sort_keys=True))
    return fixes


def main() -> None:
    """Propose OCR fixes for Collenette names that WFO does not match exactly (cached)."""

    out = Path("local-corpora/saudi-flora")
    segments = [json.loads(line) for line in Path("local-corpora/saudi-collenette/collenette-saudi-segments.jsonl").open(encoding="utf-8")]
    names = resolve(sorted({s["taxon"] for s in segments}), out / "taxon-cache.json")
    problems, seen = [], set()
    for segment in segments:
        name = segment["taxon"]
        found = names.get(name)
        if name in seen or (found and found.accepted_wfo_id and found.match_type == "Exact"):
            continue
        seen.add(name)
        problem = (found.match_type if found else "NoMatch") + (
            f" (fuzzy match: {found.matched})" if found and found.accepted_wfo_id else " (no species match)"
        )
        problems.append({"name": name, "family": segment.get("taxon_family", ""), "problem": problem,
                         "text": segment["text"][:160].replace('"', "'")})
    fixes = propose_name_fixes(problems, out / "name-fixes.json")
    print(f"{len(problems)} names checked, {sum(f.get('verified', False) for f in fixes.values())} WFO-verified fixes")


if __name__ == "__main__":
    main()
