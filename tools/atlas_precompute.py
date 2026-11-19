"""Answer the atlas's site-wide summary queries once per release and store them as static files.

The overview table, the plant-part counts of the Traits page and the value list of the Identify
page count over every trait record (3-7 s each) and change only with a release. The queries are
in ``web/saudi/precomputed-queries.json``; the page loads ``precomputed/<name>.json`` and falls
back to the query when the file is missing. ``tools/deploy_atlas.sh`` runs this against the
staged endpoint.

    python -m tools.atlas_precompute ENDPOINT WEB_DIR
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path


def main() -> None:
    endpoint, web = sys.argv[1], Path(sys.argv[2])
    queries = json.loads((web / "precomputed-queries.json").read_text(encoding="utf-8"))
    out = web / "precomputed"
    out.mkdir(exist_ok=True)
    for name, query in queries.items():
        started = time.time()
        request = urllib.request.Request(
            endpoint + "?" + urllib.parse.urlencode({"query": query}), headers={"Accept": "application/sparql-results+json"}
        )
        with urllib.request.urlopen(request, timeout=600) as response:
            bindings = json.loads(response.read())["results"]["bindings"]
        rows = [{k: v["value"] for k, v in b.items()} for b in bindings]
        (out / f"{name}.json").write_text(json.dumps(rows, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"precomputed {name}: {len(rows)} rows in {time.time() - started:.1f}s")


if __name__ == "__main__":
    main()
