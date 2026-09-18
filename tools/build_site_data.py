#!/usr/bin/env python3
"""Build compact JSON data for the static FLOPO v2 browser."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


PO_GROUPS = [
    ("flower", {"flower", "petal", "sepal", "corolla", "calyx", "stamen", "anther", "pollen"}),
    ("leaf", {"leaf", "leaflet", "stipule", "lamina"}),
    ("stem", {"stem", "branch", "shoot", "trunk", "bark", "vine", "tendril"}),
    ("fruit/seed", {"fruit", "seed", "pod", "capsule", "achene"}),
    ("inflorescence", {"inflorescence", "raceme", "spike", "head"}),
    ("root", {"root", "rhizome", "tuber"}),
]

PATO_GROUPS = [
    ("color", {"color", "pigmentation"}),
    ("shape", {"shape", "curvature", "orientation"}),
    ("size", {"size", "length", "width", "height", "diameter", "thickness"}),
    ("count", {"count", "number"}),
    ("texture", {"texture", "hairy", "glabrous", "surface"}),
    ("odor", {"scent", "aromatic", "odor"}),
]


def group_for(label: str, groups: list[tuple[str, set[str]]], default: str) -> str:
    text = label.lower()
    for name, words in groups:
        if any(word in text for word in words):
            return name
    return default


def main() -> None:
    source = Path("scratchpad/collenette-saudi-majority-2of3.tsv")
    out = Path("web/data")
    out.mkdir(parents=True, exist_ok=True)

    taxa: dict[str, dict] = {}
    traits: dict[str, dict] = {}
    assertions: list[dict] = []
    taxon_traits: defaultdict[str, set[str]] = defaultdict(set)
    trait_taxa: defaultdict[str, set[str]] = defaultdict(set)

    with source.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            taxon = row["taxon"]
            po_id = row["po_id"]
            pato_id = row["pato_id"]
            negated = row["negated"].lower() == "true"
            trait_id = f"{po_id}|{pato_id}|{int(negated)}"
            po_label = row["po_label"] or po_id
            pato_label = row["pato_label"] or pato_id
            trait_label = f"{po_label} - {'not ' if negated else ''}{pato_label}"
            organ_group = group_for(po_label, PO_GROUPS, "other organ")
            quality_group = group_for(pato_label, PATO_GROUPS, "other quality")

            taxa.setdefault(taxon, {"id": taxon, "name": taxon, "trait_count": 0})
            traits.setdefault(
                trait_id,
                {
                    "id": trait_id,
                    "label": trait_label,
                    "po_id": po_id,
                    "po_label": po_label,
                    "pato_id": pato_id,
                    "pato_label": pato_label,
                    "negated": negated,
                    "organ_group": organ_group,
                    "quality_group": quality_group,
                    "taxon_count": 0,
                },
            )
            assertion = {
                "taxon": taxon,
                "trait_id": trait_id,
                "support": int(row["support"]),
                "value_text": row.get("value_text", ""),
                "value_pato_ids": [x for x in row.get("value_pato_ids", "").split("|") if x],
                "value_pato_labels": [x for x in row.get("value_pato_labels", "").split("|") if x],
                "value_flopo_ids": [x for x in row.get("value_flopo_ids", "").split("|") if x],
                "value_flopo_labels": [x for x in row.get("value_flopo_labels", "").split("|") if x],
                "value_low": row.get("value_low", ""),
                "value_high": row.get("value_high", ""),
                "unit": row.get("unit", ""),
                "source_text": row["source_text"],
                "source_id": row["source_id"],
                "flopo_iri": row["flopo_iri"],
                "flopo_status": row["flopo_status"],
            }
            assertions.append(assertion)
            taxon_traits[taxon].add(trait_id)
            trait_taxa[trait_id].add(taxon)

    for taxon, ids in taxon_traits.items():
        taxa[taxon]["trait_count"] = len(ids)
    for trait_id, names in trait_taxa.items():
        traits[trait_id]["taxon_count"] = len(names)

    summary = {
        "source": "Collenette Saudi majority 2/3",
        "taxa": len(taxa),
        "traits": len(traits),
        "phenotype_assertions": len(assertions),
        "organ_groups": Counter(t["organ_group"] for t in traits.values()),
        "quality_groups": Counter(t["quality_group"] for t in traits.values()),
    }

    payload = {
        "summary": summary,
        "taxa": sorted(taxa.values(), key=lambda x: x["name"]),
        "traits": sorted(traits.values(), key=lambda x: (-x["taxon_count"], x["label"])),
        "assertions": assertions,
        "taxon_traits": {k: sorted(v) for k, v in taxon_traits.items()},
        "trait_taxa": {k: sorted(v) for k, v in trait_taxa.items()},
    }
    (out / "flopo-site-data.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2, default=dict))


if __name__ == "__main__":
    main()
