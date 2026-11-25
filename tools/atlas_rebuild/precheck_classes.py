"""Step of tools/atlas_rebuild/run.sh. Build the class expression of every record once (as the atlas build does) and report failures."""
import json, collections
from pathlib import Path
from multiprocessing import Pool
from rdflib import Graph
from flopo2.saudi import build
from flopo2.owl import assertions as A
from flopo2.owl.annotation_class import ensure_annotation_class_iri
def scan(item):
    name, path = item
    attrs = A._load_attributes(Path("config/pato_lexicon.tsv"))
    graph, nodes = Graph(), A._Nodes(); A._declare_vocabulary(graph)
    seen = set(); errs = collections.Counter(); ex = []
    with open(path, encoding="utf-8") as h:
        for line in h:
            if not line.strip(): continue
            for a in json.loads(line).get("assertions", []) or []:
                if a.get("qualitative_value_relation") or not A.operands_fac_representable(a) or (
                    a.get("specimen_condition") or a.get("count_position") or a.get("maximum_at_least") or a.get("presence_variable")):
                    continue
                try:
                    iri = ensure_annotation_class_iri(a)
                    if iri in seen: continue
                    seen.add(iri)
                    A._phenotype_expression(graph, nodes, a, attrs)
                except Exception as e:
                    key = f"{type(e).__name__}: {str(e)[:90]}"; errs[key] += 1
                    if len(ex) < 3: ex.append((key, {k: v for k, v in a.items() if v not in (None, [], "", False) and k not in ("composition", "gate", "mapping_provenance")}))
            if len(graph) > 200000:
                graph = Graph(); A._declare_vocabulary(graph)
    return name, len(seen), errs, ex
if __name__ == "__main__":
    av = [k for k, v in build.SOURCES.items() if v["corpus"].exists()]
    unf = set(build._unfinished_flora_runs(av))
    items = [(k, str(build.RDF_DIR / f"{k}-corpus-tagged.jsonl" if k in unf else build.SOURCES[k]["corpus"])) for k in av]
    bad = 0
    with Pool(10) as p:
        for name, n, errs, ex in p.imap_unordered(scan, items):
            print(name, n, dict(errs), flush=True)
            for e in ex: print("   ", str(e)[:600], flush=True)
            bad += sum(errs.values())
    print("FAILURES", bad)
