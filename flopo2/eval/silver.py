"""Assemble + validate the Claude-generated SILVER standard (Phase 4 bootstrap).

The fan-out workflow (`flopo-silver-standard`) had 25 Sonnet agents ground 400 flora segments to
PO/PATO entity-quality assertions, each writing ``gold/silver_batches/out_batch_NN.jsonl``. This
module concatenates them in order and applies deterministic validation gates — the same gates the
real extraction pipeline uses — so the silver standard is trustworthy *as a yardstick* despite
being model-generated (not expert gold):

  * **ID validity** — ``po_id`` must exist in the PO lexicon and ``pato_id`` in the PATO lexicon
    (drops invented/hallucinated ids).
  * **Provenance / anti-hallucination** — ``source_text`` must be a verbatim substring of the
    segment text (whitespace-normalized). Non-verbatim spans are flagged.

Outputs ``gold/silver_standard.jsonl`` (kept assertions only) and a stats dict. Anything dropped is
counted and reported so the silver standard's limitations are explicit.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

_WS = re.compile(r"\s+")


def _load_ids(lexicon: Path) -> set[str]:
    with Path(lexicon).open(newline="") as fh:
        return {row["id"] for row in csv.DictReader(fh, delimiter="\t")}


def _norm(s: str) -> str:
    return _WS.sub(" ", s or "").strip().lower()


def assemble(
    batch_dir: Path,
    po_lex: Path,
    pato_lex: Path,
    out_path: Path,
    n_batches: int = 25,
) -> dict:
    po_ids = _load_ids(po_lex)
    pato_ids = _load_ids(pato_lex)

    stats = {
        "segments": 0,
        "assertions_in": 0,
        "assertions_kept": 0,
        "bad_po_id": 0,
        "bad_pato_id": 0,
        "missing_source": 0,
        "source_not_verbatim": 0,
        "bad_json_lines": 0,
        "po_used": set(),
        "pato_used": set(),
        "negated": 0,
        "with_value": 0,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as out:
        for i in range(n_batches):
            bf = batch_dir / f"out_batch_{i:02d}.jsonl"
            if not bf.exists():
                continue
            for line in bf.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    seg = json.loads(line)
                except json.JSONDecodeError:
                    stats["bad_json_lines"] += 1
                    continue
                stats["segments"] += 1
                seg_norm = _norm(seg.get("text", ""))
                kept = []
                for a in seg.get("assertions", []):
                    stats["assertions_in"] += 1
                    po = a.get("po_id", "")
                    pato = a.get("pato_id", "")
                    src = a.get("source_text", "")
                    if po not in po_ids:
                        stats["bad_po_id"] += 1
                        continue
                    if pato not in pato_ids:
                        stats["bad_pato_id"] += 1
                        continue
                    if not src:
                        stats["missing_source"] += 1
                        continue
                    verbatim = _norm(src) in seg_norm
                    if not verbatim:
                        stats["source_not_verbatim"] += 1
                        a = {**a, "source_verbatim": False}
                    else:
                        a = {**a, "source_verbatim": True}
                    stats["assertions_kept"] += 1
                    stats["po_used"].add(po)
                    stats["pato_used"].add(pato)
                    if a.get("negated"):
                        stats["negated"] += 1
                    if a.get("value_low") is not None or a.get("value_high") is not None or a.get("unit"):
                        stats["with_value"] += 1
                    kept.append(a)
                seg["assertions"] = kept
                out.write(json.dumps(seg, ensure_ascii=False) + "\n")

    stats["distinct_po"] = len(stats.pop("po_used"))
    stats["distinct_pato"] = len(stats.pop("pato_used"))
    return stats


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Assemble + validate the silver standard.")
    ap.add_argument("--batch-dir", type=Path, default=Path("gold/silver_batches"))
    ap.add_argument("--po-lex", type=Path, default=Path("config/po_lexicon.tsv"))
    ap.add_argument("--pato-lex", type=Path, default=Path("config/pato_lexicon.tsv"))
    ap.add_argument("-o", "--out", type=Path, default=Path("gold/silver_standard.jsonl"))
    args = ap.parse_args()
    s = assemble(args.batch_dir, args.po_lex, args.pato_lex, args.out)
    print(json.dumps(s, indent=2))


if __name__ == "__main__":
    main()
