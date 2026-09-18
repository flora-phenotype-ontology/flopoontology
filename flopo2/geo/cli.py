"""Build occurrence outputs: ``python -m flopo2.geo.cli {ncvc,florml} --out DIR``.

Writes ``occurrences.jsonl``, ``occurrences.ttl``, ``dwc_occurrence.csv``, ``occurrences.sqlite``,
``competency_queries.json`` (NCVC) and ``summary.json`` into ``--out``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from rdflib import Graph

from flopo2.geo import dwc, queries, rdf, sql
from flopo2.geo.models import OccurrenceAssertion, validation_issues


def summarize(occ: list[OccurrenceAssertion]) -> dict:
    places = {o.place.feature_iri: o.place for o in occ}
    return {
        "occurrences": len(occ),
        "distinct_taxa": len({o.taxon_name for o in occ}),
        "distinct_features": len(places),
        "features_resolved_geonames": sum(p.resolved for p in places.values()),
        "features_local": sum(not p.resolved for p in places.values()),
        "features_local_with_wikidata_match": sum(
            (not p.resolved) and bool(p.same_as) for p in places.values()
        ),
        "features_relative_with_anchor": sum(bool(p.anchor_iris) for p in places.values()),
        "features_with_sfWithin": sum(bool(p.within) for p in places.values()),
        "features_with_geometry": sum(p.geometry is not None for p in places.values()),
        "occurrences_on_resolved_features": sum(o.place.resolved for o in occ),
        "by_basis": dict(Counter(o.basis for o in occ)),
        "by_occurrence_status": dict(Counter(o.occurrence_status for o in occ)),
        "by_establishment_means": dict(Counter(o.establishment_means for o in occ)),
        "by_abundance": dict(Counter(o.abundance for o in occ)),
        "by_epistemic_modality": dict(Counter(o.epistemic_modality for o in occ)),
        "by_feature_type": dict(Counter(o.place.feature_type for o in occ)),
        "endemic": sum(o.endemic for o in occ),
        "extralimital": sum(o.extralimital for o in occ),
        "conflicts": sum(o.conflict for o in occ),
        "validation_issues": dict(Counter(i for o in occ for i in validation_issues(o))),
    }


def write_all(occ: list[OccurrenceAssertion], out: Path, query_set: dict | None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "occurrences.jsonl").open("w", encoding="utf-8") as fh:
        for o in occ:
            fh.write(json.dumps(o.model_dump(), ensure_ascii=False) + "\n")
    graph = rdf.to_graph(occ)
    graph.serialize(out / "occurrences.ttl", format="turtle")
    reparsed = Graph().parse(out / "occurrences.ttl", format="turtle")
    n_dwc = dwc.write_csv(occ, out / "dwc_occurrence.csv")
    db = out / "occurrences.sqlite"
    db.unlink(missing_ok=True)
    with sqlite3.connect(db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        sql.load_sqlite(conn, occ)
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        tables = {
            t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            for t in (
                "geo_feature",
                "geo_feature_within",
                "geo_feature_link",
                "occurrence_source_statement",
                "taxon_occurrence",
            )
        }
    summary = summarize(occ)
    summary["ttl_triples"] = len(graph)
    summary["ttl_reparsed_triples"] = len(reparsed)
    summary["dwc_rows"] = n_dwc
    summary["sqlite_rows"] = tables
    summary["sqlite_foreign_key_violations"] = len(fk)
    if query_set:
        results = {}
        for name, (desc, _q) in query_set.items():
            rows = queries.run(reparsed, name)
            results[name] = {"description": desc, "n_rows": len(rows), "rows": rows}
        (out / "competency_queries.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        summary["competency_query_rows"] = {k: v["n_rows"] for k, v in results.items()}
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ncvc")
    a.add_argument("--corpus", type=Path, default=Path("local-corpora/saudi-ncvc-guide"))
    a.add_argument("--out", type=Path, default=None)
    b = sub.add_parser("florml")
    b.add_argument("dirs", type=Path, nargs="+")
    b.add_argument("--out", type=Path, required=True)
    b.add_argument("--no-queries", action="store_true")
    args = ap.parse_args(argv)
    if args.cmd == "ncvc":
        from flopo2.geo.ncvc import build

        occ = build(args.corpus)
        out = args.out or args.corpus / "derived" / "geo"
        summary = write_all(occ, out, queries.COMPETENCY)
    else:
        from flopo2.geo.florml import iter_dirs

        occ = list(iter_dirs(args.dirs))
        summary = write_all(occ, args.out, None if args.no_queries else queries.FLORML)
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
