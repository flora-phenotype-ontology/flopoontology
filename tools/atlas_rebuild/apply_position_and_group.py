"""Step of tools/atlas_rebuild/run.sh. Apply the bearer-position pass and the plant-group guard to every corpus the atlas reads, in place
(backup <file>.pre-position, kept if it exists already)."""
import json, sys, shutil, collections
from pathlib import Path
from flopo2.saudi import build
from flopo2.verify import apply_bearer_position as position, apply_plant_group as group
available = [k for k, v in build.SOURCES.items() if v["corpus"].exists()]
unfinished = set(build._unfinished_flora_runs(available))
words = position.load(); pattern = position._pattern(words); guard = group.Guard()
total = collections.Counter()
for name in available:
    path = build.SOURCES[name]["corpus"]
    if name in unfinished:
        path = build.RDF_DIR / f"{name}-corpus-tagged.jsonl"   # never the live corpus of a running flora
        if not path.exists(): continue
    c = collections.Counter()
    tmp = Path(str(path) + ".position-new")
    with path.open(encoding="utf-8") as src, tmp.open("w", encoding="utf-8") as dst:
        for line in src:
            record = json.loads(line)
            text, family = record.get("text", ""), record.get("taxon_family", "")
            for a in record.get("assertions", []):
                c["assertions"] += 1
                r = position.apply(a, text, words, pattern)
                if r: c["position_" + r] += 1
                if guard.apply(a, family): c["group_review"] += 1
            dst.write(json.dumps(record, ensure_ascii=False) + "\n")
    backup = Path(str(path) + ".pre-position")
    if not backup.exists(): shutil.copy2(path, backup)
    tmp.replace(path)
    total.update(c)
    print(json.dumps({"source": name, "file": str(path), **c}), flush=True)
print(json.dumps({"TOTAL": dict(total)}), flush=True); print("DONE", flush=True)
