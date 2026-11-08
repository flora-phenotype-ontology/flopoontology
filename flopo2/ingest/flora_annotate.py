"""Anchor, ground and gate the Qwen transcription of any flora source.

Generalizes :mod:`flopo2.ingest.collenette_annotate` across all flora corpora in
:data:`flopo2.ingest.external.FLORA_SOURCES`.

Input is ``local-corpora/<source>/raw/<source>-qwen.jsonl`` from :mod:`flopo2.ingest.flora_llm`
(one record per botanical description segment, NCVC-style ``phenotypes`` rows). Every record is
turned into the NCVC record shape and passed through
:func:`flopo2.ingest.ncvc_annotate.annotate_record`, so anchoring, grounding, reviewed
normalization rules, colour-backbone migration, and the FLOPO gates are identical across floras.

In addition to the shared normalization tables (``flora_value_term_rules.tsv``,
``collenette_normalization.tsv``, ``llm_term_rules.tsv``) and shared LLM caches, per-flora
LLM caches under ``local-corpora/<source>/`` (``llm-rereads.jsonl``, ``llm-relations.jsonl``,
``llm-relation-chains.jsonl``, ``llm-term-rules.tsv``) are automatically loaded when present.

Output (``local-corpora/<source>/derived/``):
- ``<source>-annotated.jsonl`` (stage-22 wire format, colour values on the ISCC-NBS backbone)
- ``<source>-dispositions.tsv`` (per-row grounding/gate audit)
- ``<source>-summary.json`` (record, row, assertion, and unresolved-reason counts)
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

from flopo2.ingest.external import FLORA_SOURCES
from flopo2.ingest.llm_relations import load as load_llm_relations
from flopo2.ingest.llm_reread import load as load_rereads
from flopo2.ingest.ncvc_annotate import (
    annotate_record,
    colour_backbone_migrator,
    enable_atlas_options,
    load_resources,
    merge_rules,
)

RULE_TABLES = [
    Path("flopo2/ingest/flora_value_term_rules.tsv"),
    Path("flopo2/ingest/collenette_normalization.tsv"),
    Path("flopo2/ingest/llm_term_rules.tsv"),
]
_PAGE_RE = re.compile(r":page-(\d+)")


def extractor_name(source: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", source.lower()).strip("_")
    return f"qwen3.8-27b_{slug}_transcription"


def to_ncvc_record(raw: dict, source: str) -> dict:
    match = _PAGE_RE.search(raw["source_id"])
    return {
        "source": source,
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


def _sort_key(source_id: str) -> tuple[list[int], str]:
    return ([int(x) for x in re.findall(r"\d+", source_id)], source_id)


def run(
    source: str,
    raw_path: Path | None = None,
    out_dir: Path | None = None,
) -> dict:
    corpus_dir = Path("local-corpora") / source
    raw_path = raw_path or (corpus_dir / "raw" / f"{source}-qwen.jsonl")
    out_dir = out_dir or (corpus_dir / "derived")
    extractor = extractor_name(source)
    default_lang = str(FLORA_SOURCES.get(source, {}).get("language", "en"))

    res = load_resources()
    res.holds = []
    gap_tables = [p for p in RULE_TABLES[2:] if p.exists()]
    flora_rule_table = corpus_dir / "llm-term-rules.tsv"
    if flora_rule_table.exists():
        gap_tables.append(flora_rule_table)
    base_rules = merge_rules(res.rules, gap_tables, RULE_TABLES[:2])
    enable_atlas_options(res)

    # Overlay per-flora LLM caches onto the shared caches when present.
    flora_rereads = corpus_dir / "llm-rereads.jsonl"
    if flora_rereads.exists():
        res.rereads = {**(res.rereads or {}), **load_rereads(flora_rereads)}
    flora_relations = corpus_dir / "llm-relations.jsonl"
    if flora_relations.exists():
        res.llm_relations = {**(res.llm_relations or {}), **load_llm_relations(flora_relations)}
    flora_chains = corpus_dir / "llm-relation-chains.jsonl"
    if flora_chains.exists():
        res.llm_relation_chains = {
            **(res.llm_relation_chains or {}),
            **load_llm_relations(flora_chains),
        }

    colour_migrator = colour_backbone_migrator()
    latest: dict[str, dict] = {}
    if raw_path.exists():
        for line in raw_path.open(encoding="utf-8"):
            if not line.strip():
                continue
            row = json.loads(line)
            if "error" not in row and row.get("source_id"):
                latest[row["source_id"]] = row

    out_dir.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    dispositions_out: list[dict] = []
    annotated_path = out_dir / f"{source}-annotated.jsonl"
    dispositions_path = out_dir / f"{source}-dispositions.tsv"
    summary_path = out_dir / f"{source}-summary.json"

    with annotated_path.open("w", encoding="utf-8") as sink:
        for source_id in sorted(latest, key=_sort_key):
            raw = latest[source_id]
            rec = to_ncvc_record(raw, source)
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
                        "reread_from": d.row.get("reread_from", ""),
                    }
                )
            lang = raw.get("language") or default_lang
            for seg in segments:
                colour_migrator.migrate_record(seg)
                seg["taxon"] = raw.get("taxon", seg.get("taxon"))
                seg["language"] = lang
                for stmt in seg.get("source_statements", []):
                    stmt["language"] = lang
                for assertion in seg["assertions"]:
                    assertion["extractor"] = extractor
                    assertion["mapping_provenance"] = [
                        p.replace("claude_opus_transcription", extractor)
                        for p in assertion.get("mapping_provenance", [])
                    ]
                for span in seg["unresolved_spans"]:
                    span["extractor"] = extractor
                counts["assertions"] += len(seg["assertions"])
                counts["unresolved_spans"] += len(seg["unresolved_spans"])
                sink.write(json.dumps(seg, ensure_ascii=False) + "\n")

    fields = (
        list(dispositions_out[0])
        if dispositions_out
        else [
            "source_id",
            "taxon",
            "row",
            "entity_en",
            "quality_en",
            "source_en",
            "status",
            "reason",
            "po_id",
            "pato_id",
            "value_terms",
            "reread_from",
        ]
    )
    with dispositions_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fields, delimiter="\t")
        writer.writeheader()
        writer.writerows(dispositions_out)

    summary = {
        "source": source,
        "records": len(latest),
        **dict(counts),
        "unresolved_reasons": dict(reasons.most_common()),
    }
    summary_path.write_text(json.dumps(summary, indent=1) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--source", required=True, help="Flora source key (e.g. powo-fiq, eflora-fna)")
    parser.add_argument("--raw", type=Path, default=None, help="Override raw Qwen JSONL path")
    parser.add_argument("--out", type=Path, default=None, help="Override derived output directory")
    args = parser.parse_args(argv)
    print(json.dumps(run(args.source, args.raw, args.out), indent=1))


if __name__ == "__main__":
    main()
