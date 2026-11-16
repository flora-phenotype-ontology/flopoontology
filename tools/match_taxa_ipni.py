"""Match every printed taxon name of the atlas to WCVP/IPNI (flopo2.taxon.wcvp); write a TSV and counts."""

from __future__ import annotations

import collections
import csv
import json
import sys
from pathlib import Path

from flopo2.taxon.wcvp import Wcvp, as_row

CACHE = Path("local-corpora/saudi-flora/taxon-cache.json")
OUT = Path("local-corpora/wcvp/match/ipni-matches.tsv")


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    wcvp = Wcvp()
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    rows = []
    for name, v in cache.items():
        m = wcvp.match(name, verified=v.get("matched", ""), family=v.get("family", ""), wfo_accepted=v.get("accepted_name", ""))
        row = as_row(m)
        row.update(wfo_match=v.get("match_type", ""), wfo_accepted=v.get("accepted_wfo_id", ""), wfo_family=v.get("family", ""), wfo_order=v.get("order", ""))
        rows.append(row)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)
    ok = [r for r in rows if r["how"] not in ("none", "ambiguous")]
    print(collections.Counter(r["how"] for r in rows).most_common())
    print(f"matched {len(ok)} of {len(rows)}; accepted IPNI ID for {sum(1 for r in ok if r['accepted_ipni_id'])}")


if __name__ == "__main__":
    main()
