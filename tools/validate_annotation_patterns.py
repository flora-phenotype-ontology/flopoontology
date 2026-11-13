#!/usr/bin/env python3
"""Check the RDF of annotated flora records against the annotation design patterns (docs/odp/).

    python -m tools.validate_annotation_patterns local-corpora/eflora-fop/derived/eflora-fop-annotated.jsonl
    python -m tools.validate_annotation_patterns FILE... --per-pattern 50 --json report.json

For each pattern, up to ``--per-pattern`` records that use it are taken from the corpora, written
as the atlas writes them (:meth:`flopo2.saudi.build.Builder.index_corpus`), and checked against

* the ShEx shape of the pattern (``docs/odp/shapes/flopo-annotation-patterns.shex``), and
* the SPARQL rules that compare two values of a record (``docs/odp/shapes/rules.rq``).

The data-model rules of the patterns (``flopo2.verify.data_model.pattern_issues``) run on every
record in the pipeline's own gate; this tool is the check of the RDF side. Exit status 1 when a
record fails a shape or a rule.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

SHAPES = Path("docs/odp/shapes/flopo-annotation-patterns.shex")
RULES = Path("docs/odp/shapes/rules.rq")
SHAPE_BASE = "http://phenomebrowser.net/flopo/shapes/"


def _numeric(a: dict) -> bool:
    return a.get("value_low") is not None or a.get("value_high") is not None


# pattern -> (shape, does this assertion use the pattern?)
PATTERNS = {
    "01 approximate value": ("ApproximateValue", lambda a: a.get("value_qualifier") not in (None, "", "exact")),
    "02 bounded measurement": ("BoundedMeasurement", lambda a: _numeric(a) and a.get("unit") and not a.get("ratio_numerator")
                               and (a.get("value_low") is None) != (a.get("value_high") is None)),
    "03 count of parts": ("CountOfParts", lambda a: _numeric(a) and a.get("unit") == "count"),
    "04 state of the bearer": ("BearerState", lambda a: bool(a.get("bearer_context_qualities"))),
    "05 range with extremes": ("RangeWithExtremes", lambda a: a.get("value_min_extreme") is not None
                               or a.get("value_max_extreme") is not None),
    "06 specimen condition": ("SpecimenCondition", lambda a: bool(a.get("specimen_condition"))),
    "07a alternatives of one attribute": ("AlternativesOfOneAttribute", lambda a: a.get("value_operator") == "one_of"
                                          and len(a.get("value_terms") or []) > 1
                                          and a.get("value_union_scope") != "across_attributes"),
    "07b alternatives across attributes": ("AlternativesAcrossAttributes",
                                           lambda a: a.get("value_union_scope") == "across_attributes"),
    "08 alternative with frequency": ("AlternativeWithFrequency", lambda a: a.get("value_operator") == "one_of" and any(
        (o.get("frequency_qualifier") or "unspecified") != "unspecified" for o in a.get("value_operands") or [])),
    "09 relation to another part": ("RelationToAnotherPart", lambda a: bool(a.get("towards"))
                                    and (a["towards"].get("ratio_low") is None)),
    "10 ratio to another part": ("RatioToAnotherPart", lambda a: bool(a.get("towards"))
                                 and a["towards"].get("ratio_low") is not None),
    "11 ratio of two dimensions": ("RatioOfTwoDimensions", lambda a: bool(a.get("ratio_numerator"))),
    "12 part of a qualified whole": ("PartOfQualifiedWhole", lambda a: bool(a.get("bearer_whole"))),
}


def load_rules(path: Path = RULES) -> list[tuple[str, str]]:
    rules = []
    for block in path.read_text(encoding="utf-8").split("\n----------\n"):
        name = next((line.split("rule:", 1)[1].split("(")[0].strip() for line in block.splitlines()
                     if line.startswith("# rule:")), "")
        if name:
            rules.append((name, block))
    return rules


def sample(paths: list[Path], per_pattern: int) -> tuple[list[dict], dict[tuple[str, int], list[str]]]:
    """Records reduced to the sampled assertions, and the patterns of each (source_id, index)."""

    taken: Counter = Counter()
    records, uses = [], {}
    for path in paths:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if all(taken[name] >= per_pattern for name in PATTERNS):
                    break
                record = json.loads(line)
                if record.get("language") == "ar":
                    continue
                keep = []
                for assertion in record.get("assertions") or []:
                    names = [name for name, (_shape, test) in PATTERNS.items()
                             if taken[name] < per_pattern and test(assertion)]
                    if names:
                        for name in names:
                            taken[name] += 1
                        keep.append((assertion, names))
                if keep:
                    record = {**record, "assertions": [a for a, _ in keep], "unresolved_spans": []}
                    for index, (_a, names) in enumerate(keep):
                        uses[(record["source_id"], index)] = names
                    records.append(record)
    return records, uses


def validate(paths: list[Path], per_pattern: int = 25) -> dict:
    from pyshex import ShExEvaluator
    from rdflib import Graph, URIRef

    from flopo2.owl.assertions import formal_assertion_iri
    from flopo2.saudi.build import Builder

    records, uses = sample(paths, per_pattern)
    graph = Graph()
    with tempfile.TemporaryDirectory(dir=Path.cwd() / "local-corpora" if (Path.cwd() / "local-corpora").is_dir() else None) as tmp:
        corpus = Path(tmp) / "sample.jsonl"
        corpus.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
        Builder(out=Path(tmp) / "atlas").index_corpus("odp-sample", corpus, graph)
    schema = SHAPES.read_text(encoding="utf-8")
    report = {"records": len(uses), "triples": len(graph), "patterns": {}, "rules": {}, "failures": []}
    for record in records:
        for index, assertion in enumerate(record["assertions"]):
            node = formal_assertion_iri(assertion["source_statement_id"], index, assertion)
            for name in uses[(record["source_id"], index)]:
                shape = PATTERNS[name][0]
                entry = report["patterns"].setdefault(name, {"shape": shape, "checked": 0, "failed": 0})
                entry["checked"] += 1
                result = ShExEvaluator(rdf=graph, schema=schema, focus=URIRef(node),
                                       start=URIRef(SHAPE_BASE + shape)).evaluate()[0]
                if not result.result:
                    entry["failed"] += 1
                    if len(report["failures"]) < 20:
                        report["failures"].append({"pattern": name, "record": str(node),
                                                   "text": assertion.get("source_text", "")[:80],
                                                   "reason": " ".join(str(result.reason).split())[:300]})
    for name, query in load_rules():
        broken = [str(row[0]) for row in graph.query(query)]
        report["rules"][name] = len(broken)
        for node in broken[:3]:
            report["failures"].append({"rule": name, "record": node})
    report["ok"] = not report["failures"]
    return report


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("corpora", nargs="+", type=Path)
    parser.add_argument("--per-pattern", type=int, default=25)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    report = validate(args.corpora, args.per_pattern)
    for name, entry in sorted(report["patterns"].items()):
        print(f"{name:38s} {entry['shape']:30s} {entry['checked'] - entry['failed']:4d}/{entry['checked']:<4d} conform")
    for name in PATTERNS:
        if name not in report["patterns"]:
            print(f"{name:38s} {PATTERNS[name][0]:30s}    no record in the sample")
    for name, broken in report["rules"].items():
        print(f"rule {name:50s} {'ok' if not broken else f'{broken} records break it'}")
    for failure in report["failures"]:
        print("FAIL", json.dumps(failure, ensure_ascii=False))
    if args.json:
        args.json.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    sys.exit(0 if report["ok"] else 1)


if __name__ == "__main__":
    main()
