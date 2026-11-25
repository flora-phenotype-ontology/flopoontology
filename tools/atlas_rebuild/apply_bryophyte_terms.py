"""Step of tools/atlas_rebuild/run.sh. Apply the bryophyte-terms pass to every corpus the atlas reads, in place (backup <file>.pre-moss)."""
import json, shutil, collections
from pathlib import Path
from flopo2.saudi import build
from flopo2.verify import apply_bryophyte_terms as bryophyte
available = [k for k, v in build.SOURCES.items() if v["corpus"].exists()]
unfinished = set(build._unfinished_flora_runs(available))
terms = bryophyte.Terms(); total = collections.Counter()
for name in available:
    path = build.SOURCES[name]["corpus"]
    if name in unfinished:
        path = build.RDF_DIR / f"{name}-corpus-tagged.jsonl"   # never the live corpus of a running flora
        if not path.exists(): continue
    c = collections.Counter(); tmp = Path(str(path) + ".moss-new")
    with path.open(encoding="utf-8") as src, tmp.open("w", encoding="utf-8") as dst:
        for line in src:
            record = json.loads(line); changed = False
            if not bryophyte.misfiled(name, record):
                family, text = record.get("taxon_family", ""), record.get("text", "")
                if bryophyte.is_bryophyte(family, text):
                    c["descriptions"] += 1
                    for a in record.get("assertions", []):
                        r = terms.apply(a, family, text)
                        if r: c[r] += 1; changed = True
            else:
                c["misfiled"] += 1
            dst.write(json.dumps(record, ensure_ascii=False) + "\n" if changed else line)
    if c["replaced"] or c["review"]:
        backup = Path(str(path) + ".pre-moss")
        if not backup.exists(): shutil.copy2(path, backup)
        tmp.replace(path)
    else:
        tmp.unlink()
    total.update(c); print(json.dumps({"source": name, **c}), flush=True)
print(json.dumps({"TOTAL": dict(total)}), flush=True); print("DONE", flush=True)
