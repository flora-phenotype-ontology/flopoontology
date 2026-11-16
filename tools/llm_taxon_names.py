"""Ask an LLM (agy-auto: Gemini Flash or Argon) to repair taxon names that WCVP/IPNI did not match.

Input: local-corpora/wcvp/match/ipni-matches.tsv (tools/match_taxa_ipni.py).  Names that WCVP could
not match, or matched to several names, are sent in batches with their WFO family.  For a clash the
WCVP candidates are listed and the model picks one.  An answer is used only when the repaired name
then matches WCVP (``flopo2.taxon.wcvp``) on its own, or the pick is one of the listed candidates.

    python -m tools.llm_taxon_names run [--model gemini-3.8-flash-medium] [--jobs 6] [--only-unresolved]
    python -m tools.llm_taxon_names apply      # writes ipni-llm-fixes.tsv

Answers are cached in local-corpora/wcvp/match/llm-answers.jsonl (one line per name and model).
Mosses and other bryophytes are skipped: WCVP and IPNI list vascular plants only.
"""

from __future__ import annotations

import argparse
import concurrent.futures as futures
import csv
import json
import re
import subprocess
import tempfile
from pathlib import Path

from flopo2.taxon.wcvp import Wcvp

MATCHES = Path("local-corpora/wcvp/match/ipni-matches.tsv")
ANSWERS = Path("local-corpora/wcvp/match/llm-answers.jsonl")
FIXES = Path("local-corpora/wcvp/match/ipni-llm-fixes.tsv")
BRYOPHYTE_ORDERS = {
    "Hypnales", "Pottiales", "Dicranales", "Orthotrichales", "Bryales", "Grimmiales", "Sphagnales",
    "Archidiales", "Polytrichales", "Rhabdoweisiales", "Bartramiales", "Funariales", "Hookeriales",
    "Hedwigiales", "Splachnales", "Bryoxiphiales", "Buxbaumiales", "Diphysciales", "Encalyptales",
    "Gigaspermales", "Rhizogoniales", "Scouleriales", "Timmiales", "Tetraphidales", "Andreaeales",
    "Andreaeobryales", "Takakiales", "Oedipodiales", "Ptychomniales", "Aulacomniales", "Orthodontiales",
    "Hypnodendrales", "Catoscopiales", "Mitteniales", "Bryobartramiales", "Distichiales", "Ditrichales",
    "Jungermanniales", "Porellales", "Marchantiales", "Metzgeriales", "Pelliales", "Fossombroniales",
    "Pallaviciniales", "Ptilidiales", "Sphaerocarpales", "Haplomitriales", "Treubiales", "Blasiales",
    "Lunulariales", "Neohodgsoniales", "Pleuroziales", "Anthocerotales", "Dendrocerotales",
    "Notothyladales", "Phymatocerotales", "Leiosporocerotales",
}

PROMPT = """You are checking plant names printed in floras against Kew's World Checklist of Vascular
Plants (WCVP) and IPNI. Do not use any tools, do not read or write files; answer from knowledge only.

For each item give the name as it should be looked up in WCVP: correct OCR and typing errors
("Aadropogon" -> "Andropogon"), drop HTML, question marks, quotes and words that are not part of
the name ("sp. nov.", "aff.", "cf.", description fragments), keep the rank word ("subsp.", "var.",
"f.") and give the authors if the printed name has them or you are sure of them. Do not replace a
synonym with the accepted name: give the printed name, repaired.
If an item lists "candidates", the name exists several times in WCVP; pick the candidate id the
flora most likely means (use the family and the printed authors), or "" if you cannot tell.

verdict is one of: corrected, unchanged, picked, family (only a family name), not_a_name (not a
plant name), bryophyte (a moss, liverwort or hornwort), unknown.

Return only a JSON array, one object per item, in the same order:
[{{"i": <item number>, "verdict": "...", "name": "<repaired name or empty>", "pick": "<candidate id or empty>"}}]

Items:
{items}
"""


def load_rows() -> list[dict]:
    with MATCHES.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def todo(rows: list[dict], wcvp: Wcvp) -> list[dict]:
    items = []
    for row in rows:
        if row["how"] not in ("none", "ambiguous") or row["wfo_order"] in BRYOPHYTE_ORDERS:
            continue
        item = {"name": row["name"], "family": row["wfo_family"]}
        if row["how"] == "ambiguous":
            ids = wcvp.by_key.get(row["key"], [])
            item["candidates"] = [
                {"id": pid, "name": wcvp.by_id[pid]["taxon_name"], "authors": wcvp.by_id[pid]["taxon_authors"],
                 "family": wcvp.by_id[pid]["family"], "status": wcvp.by_id[pid]["taxon_status"]}
                for pid in ids[:8]
            ]
        items.append(item)
    return items


def cached() -> dict[tuple[str, str], dict]:
    seen = {}
    if ANSWERS.exists():
        for line in ANSWERS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                answer = json.loads(line)
                seen[(answer["model"], answer["name"])] = answer
    return seen


def ask(batch: list[dict], model: str, timeout: int = 600) -> list[dict]:
    lines = []
    for n, item in enumerate(batch, 1):
        lines.append(json.dumps({"i": n, **item}, ensure_ascii=False))
    prompt = PROMPT.format(items="\n".join(lines))
    with tempfile.TemporaryDirectory(dir=Path.home() / "tmp", prefix="agy-names-") as empty:
        done = subprocess.run(
            ["agy-auto", "-p", prompt, "--model", model, "--print-timeout", f"{timeout}s"],
            cwd=empty, capture_output=True, text=True, timeout=timeout + 60,
        )
    text = done.stdout
    match = re.search(r"\[\s*\{.*\}\s*\]", text, re.S)
    if not match:
        raise RuntimeError(f"no JSON array in answer (exit {done.returncode}): {text[-300:]} {done.stderr[-300:]}")
    answers = json.loads(match.group(0))
    out = []
    for answer in answers:
        n = int(answer.get("i", 0))
        if 1 <= n <= len(batch):
            out.append({"model": model, "name": batch[n - 1]["name"], "verdict": answer.get("verdict", ""),
                        "fix": answer.get("name", "") or "", "pick": str(answer.get("pick", "") or "")})
    return out


def run(model: str, jobs: int, size: int, only_unresolved: bool) -> None:
    wcvp = Wcvp()
    rows = load_rows()
    items = todo(rows, wcvp)
    seen = cached()
    if only_unresolved:  # a second model only for what the first could not repair
        # settled: verified, or judged no vascular plant name (family only, not a name, bryophyte)
        settled = {r["name"] for r in verify(rows, wcvp, seen)
                   if r["result_how"] not in ("none", "ambiguous", "") or r["verdict"] in ("family", "not_a_name", "bryophyte")}
        items = [i for i in items if i["name"] not in settled]
    items = [i for i in items if (model, i["name"]) not in seen]
    batches = [items[k : k + size] for k in range(0, len(items), size)]
    print(f"{len(items)} names in {len(batches)} batches with {model}", flush=True)
    ANSWERS.parent.mkdir(parents=True, exist_ok=True)
    failed = 0
    with futures.ThreadPoolExecutor(jobs) as pool, ANSWERS.open("a", encoding="utf-8") as sink:
        pending = {pool.submit(ask, b, model): b for b in batches}
        for k, done in enumerate(futures.as_completed(pending), 1):
            try:
                for answer in done.result():
                    sink.write(json.dumps(answer, ensure_ascii=False) + "\n")
                sink.flush()
            except Exception as error:  # noqa: BLE001 - a failed batch is retried by the next run
                failed += 1
                print(f"batch failed: {error}", flush=True)
            if k % 10 == 0:
                print(f"{k}/{len(batches)} batches", flush=True)
    print(f"done; {failed} batches failed (run again to retry them)")


def verify(rows: list[dict], wcvp: Wcvp, seen: dict) -> list[dict]:
    """One row per answered name: the best verified answer (Argon over Flash when both verify)."""

    by_name: dict[str, list[dict]] = {}
    for (model, name), answer in seen.items():
        by_name.setdefault(name, []).append(answer)
    meta = {r["name"]: r for r in rows}
    out = []
    for name, answers in by_name.items():
        row = meta.get(name, {})
        best = None
        for answer in sorted(answers, key=lambda a: "argon" not in a["model"]):
            result = None
            if answer["verdict"] == "picked" and answer["pick"] in wcvp.by_id and answer["pick"] in wcvp.by_key.get(row.get("key", ""), []):
                result = wcvp.from_id(name, answer["pick"], "llm-pick")
            elif answer["fix"] and answer["verdict"] in ("corrected", "unchanged"):
                found = wcvp.match(answer["fix"], family=row.get("wfo_family", ""))
                if found.how not in ("none", "ambiguous"):
                    found.name, found.how = name, "llm-" + found.how
                    result = found
            if result is not None:
                best = {**answer, **{f"result_{k}": v for k, v in result.__dict__.items()}}
                break
        if best is None:
            first = answers[0]
            best = {**first, "result_how": "", "result_name": name}
        out.append(best)
    return out


def apply() -> None:
    wcvp = Wcvp()
    rows = verify(load_rows(), wcvp, cached())
    fields = sorted({k for r in rows for k in r})
    with FIXES.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    ok = sum(1 for r in rows if r["result_how"])
    verdicts: dict[str, int] = {}
    for r in rows:
        if not r["result_how"]:
            verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
    print(f"{ok} of {len(rows)} answered names verified in WCVP; not verified by verdict: {verdicts}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["run", "apply"])
    parser.add_argument("--model", default="gemini-3.8-flash-medium")
    parser.add_argument("--jobs", type=int, default=6)
    parser.add_argument("--size", type=int, default=40)
    parser.add_argument("--only-unresolved", action="store_true")
    args = parser.parse_args()
    if args.command == "run":
        run(args.model, args.jobs, args.size, args.only_unresolved)
    else:
        apply()


if __name__ == "__main__":
    main()
