"""Build import-free OBO inputs for an independently reproducible OAK lexmatch baseline."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

from flopo2.terminology.catalog import OntologyCatalog, load_catalog_from_ontology_files


def _escape(value: str) -> str:
    return (value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _obo_curie(value: str) -> str:
    match = re.fullmatch(r"(PO|PATO|FLOPO)_(\d+)", value)
    return f"{match.group(1)}:{match.group(2)}" if match else value


def _write_obo(stanzas: list[list[str]], output: Path, ontology: str) -> None:
    lines = ["format-version: 1.4", f"ontology: {ontology}", ""]
    for stanza in stanzas:
        lines.extend(("[Term]", *stanza, ""))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines), encoding="utf-8")


def write_surface_obo(
    surface_report: Path,
    output: Path,
    mapping_output: Path,
) -> int:
    with Path(surface_report).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    surfaces = sorted(
        {
            (row.get("surface_form") or "").strip(): (row.get("corpus_frequency") or "0")
            for row in rows
            if (row.get("surface_form") or "").strip()
        }.items()
    )
    stanzas = []
    mappings = []
    for index, (surface, frequency) in enumerate(surfaces, start=1):
        query_id = f"BTERM:LEX{index:06d}"
        stanzas.append([f"id: {query_id}", f"name: {_escape(surface)}"])
        mappings.append(
            {"query_id": query_id, "surface_form": surface, "corpus_frequency": frequency}
        )
    _write_obo(stanzas, output, "flopo-botanical-lexmatch-queries")
    mapping_output.parent.mkdir(parents=True, exist_ok=True)
    with mapping_output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("query_id", "surface_form", "corpus_frequency"),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(mappings)
    return len(mappings)


def write_catalog_obo(
    catalog: OntologyCatalog,
    output: Path,
    namespaces: set[str] | None = None,
    include_definitions: bool = True,
) -> int:
    stanzas = []
    allowed = namespaces or {"PO", "PATO", "FLOPO"}
    for term in sorted(catalog.terms.values(), key=lambda item: item.curie):
        if term.deprecated or term.namespace not in allowed:
            continue
        lines = [f"id: {_obo_curie(term.curie)}", f"name: {_escape(term.label)}"]
        if include_definitions and term.definition:
            lines.append(f'def: "{_escape(term.definition)}" []')
        scopes = {label: scope for label, scope in term.synonym_scopes}
        seen = set()
        for synonym in term.synonyms:
            if not synonym or synonym in seen:
                continue
            seen.add(synonym)
            scope = scopes.get(synonym, "EXACT")
            if scope not in {"EXACT", "BROAD", "NARROW", "RELATED"}:
                scope = "RELATED"
            lines.append(f'synonym: "{_escape(synonym)}" {scope} []')
        stanzas.append(lines)
    _write_obo(stanzas, output, "flopo-current-target-lexicon")
    return len(stanzas)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--surface-report", type=Path, required=True)
    parser.add_argument("--po-obo", type=Path, default=Path("ont/plant_ontology.obo"))
    parser.add_argument("--pato-obo", type=Path, default=Path("ont/quality.obo"))
    parser.add_argument("--flopo-owl", type=Path, default=Path("ontology/flopo.owl"))
    parser.add_argument("--flopo-registry", type=Path, default=Path("config/flopo_id_registry.tsv"))
    parser.add_argument("--query-obo", type=Path, required=True)
    parser.add_argument("--query-map", type=Path, required=True)
    parser.add_argument("--catalog-obo", type=Path, required=True)
    parser.add_argument(
        "--manifest-out",
        type=Path,
        help="write the deterministic input counts and hashes as JSON",
    )
    parser.add_argument(
        "--namespace",
        action="append",
        choices=("PO", "PATO", "FLOPO"),
        help="limit the target export; repeat for multiple namespaces",
    )
    parser.add_argument(
        "--omit-definitions",
        action="store_true",
        help="omit definitions because OAK lexmatch uses only labels and synonyms",
    )
    args = parser.parse_args()

    query_count = write_surface_obo(args.surface_report, args.query_obo, args.query_map)
    catalog = load_catalog_from_ontology_files(
        args.po_obo,
        args.pato_obo,
        args.flopo_owl,
        args.flopo_registry,
    )
    target_count = write_catalog_obo(
        catalog,
        args.catalog_obo,
        set(args.namespace) if args.namespace else None,
        include_definitions=not args.omit_definitions,
    )
    rendered = (
        json.dumps(
            {
                "queries": query_count,
                "targets": target_count,
                "query_obo": str(args.query_obo),
                "query_obo_sha256": _sha256(args.query_obo),
                "query_map": str(args.query_map),
                "query_map_sha256": _sha256(args.query_map),
                "catalog_obo": str(args.catalog_obo),
                "catalog_obo_sha256": _sha256(args.catalog_obo),
            },
            indent=2,
        )
        + "\n"
    )
    if args.manifest_out:
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
