"""Extract and stage per-flora FLOPO ontology addition candidates.

Reads ``local-corpora/<source>/derived/<source>-annotated.jsonl`` and
``<source>-dispositions.tsv`` (plus ``local-corpora/<source>/llm-term-rules.tsv`` when present)
and writes staged candidate tables under ``curation/candidates/<source>/``:

1. ``value_term_candidates.tsv`` — unmatched botanical quality words
   (``no_ontology_term_for_quality``) that remain after LLM re-reading and lexical candidate
   matching, ranked by frequency with suggested PATO parent classes and bearer distributions
   (ready for promotion to ``config/flopo_flora_value_terms.tsv``).
2. ``bearer_candidates.tsv`` — unmatched anatomical structures
   (``missing_or_unsupported_bearer``) ranked by frequency with nearest PO candidates.
3. ``novel_po_pato_combinations.tsv`` — grounded ``(PO, PATO/FLOPO)`` pairs that are currently
   marked ``novel`` by ``config/valid_combinations.tsv`` or ``new_class_candidate`` by the
   FLOPO ID registry.
4. ``CANDIDATES.md`` — human-readable summary for the flora.

Running with ``--rollup`` also builds ``curation/candidates/SUMMARY.md`` across all floras that
have derived annotations, ranking cross-flora value terms, bearers, and novel combinations by
how many floras and treatments they appear in.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from flopo2.ingest.external import FLORA_SOURCES
from flopo2.ingest.llm_term_rules import flopo_local_terms
from flopo2.ingest.ncvc_annotate import normalize_key
from flopo2.saudi.vocab import parse_obo

_SHAPE_HINTS = re.compile(
    r"(?:oid|iform|ulate|ate|shaped|like|lobed|angled|angular|fid|sect|partite|cleft|"
    r"beaked|winged|horned|spurred|keeled|hooded|cupped|bell|funnel|tubular|conical|"
    r"globose|ovoid|oblong|lanceolate|linear|elliptic|orbicular|peltate|cordate|reniform)$",
    re.IGNORECASE,
)
_PILOSITY_HINTS = re.compile(
    r"(?:pilose|pilosulous|pubescent|puberul(?:ous|ent)|villous|villosulous|toment(?:ose|ulose)|"
    r"hirsute|hirtellous|hispid|hispidulous|strig(?:ose|illose)|sericeous|lanate|lanuginose|"
    r"floccose|arachnoid|barbate|bearded|ciliate|ciliolate|hairy|downy|woolly|bristly|glabrous|glabrescent)",
    re.IGNORECASE,
)
_TEXTURE_HINTS = re.compile(
    r"(?:coriaceous|chartaceous|membranous|scarious|crustaceous|fleshy|succulent|woody|"
    r"fibrous|corky|papery|leathery|horny|warty|verrucose|tuberculate|rugose|wrinkled|"
    r"striate|ribbed|grooved|sulcate|fissured|pitted|foveolate|reticulate|muricate|"
    r"echinate|aculeate|prickly|spiny|scabrous|papillose|viscid|glutinous|resinous|waxy)",
    re.IGNORECASE,
)
_POSITION_HINTS = re.compile(
    r"(?:axillary|terminal|basal|apical|lateral|subterminal|cauline|radical|epiphyllous|"
    r"leaf-opposed|extra-axillary|interpetiolar|intrapetiolar|submerged|floating|"
    r"aerial|subterranean|hypogeous|epigeous|pendulous|erect|ascending|prostrate|procumbent|"
    r"decumbent|spreading|patent|reflexed|deflexed|appressed|adpressed|imbricate|valvate)",
    re.IGNORECASE,
)
_SPATIAL_HINTS = re.compile(
    r"(?:solitary|paired|clustered|fasciculate|glomerulate|verticillate|whorled|opposite|"
    r"alternate|distichous|secund|rosulate|tufted|caespitose|cespitose|crowded|lax|dense)",
    re.IGNORECASE,
)
_ATTACHMENT_HINTS = re.compile(
    r"(?:sessile|subsessile|petiolate|pedicellate|stipitate|amplexicaul|perfoliate|"
    r"connate|adnate|free|coherent|fused|united|distinct|peltate|basifixed|dorsifixed|versatile)",
    re.IGNORECASE,
)
_ODOUR_HINTS = re.compile(
    r"(?:scented|smelling|odour|odor|fragrant|aromatic|foetid|fetid|pungent|sweet|bitter|sour)",
    re.IGNORECASE,
)
_SEX_HINTS = re.compile(
    r"(?:unisexual|bisexual|hermaphrodite|monoecious|dioecious|polygamous|staminate|"
    r"pistillate|carpellate|sterile|fertile|androgynous|gynoecious|andromonoecious)",
    re.IGNORECASE,
)


_NON_BEARER_NOISE = {
    "cm", "mm", "m", "dm", "km", "µm", "um", "ft", "in",
    "part", "part:", "parts", "absent", "present", "none",
    "by", "to", "or", "of", "the", "a", "an", "per",
    "merou", "merous", "sery", "series", "time", "times", "row", "rows",
}


def suggest_pato_parent(word: str) -> tuple[str, str]:
    """Return a heuristic (PATO ID, label) parent for a novel botanical quality word."""
    w = word.lower().strip()
    if _PILOSITY_HINTS.search(w):
        return ("PATO:0000066", "pilosity")
    if _ATTACHMENT_HINTS.search(w):
        return ("PATO:0001435", "attachment quality")
    if _SPATIAL_HINTS.search(w):
        return ("PATO:0000060", "spatial pattern")
    if _POSITION_HINTS.search(w):
        return ("PATO:0000140", "position")
    if _ODOUR_HINTS.search(w):
        return ("PATO:0001331", "odor")
    if _SEX_HINTS.search(w):
        return ("PATO:0001894", "phenotypic sex")
    if _TEXTURE_HINTS.search(w):
        return ("PATO:0000150", "texture")
    if _SHAPE_HINTS.search(w):
        return ("PATO:0000052", "shape")
    return ("PATO:0000141", "structure")


def _short_snippet(text: str, max_len: int = 48) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    if len(cleaned) <= max_len:
        return cleaned
    return cleaned[: max_len - 3].rstrip() + "..."


def _load_term_labels() -> dict[str, str]:
    labels: dict[str, str] = {}
    for obo_path in (Path("ont/plant_ontology.obo"), Path("ont/quality.obo")):
        if obo_path.exists():
            for term in parse_obo(obo_path).values():
                labels[term.id.replace(":", "_")] = term.name
                labels[term.id] = term.name
    for flopo_id, (label, _parent) in flopo_local_terms().items():
        labels[flopo_id] = label
        labels[flopo_id.replace("_", ":")] = label
    return labels


def extract_for_source(
    source: str,
    derived_dir: Path | None = None,
    out_dir: Path | None = None,
) -> dict:
    corpus_dir = Path("local-corpora") / source
    derived_dir = derived_dir or (corpus_dir / "derived")
    out_dir = out_dir or (Path("curation/candidates") / source)
    out_dir.mkdir(parents=True, exist_ok=True)

    annotated_path = derived_dir / f"{source}-annotated.jsonl"
    dispositions_path = derived_dir / f"{source}-dispositions.tsv"
    summary_path = derived_dir / f"{source}-summary.json"
    labels = _load_term_labels()

    value_rows: dict[str, list[dict]] = defaultdict(list)
    bearer_rows: dict[str, list[dict]] = defaultdict(list)
    novel_combos: dict[tuple[str, str, str], dict] = {}

    if dispositions_path.exists():
        with dispositions_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                reason = row.get("reason", "")
                if reason == "no_ontology_term_for_quality":
                    qkey = normalize_key(row.get("quality_en", ""))
                    if qkey and len(qkey) >= 2 and not re.search(r"\d", qkey):
                        value_rows[qkey].append(row)
                elif reason == "missing_or_unsupported_bearer":
                    bkey = normalize_key(row.get("entity_en", "")).strip(":")
                    if (
                        bkey
                        and len(bkey) >= 2
                        and bkey not in _NON_BEARER_NOISE
                        and not re.search(r"\d", bkey)
                    ):
                        bearer_rows[bkey].append(row)

    if annotated_path.exists():
        with annotated_path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                seg = json.loads(line)
                taxon = seg.get("taxon", "")
                for a in seg.get("assertions", []):
                    gate = a.get("gate") or {}
                    reasons = set(gate.get("reasons") or [])
                    flopo_status = gate.get("flopo_status", "")
                    if "po_pato_novel" not in reasons and flopo_status != "new_class_candidate":
                        continue
                    po_id = a.get("po_id", "")
                    pato_id = a.get("pato_id", "")
                    vterms = a.get("value_terms") or a.get("value_term_ids") or []
                    vterm = vterms[0] if len(vterms) == 1 else ""
                    key = (po_id, pato_id, vterm)
                    entry = novel_combos.setdefault(
                        key,
                        {
                            "po_id": po_id,
                            "po_label": a.get("po_label") or labels.get(po_id, ""),
                            "pato_id": pato_id,
                            "pato_label": a.get("pato_label") or labels.get(pato_id, ""),
                            "value_term": vterm,
                            "value_label": labels.get(vterm, ""),
                            "flopo_signature": gate.get("flopo_signature", ""),
                            "flopo_status": flopo_status,
                            "po_pato_status": gate.get("po_pato_status", ""),
                            "count": 0,
                            "taxa": set(),
                            "examples": [],
                        },
                    )
                    entry["count"] += 1
                    if taxon:
                        entry["taxa"].add(taxon)
                    snippet = _short_snippet(a.get("source_text", ""))
                    if snippet and snippet not in entry["examples"] and len(entry["examples"]) < 3:
                        entry["examples"].append(snippet)

    # 1. Write value_term_candidates.tsv
    value_candidates_out = []
    for qkey, rows in sorted(value_rows.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        parent_id, parent_label = suggest_pato_parent(qkey)
        bearer_counts = Counter(
            row.get("po_id") or normalize_key(row.get("entity_en", ""))
            for row in rows
            if row.get("po_id") or row.get("entity_en")
        )
        top_bearers = "|".join(b for b, _ in bearer_counts.most_common(5))
        taxa = sorted({r.get("taxon", "") for r in rows if r.get("taxon")})
        examples = []
        for r in rows:
            ex = f"{r.get('entity_en', '')}: {_short_snippet(r.get('source_en', ''), 36)}"
            if ex not in examples:
                examples.append(ex)
            if len(examples) >= 3:
                break
        value_candidates_out.append(
            {
                "candidate_label": qkey,
                "count": len(rows),
                "taxa_count": len(taxa),
                "suggested_parent": parent_id,
                "suggested_parent_label": parent_label,
                "bearers": top_bearers,
                "example_taxa": "|".join(taxa[:3]),
                "example_phrases": " ; ".join(examples),
            }
        )

    value_fields = [
        "candidate_label",
        "count",
        "taxa_count",
        "suggested_parent",
        "suggested_parent_label",
        "bearers",
        "example_taxa",
        "example_phrases",
    ]
    with (out_dir / "value_term_candidates.tsv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, value_fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(value_candidates_out)

    # 2. Write bearer_candidates.tsv
    bearer_candidates_out = []
    for bkey, rows in sorted(bearer_rows.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        q_counts = Counter(
            normalize_key(row.get("quality_en", "")) for row in rows if row.get("quality_en")
        )
        top_qualities = "|".join(q for q, _ in q_counts.most_common(5))
        taxa = sorted({r.get("taxon", "") for r in rows if r.get("taxon")})
        examples = []
        for r in rows:
            ex = f"{r.get('entity_en', '')} / {r.get('quality_en', '')}: {_short_snippet(r.get('source_en', ''), 36)}"
            if ex not in examples:
                examples.append(ex)
            if len(examples) >= 3:
                break
        bearer_candidates_out.append(
            {
                "candidate_bearer": bkey,
                "count": len(rows),
                "taxa_count": len(taxa),
                "qualities_seen": top_qualities,
                "example_taxa": "|".join(taxa[:3]),
                "example_phrases": " ; ".join(examples),
            }
        )

    bearer_fields = [
        "candidate_bearer",
        "count",
        "taxa_count",
        "qualities_seen",
        "example_taxa",
        "example_phrases",
    ]
    with (out_dir / "bearer_candidates.tsv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, bearer_fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(bearer_candidates_out)

    # 3. Write novel_po_pato_combinations.tsv
    novel_out = []
    for _key, entry in sorted(
        novel_combos.items(),
        key=lambda kv: (-kv[1]["count"], kv[0][0], kv[0][1], kv[0][2]),
    ):
        eff_label = entry["value_label"] or entry["pato_label"]
        novel_out.append(
            {
                "po_id": entry["po_id"],
                "po_label": entry["po_label"],
                "pato_id": entry["pato_id"],
                "pato_label": entry["pato_label"],
                "value_term": entry["value_term"],
                "value_label": entry["value_label"],
                "example_label": f"{entry['po_label']} {eff_label}".strip(),
                "flopo_signature": entry["flopo_signature"],
                "flopo_status": entry["flopo_status"],
                "po_pato_status": entry["po_pato_status"],
                "count": entry["count"],
                "taxa_count": len(entry["taxa"]),
                "example_phrases": " ; ".join(entry["examples"]),
            }
        )

    novel_fields = [
        "po_id",
        "po_label",
        "pato_id",
        "pato_label",
        "value_term",
        "value_label",
        "example_label",
        "flopo_signature",
        "flopo_status",
        "po_pato_status",
        "count",
        "taxa_count",
        "example_phrases",
    ]
    with (out_dir / "novel_po_pato_combinations.tsv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, novel_fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(novel_out)

    # 4. Write CANDIDATES.md
    summary_data = {}
    if summary_path.exists():
        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
    meta = FLORA_SOURCES.get(source, {})
    title = meta.get("title", source)
    md_lines = [
        f"# FLOPO Candidate Additions — {title} (`{source}`)",
        "",
        f"- **Records processed**: {summary_data.get('records', 0):,}",
        f"- **Extracted trait rows**: {summary_data.get('rows', 0):,}",
        f"- **Formal assertions emitted**: {summary_data.get('assertions', 0):,}",
        f"- **Distinct candidate value terms**: {len(value_candidates_out):,}",
        f"- **Distinct candidate anatomical bearers**: {len(bearer_candidates_out):,}",
        f"- **Distinct novel PO × PATO/FLOPO combinations**: {len(novel_out):,}",
        "",
        "## Top Candidate FLOPO Value Terms (`value_term_candidates.tsv`)",
        "",
        "| Quality word | Count | Taxa | Suggested PATO parent | Top bearers |",
        "|---|---:|---:|---|---|",
    ]
    for row in value_candidates_out[:25]:
        md_lines.append(
            f"| `{row['candidate_label']}` | {row['count']} | {row['taxa_count']} | "
            f"`{row['suggested_parent']}` ({row['suggested_parent_label']}) | `{row['bearers']}` |"
        )
    md_lines.extend(
        [
            "",
            "## Top Candidate Anatomical Bearers (`bearer_candidates.tsv`)",
            "",
            "| Bearer word | Count | Taxa | Qualities seen |",
            "|---|---:|---:|---|",
        ]
    )
    for row in bearer_candidates_out[:25]:
        md_lines.append(
            f"| `{row['candidate_bearer']}` | {row['count']} | {row['taxa_count']} | "
            f"`{row['qualities_seen']}` |"
        )
    md_lines.extend(
        [
            "",
            "## Top Novel PO × PATO / FLOPO Class Candidates (`novel_po_pato_combinations.tsv`)",
            "",
            "| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Count | Taxa |",
            "|---|---|---|---|---|---|---:|---:|",
        ]
    )
    for row in novel_out[:25]:
        q_id = row["value_term"] or row["pato_id"]
        q_lbl = row["value_label"] or row["pato_label"]
        md_lines.append(
            f"| `{row['po_id']}` | {row['po_label']} | `{q_id}` | {q_lbl} | "
            f"`{row['flopo_signature']}` | `{row['po_pato_status']}` / `{row['flopo_status']}` | "
            f"{row['count']} | {row['taxa_count']} |"
        )
    (out_dir / "CANDIDATES.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    return {
        "source": source,
        "records": summary_data.get("records", 0),
        "assertions": summary_data.get("assertions", 0),
        "value_term_candidates": len(value_candidates_out),
        "bearer_candidates": len(bearer_candidates_out),
        "novel_combinations": len(novel_out),
    }


def build_rollup(candidates_root: Path = Path("curation/candidates")) -> dict:
    """Aggregate candidate TSVs across all floras into curation/candidates/SUMMARY.md."""
    flora_dirs = sorted(
        p for p in candidates_root.iterdir() if p.is_dir() and (p / "value_term_candidates.tsv").exists()
    )
    val_agg: dict[str, dict] = {}
    bearer_agg: dict[str, dict] = {}
    combo_agg: dict[str, dict] = {}
    flora_stats: list[dict] = []

    for fdir in flora_dirs:
        source = fdir.name
        summary_path = Path("local-corpora") / source / "derived" / f"{source}-summary.json"
        sdata = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}

        with (fdir / "value_term_candidates.tsv").open(encoding="utf-8", newline="") as fh:
            vrows = list(csv.DictReader(fh, delimiter="\t"))
        for r in vrows:
            lbl = r["candidate_label"]
            item = val_agg.setdefault(
                lbl,
                {
                    "label": lbl,
                    "total_count": 0,
                    "floras": set(),
                    "suggested_parent": r["suggested_parent"],
                    "suggested_parent_label": r["suggested_parent_label"],
                    "bearers": Counter(),
                },
            )
            item["total_count"] += int(r["count"])
            item["floras"].add(source)
            for b in (r.get("bearers") or "").split("|"):
                if b:
                    item["bearers"][b] += int(r["count"])

        with (fdir / "bearer_candidates.tsv").open(encoding="utf-8", newline="") as fh:
            brows = list(csv.DictReader(fh, delimiter="\t"))
        for r in brows:
            lbl = r["candidate_bearer"]
            item = bearer_agg.setdefault(
                lbl,
                {
                    "bearer": lbl,
                    "total_count": 0,
                    "floras": set(),
                    "qualities": Counter(),
                },
            )
            item["total_count"] += int(r["count"])
            item["floras"].add(source)
            for q in (r.get("qualities_seen") or "").split("|"):
                if q:
                    item["qualities"][q] += int(r["count"])

        with (fdir / "novel_po_pato_combinations.tsv").open(encoding="utf-8", newline="") as fh:
            crows = list(csv.DictReader(fh, delimiter="\t"))
        for r in crows:
            sig = r["flopo_signature"] or f"{r['po_id']}|{r['value_term'] or r['pato_id']}"
            item = combo_agg.setdefault(
                sig,
                {
                    "signature": sig,
                    "po_id": r["po_id"],
                    "po_label": r["po_label"],
                    "quality_id": r["value_term"] or r["pato_id"],
                    "quality_label": r["value_label"] or r["pato_label"],
                    "example_label": r["example_label"],
                    "po_pato_status": r["po_pato_status"],
                    "flopo_status": r["flopo_status"],
                    "total_count": 0,
                    "floras": set(),
                },
            )
            item["total_count"] += int(r["count"])
            item["floras"].add(source)

        flora_stats.append(
            {
                "source": source,
                "title": FLORA_SOURCES.get(source, {}).get("title", source),
                "records": sdata.get("records", 0),
                "rows": sdata.get("rows", 0),
                "assertions": sdata.get("assertions", 0),
                "value_candidates": len(vrows),
                "bearer_candidates": len(brows),
                "novel_combinations": len(crows),
            }
        )

    lines = [
        "# Cross-Flora FLOPO Ontology Addition Candidates",
        "",
        "This report aggregates candidate value terms (`FLOPO:0991xxx`), missing anatomical bearers,",
        "and novel `PO × PATO/FLOPO` combinations across all processed floras.",
        "",
        "## Per-Flora Overview",
        "",
        "| Source | Flora | Records | Extracted Rows | Assertions | Value Candidates | Bearer Candidates | Novel Combinations |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for st in flora_stats:
        lines.append(
            f"| [`{st['source']}`]({st['source']}/CANDIDATES.md) | {st['title']} | "
            f"{st['records']:,} | {st['rows']:,} | {st['assertions']:,} | "
            f"{st['value_candidates']:,} | {st['bearer_candidates']:,} | {st['novel_combinations']:,} |"
        )

    lines.extend(
        [
            "",
            "## Top Cross-Flora Value Term Candidates",
            "",
            "Ranked first by number of floras in which the term is needed, then by total occurrences.",
            "",
            "| Quality word | Floras | Total Count | Suggested PATO parent | Top Bearers |",
            "|---|---:|---:|---|---|",
        ]
    )
    for item in sorted(
        val_agg.values(), key=lambda x: (-len(x["floras"]), -x["total_count"], x["label"])
    )[:40]:
        top_b = "|".join(b for b, _ in item["bearers"].most_common(4))
        lines.append(
            f"| `{item['label']}` | {len(item['floras'])} | {item['total_count']:,} | "
            f"`{item['suggested_parent']}` ({item['suggested_parent_label']}) | `{top_b}` |"
        )

    lines.extend(
        [
            "",
            "## Top Cross-Flora Anatomical Bearer Candidates",
            "",
            "| Bearer word | Floras | Total Count | Top Qualities |",
            "|---|---:|---:|---|",
        ]
    )
    for item in sorted(
        bearer_agg.values(), key=lambda x: (-len(x["floras"]), -x["total_count"], x["bearer"])
    )[:40]:
        top_q = "|".join(q for q, _ in item["qualities"].most_common(4))
        lines.append(
            f"| `{item['bearer']}` | {len(item['floras'])} | {item['total_count']:,} | `{top_q}` |"
        )

    lines.extend(
        [
            "",
            "## Top Cross-Flora Novel PO × PATO / FLOPO Combinations",
            "",
            "| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Floras | Total Count |",
            "|---|---|---|---|---|---|---:|---:|",
        ]
    )
    for item in sorted(
        combo_agg.values(), key=lambda x: (-len(x["floras"]), -x["total_count"], x["signature"])
    )[:40]:
        lines.append(
            f"| `{item['po_id']}` | {item['po_label']} | `{item['quality_id']}` | "
            f"{item['quality_label']} | `{item['signature']}` | "
            f"`{item['po_pato_status']}` / `{item['flopo_status']}` | "
            f"{len(item['floras'])} | {item['total_count']:,} |"
        )

    (candidates_root / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "floras": len(flora_stats),
        "distinct_value_candidates": len(val_agg),
        "distinct_bearer_candidates": len(bearer_agg),
        "distinct_novel_combinations": len(combo_agg),
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--source", action="append", help="Flora source key(s) to extract candidates for")
    parser.add_argument("--all", action="store_true", help="Extract candidates for all floras with derived annotations")
    parser.add_argument("--rollup", action="store_true", help="Rebuild cross-flora curation/candidates/SUMMARY.md")
    args = parser.parse_args(argv)

    sources = list(args.source or [])
    if args.all:
        for p in sorted(Path("local-corpora").glob("*/derived/*-annotated.jsonl")):
            src = p.parent.parent.name
            if src not in {"saudi-ncvc-guide", "saudi-collenette"} and src not in sources:
                sources.append(src)

    results = []
    for src in sources:
        results.append(extract_for_source(src))
    if args.rollup or args.all:
        rollup = build_rollup()
        print(json.dumps({"sources": results, "rollup": rollup}, indent=1))
    else:
        print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
