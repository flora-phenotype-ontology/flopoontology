"""Freeze atlas profiles and collect a licensed, provenance-rich development audit.

This creates no gold labels or claimed test set. API responses and image hashes are retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

from flopo2.saudi.inaturalist import API, file_hash, write_json
from flopo2.vision.logic import Compiler, UnsupportedExpression

FB = "http://phenomebrowser.net/flopo/browse#"
ALLOWED_LICENSES = {"cc0", "cc-by", "cc-by-sa"}
ORGANS = {"leaf", "petal", "fruit"}


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_jsonl(path, rows):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    temp.replace(path)


def freeze(release: Path, out: Path, taxon_limit: int = 40, diverse_only: bool = True):
    import pyoxigraph as ox
    meta = json.loads((release / "release.json").read_text())
    catalogue = json.loads((release / "web/inaturalist.json").read_text())
    if file_hash(release / "web/inaturalist.json") != meta["inaturalist_sha256"]:
        raise ValueError("Crosswalk does not match the frozen release")
    store = ox.Store()
    for graph in meta["graphs"]:
        path = release / graph["file"]
        if file_hash(path) != graph["sha256"]:
            raise ValueError(f"Changed release graph: {path}")
        store.bulk_load(path=str(path), format=ox.RdfFormat.N_QUADS)
    query = '''PREFIX fb: <http://phenomebrowser.net/flopo/browse#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?r ?t ?b ?bl ?q ?ql ?status ?text ?src ?pc ?attribute ?qualifier ?family WHERE {
?r a fb:TraitRecord; fb:taxon ?t; fb:bearer ?b; fb:quality ?q;
   fb:negated false; fb:status ?status; fb:text ?text; fb:source ?src.
?b rdfs:label ?bl. ?q rdfs:label ?ql.
FILTER(STR(?bl) IN ("leaf", "petal", "fruit"))
OPTIONAL { ?r fb:phenotypeClass ?pc }
OPTIONAL { ?r fb:attribute ?attribute }
OPTIONAL { ?r fb:qualifier ?qualifier }
OPTIONAL { ?t fb:family ?family }
}'''
    result = store.query(query, use_default_graph_as_union=True)
    variables = [v.value for v in result.variables]
    profiles = defaultdict(list)
    for row in result:
        d = {k: v.value for k, v in zip(variables, row) if v is not None}
        profiles[d["t"]].append(d)
    candidates = []
    for taxon, records in profiles.items():
        entry = catalogue["taxa"].get(taxon, {})
        if entry.get("status") != "matched" or entry.get("rank") != "species" or taxon.rsplit("/", 1)[-1].startswith("bare-name"):
            continue
        accepted = [r for r in records if r["status"] == "accepted"]
        if len(accepted) < 3 or entry.get("observations_count", 0) < 50:
            continue
        candidates.append({"taxon": taxon, "name": entry["name"], "inat_id": entry["id"],
            "inat_name": entry["inat_name"], "genus": entry["inat_name"].split()[0],
            "family": records[0].get("family", "unknown"), "records": accepted,
            "organs": sorted({r["bl"] for r in accepted}),
            "matching_method": entry.get("method", "verified_crosswalk")})
    candidates.sort(key=lambda t: (-len(t["organs"]), -min(len(t["records"]), 30), hashlib.sha256(t["taxon"].encode()).hexdigest()))
    selected, genera, families = [], set(), Counter()
    for taxon in candidates:
        if diverse_only and (taxon["genus"] in genera or families[taxon["family"]] >= 4):
            continue
        selected.append(taxon); genera.add(taxon["genus"]); families[taxon["family"]] += 1
        if len(selected) == taxon_limit:
            break
    compiler, compiled, rejected = Compiler(store), {}, {}
    iris = sorted({r["pc"] for t in selected for r in t["records"] if r.get("pc")})
    for iri in iris:
        try:
            compiled[iri] = compiler.compile(iri).json()
        except UnsupportedExpression as exc:
            rejected[iri] = str(exc)
    classes = {r[key] for t in selected for r in t["records"] for key in ("b", "q")}
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "profiles.json", selected)
    write_json(out / "queries.json", {"supported": compiled, "unsupported": rejected,
                                      "ancestors": compiler.ancestors(classes)})
    summary = {"release": meta["stamp"], "release_metadata_sha256": file_hash(release / "release.json"),
        "crosswalk_sha256": meta["inaturalist_sha256"], "graphs": meta["graphs"],
        "created": datetime.now(timezone.utc).isoformat(), "eligible_taxa": len(candidates),
        "selected_taxa": len(selected), "genera": len(genera), "families": dict(families),
        "supported_queries": len(compiled), "unsupported_queries": len(rejected),
        "status": "development_audit_unreviewed", "selection": "one species per genus; max four per family; prefer multiple organs; deterministic hash tie-break" if diverse_only else "all eligible species up to limit; prefer multiple organs; deterministic hash tie-break"}
    write_json(out / "audit.json", summary)
    print(json.dumps({k: summary[k] for k in ("eligible_taxa", "selected_taxa", "genera", "supported_queries", "unsupported_queries")}))


def observation_rows(record: dict, profile: dict, max_photos: int) -> list[dict]:
    if record.get("quality_grade") != "research" or record.get("taxon", {}).get("id") != profile["inat_id"]:
        return []
    rows = []
    for photo in record.get("photos", []):
        if photo.get("license_code") not in ALLOWED_LICENSES:
            continue
        url = photo.get("url", "").replace("/square.", "/large.")
        if not url.startswith("https://"):
            continue
        rows.append({"observation_id": record["id"], "photo_id": photo["id"], "image_url": url,
            "observation_url": f"https://www.inaturalist.org/observations/{record['id']}",
            "photo_url": f"https://www.inaturalist.org/photos/{photo['id']}",
            "license": photo["license_code"], "attribution": photo.get("attribution", ""),
            "observer_id": record.get("user", {}).get("id"), "observed_on": record.get("observed_on"),
            "created_at": record.get("created_at"), "taxon": profile["taxon"], "inat_id": profile["inat_id"],
            "name": profile["name"], "genus": profile["genus"], "family": profile["family"],
            "quality_grade": "research", "split": "development_audit", "review_status": "unreviewed"})
        if len(rows) >= max_photos:
            break
    return rows


def download(row: dict, out: Path) -> dict:
    from PIL import Image, ImageOps
    path = out / "images" / f"{row['photo_id']}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        req = urllib.request.Request(row["image_url"], headers={"User-Agent": "FLOPO-Visual-Pilot/0.1"})
        with urllib.request.urlopen(req, timeout=60) as response:
            data = response.read(30_000_001)
        if len(data) > 30_000_000:
            raise ValueError("Image exceeds 30 MB")
        temp = path.with_suffix(".download")
        temp.write_bytes(data)
        with Image.open(temp) as im:
            im.verify()
        temp.replace(path)
    with Image.open(path) as image:
        im = ImageOps.exif_transpose(image)
        width, height = im.size
        pixels = list(im.convert("L").resize((9, 8)).getdata())
        bits = sum(int(pixels[y * 9 + x] > pixels[y * 9 + x + 1]) << (y * 8 + x) for y in range(8) for x in range(8))
    return {**row, "image_path": str(path.relative_to(out)), "sha256": file_hash(path),
            "dhash": f"{bits:016x}", "width": width, "height": height,
            "retrieved": datetime.now(timezone.utc).isoformat()}


def collect(out: Path, per_taxon: int = 5, max_photos: int = 3, target_observations: int | None = None):
    profiles = json.loads((out / "profiles.json").read_text())
    api = API(out / "api-cache")
    rows, shortfalls, total = [], [], 0
    for i, profile in enumerate(profiles):
        response = api.get("observations", taxon_id=profile["inat_id"], quality_grade="research",
            photos="true", photo_license=",".join(sorted(ALLOWED_LICENSES)), captive="false",
            d1="2026-01-01", per_page=100, order_by="id", order="desc")
        taken, observers = 0, set()
        # Deterministic sampling within the retrieved recent pool, not a global random sample.
        pool = sorted(response.get("results", []), key=lambda r: hashlib.sha256(str(r["id"]).encode()).hexdigest())
        for record in pool:
            observer = record.get("user", {}).get("id")
            if observer in observers:
                continue
            photos = observation_rows(record, profile, max_photos)
            if photos:
                rows.extend(photos); taken += 1; total += 1; observers.add(observer)
            if taken >= per_taxon or (target_observations and total >= target_observations):
                break
        if taken < per_taxon:
            shortfalls.append({"taxon": profile["name"], "observations": taken})
        print(f"Collected metadata {i + 1}/{len(profiles)}: {taken} observations", flush=True)
        if target_observations and total >= target_observations:
            break
    # One photo may be attached to several observations; retain provenance but download once.
    write_jsonl(out / "planned-images.jsonl", rows)
    unique = {}
    for row in rows:
        unique.setdefault(row["photo_id"], row)
    downloaded, errors = {}, []
    def fetch(row):
        try:
            return row["photo_id"], download(row, out), None
        except Exception as exc:
            return row["photo_id"], None, str(exc)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for index, (photo_id, record, error) in enumerate(pool.map(fetch, unique.values()), 1):
            if record:
                downloaded[photo_id] = record
            else:
                errors.append({"photo_id": photo_id, "error": error})
            if index % 100 == 0:
                print(f"Downloaded {len(downloaded)}/{len(unique)} images; {len(errors)} errors", flush=True)
    completed = [{**downloaded[r["photo_id"]], **r} for r in rows if r["photo_id"] in downloaded]
    write_jsonl(out / "images.jsonl", completed)
    pairs = []
    records = list(downloaded.values())
    for i, a in enumerate(records):
        for b in records[:i]:
            distance = (int(a["dhash"], 16) ^ int(b["dhash"], 16)).bit_count()
            if a["sha256"] == b["sha256"] or distance <= 3:
                pairs.append({"photo_ids": [a["photo_id"], b["photo_id"]], "exact": a["sha256"] == b["sha256"], "dhash_distance": distance})
    write_json(out / "collection.json", {"observations": len({r["observation_id"] for r in completed}),
        "images": len(downloaded), "taxa": len({r["taxon"] for r in completed}), "shortfalls": shortfalls,
        "download_errors": errors, "duplicate_candidates": pairs, "licenses": dict(Counter(r["license"] for r in downloaded.values())),
        "sampling": f"up to {per_taxon} distinct observers per species from a recent, licensed research-grade pool; observed since 2026-01-01",
        "target_observations": target_observations,
        "status": "unreviewed development collection; not independent gold labels"})
    print(f"Downloaded {len(downloaded)} images from {len({r['observation_id'] for r in completed})} observations")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["freeze", "collect"])
    parser.add_argument("--release", type=Path)
    parser.add_argument("--out", type=Path, default=Path("local-corpora/visual-pilot"))
    parser.add_argument("--taxa", type=int, default=40)
    parser.add_argument("--observations", type=int, help="Stop collecting once this development-observation target is reached")
    parser.add_argument("--per-taxon", type=int, default=5)
    args = parser.parse_args()
    if args.command == "freeze":
        if args.release is None:
            parser.error("freeze requires --release")
        freeze(args.release, args.out, args.taxa)
    else:
        if args.observations is not None and args.observations < 1:
            parser.error("--observations must be positive")
        if args.per_taxon < 1:
            parser.error("--per-taxon must be positive")
        collect(args.out, per_taxon=args.per_taxon, target_observations=args.observations)


if __name__ == "__main__":
    main()
