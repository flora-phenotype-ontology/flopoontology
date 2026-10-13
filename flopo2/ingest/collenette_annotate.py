"""Anchor, ground and gate the LLM transcription of Collenette's Saudi field guide.

Input is ``raw/collenette-qwen.jsonl`` from :mod:`flopo2.ingest.collenette_llm` (one record per
OCR segment, NCVC-style ``phenotypes`` rows).  Every record is turned into the NCVC record shape
(``description_en`` = the OCR segment) and passed through
:func:`flopo2.ingest.ncvc_annotate.annotate_record`, so anchoring, grounding, the reviewed
normalization rules and the FLOPO gates are exactly those used for the NCVC guide.  NCVC's
page-keyed data-quality holds do not apply here.

Colour words are grounded to the ISCC-NBS colour backbone through
``config/botanical_colour_synonyms.tsv`` (curator-approved word list):

* an EXACT or NARROW synonym becomes that backbone class;
* a RELATED synonym ("-ish" words) becomes its class with ``value_qualifier: approximately``;
* a two-colour compound or modified colour ("orange-red", "pale yellow", "creamy-white") becomes
  the class of its head colour, the reading the colour backbone migration uses for compounds
  that ISCC-NBS does not name (head-final, NARROW).

Output (``derived/``): ``collenette-saudi-annotated.jsonl`` (stage-22 wire format, colour values
already on the backbone) and ``collenette-saudi-dispositions.tsv``.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

from flopo2.ingest.ncvc_annotate import (
    annotate_record,
    colour_backbone_migrator,
    enable_atlas_options,
    load_resources,
    merge_rules,
)

SOURCE = "collenette-saudi"
EXTRACTOR = "qwen3.8-27b_collenette_transcription"
# The FLOPO flora value terms and the Collenette rules override the NCVC rules for the same word;
# the LLM-proposed rules only fill gaps (see ncvc_annotate.merge_rules).
RULE_TABLES = [
    Path("flopo2/ingest/flora_value_term_rules.tsv"),
    Path("flopo2/ingest/collenette_normalization.tsv"),
    Path("flopo2/ingest/llm_term_rules.tsv"),
]
_PAGE_RE = re.compile(r":page-(\d+)")


def to_ncvc_record(raw: dict) -> dict:
    match = _PAGE_RE.search(raw["source_id"])
    return {
        "source": SOURCE,
        "source_id": raw["source_id"],
        "pdf_page": int(match.group(1)) if match else 0,
        "scientific_name": raw.get("taxon", ""),
        "family": raw.get("family", ""),
        "description_en": raw.get("segment_text", ""),
        "phenotypes": [dict(p) for p in raw.get("phenotypes") or []],
    }


def prepare(rec: dict) -> None:
    """Use the free entity/quality words as labels; colours are read by the shared colour hook."""

    for phenotype in rec["phenotypes"]:
        phenotype["po_label"] = phenotype.get("entity_en", "")
        phenotype["pato_label"] = str(phenotype.get("quality_en") or "")


def run(raw_path: Path, out_dir: Path) -> dict:
    res = load_resources()
    res.holds = []
    base_rules = merge_rules(res.rules, [p for p in RULE_TABLES[2:] if p.exists()], RULE_TABLES[:2])
    enable_atlas_options(res)
    colour_migrator = colour_backbone_migrator()
    latest: dict[str, dict] = {}
    for line in raw_path.open(encoding="utf-8"):
        row = json.loads(line)
        if "error" not in row:
            latest[row["source_id"]] = row
    out_dir.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    dispositions_out = []
    with (out_dir / "collenette-saudi-annotated.jsonl").open("w", encoding="utf-8") as sink:
        for source_id in sorted(latest, key=lambda s: [int(x) for x in re.findall(r"\d+", s)]):
            raw = latest[source_id]
            rec = to_ncvc_record(raw)
            prepare(rec)
            segments, dispositions = annotate_record(rec, replace(res, rules=base_rules))
            for d in dispositions:
                counts[f"rows_{d.status}"] += 1
                counts["rows"] += 1
                if d.status not in {"accepted", "review", "held"}:
                    reasons[d.reason] += 1
                index = d.row.get("row")
                dispositions_out.append(
                    {
                        "source_id": source_id,
                        "taxon": raw.get("taxon", ""),
                        "row": index,
                        "entity_en": d.row.get("entity_en", ""),
                        "quality_en": d.row.get("quality_en", ""),
                        "source_en": d.row.get("source_en", ""),
                        "status": d.status,
                        "reason": d.reason,
                        "po_id": d.row.get("po_id", ""),
                        "pato_id": d.row.get("pato_id", ""),
                        "value_terms": d.row.get("value_terms", ""),
                    }
                )
            for seg in segments:
                colour_migrator.migrate_record(seg)
                seg["taxon"] = raw.get("taxon", seg.get("taxon"))
                for assertion in seg["assertions"]:
                    assertion["extractor"] = EXTRACTOR
                    assertion["mapping_provenance"] = [
                        p.replace("claude_opus_transcription", EXTRACTOR)
                        for p in assertion.get("mapping_provenance", [])
                    ]
                for span in seg["unresolved_spans"]:
                    span["extractor"] = EXTRACTOR
                counts["assertions"] += len(seg["assertions"])
                counts["unresolved_spans"] += len(seg["unresolved_spans"])
                sink.write(json.dumps(seg, ensure_ascii=False) + "\n")
    fields = list(dispositions_out[0]) if dispositions_out else []
    with (out_dir / "collenette-saudi-dispositions.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(dispositions_out)
    summary = {
        "records": len(latest),
        **dict(counts),
        "unresolved_reasons": dict(reasons.most_common()),
    }
    (out_dir / "collenette-summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--raw", type=Path, default=Path("local-corpora/saudi-collenette/raw/collenette-qwen.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("local-corpora/saudi-collenette/derived"))
    args = parser.parse_args(argv)
    print(json.dumps(run(args.raw, args.out), indent=1))


if __name__ == "__main__":
    main()
