"""Step of tools/atlas_rebuild/run.sh. The ELK check (phene form, bearer axioms) on every atlas source, smallest first.
A source whose full run is unfinished is checked on the snapshot the atlas build reads."""
import json, sys, time
from pathlib import Path
from flopo2.saudi import build
from flopo2.verify import annotation_class_check as acc
available = [k for k, v in build.SOURCES.items() if v["corpus"].exists()]
unfinished = set(build._unfinished_flora_runs(available))
todo = []
for name in available:
    corpus = build.SOURCES[name]["corpus"]
    if name in unfinished:
        corpus = build.RDF_DIR / f"{name}-corpus-tagged.jsonl"
        if not corpus.exists():
            continue
    todo.append((name, corpus))
todo.sort(key=lambda x: x[1].stat().st_size)
done = set()
log = Path(sys.argv[1])
if log.exists():
    for line in log.read_text().splitlines():
        if line.startswith("{"):
            row = json.loads(line)
            if row.get("unsatisfiable") is not None and row.get("taxon_contradictions") is not None:
                done.add(row["source"])
with log.open("a") as out:
    for name, corpus in todo:
        if name in done:
            continue
        for attempt in range(4):
            start = time.time()
            result = acc.check(name, corpus, corpus.parent)
            result["seconds"] = round(time.time() - start)
            result["corpus"] = str(corpus)
            if result.get("unsatisfiable") is not None and result.get("taxon_contradictions") is not None:
                break
            time.sleep(300)  # memory: wait and try again
        out.write(json.dumps(result) + "\n"); out.flush()
    out.write("DONE\n")
