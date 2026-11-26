"""Static taxon index of an atlas release: ``taxa.json`` for the Taxa page, ``country-taxa.json`` for the Map.

The Taxa page used to ask the endpoint for every taxon, its record count, its sources and its
vernacular names (four queries, about 50 MB) and drew all 110,000 names at once. This index is
built once per release from the RDF files and is small enough to load at once and filter in
the browser:

    {"sources": [source key, ...], "families": [family, ...],
     "taxa": [[key, label, authorship, family index, trait records, [source index, ...], vernacular, printed names], ...]}

``key`` is the taxon IRI without ``http://phenomebrowser.net/flopo/taxon/`` ("ipni-822006-1").
``printed names`` are the names that floras print for the taxon and that differ from the accepted name
(Acacia tortilis for Vachellia tortilis), reduced to genus, species and infraspecific epithets and joined
with "|"; the Taxa page and the search of the overview find a taxon by them. Taxa are ordered by name
without leading punctuation ('Lithospermum' under L).
``country-taxa.json`` maps each country (ISO alpha-3) to the positions of its taxa in ``taxa``.

    python -m tools.atlas_taxa_index RDF_DIR OUT_DIR
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

TAXON = "http://phenomebrowser.net/flopo/taxon/"
B = "http://phenomebrowser.net/flopo/browse#"
TRIPLE = re.compile(r'^<([^>]+)> <([^>]+)> (?:<([^>]+)>|"((?:[^"\\]|\\.)*)"(?:@([\w-]+)|\^\^<[^>]+>)?)')


def _text(raw: str) -> str:
    return json.loads(f'"{raw}"') if "\\" in raw else raw


RANKS = {"subsp.", "ssp.", "var.", "subvar.", "f.", "subf.", "forma"}


def printed_binomial(printed: str) -> str:
    """Genus, species and infraspecific epithets of a printed name, without the authors."""
    kept: list[str] = []
    for i, token in enumerate(printed.replace("\u00d7", " \u00d7 ").split()):
        if i == 0 or token == "\u00d7" or token in RANKS or re.fullmatch(r"[a-z][a-z-]+", token):
            kept.append(token)
        else:
            break
    while kept and (kept[-1] in RANKS or kept[-1] == "\u00d7"):
        kept.pop()
    return " ".join(kept)


def sort_key(label: str, key: str) -> tuple[str, str, str]:
    return (re.sub(r"^[\W_]+", "", label).lower(), label.lower(), key)


def build(rdf: Path) -> tuple[dict, dict[str, int]]:
    label, auth, family, vernacular = {}, {}, {}, defaultdict(list)
    printed: dict[str, set] = defaultdict(set)
    typed: set[str] = set()  # habitat and abundance notes also have IRIs under taxon/ and a label
    sources: dict[str, set] = defaultdict(set)
    for path in [*rdf.glob("taxa.nt"), *rdf.glob("*-taxa.nq")]:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                m = TRIPLE.match(line)
                if not m:
                    continue
                s, p, o, lit = m.group(1), m.group(2), m.group(3), m.group(4)
                if s.startswith(TAXON):
                    key = s[len(TAXON):]
                    if p.endswith("22-rdf-syntax-ns#type") and o == B + "Taxon":
                        typed.add(key)
                    elif p.endswith("rdf-schema#label"):
                        label[key] = _text(lit or "")
                    elif p == B + "authorship":
                        auth[key] = _text(lit or "")
                    elif p == B + "family":
                        family[key] = _text(lit or "")
                    elif p == B + "vernacularName":
                        vernacular[key].append(_text(lit or ""))
                elif "/taxon-name/" in s and p == B + "source" and o:
                    key = s.split("/taxon-name/", 1)[1].rsplit("/", 2)[0]
                    sources[key].add(o.rsplit("/", 1)[-1])
                elif "/taxon-name/" in s and p == B + "name" and lit:
                    printed[s.split("/taxon-name/", 1)[1].rsplit("/", 2)[0]].add(_text(lit))
    records: Counter = Counter()
    for path in [*rdf.glob("*-index.nt"), *rdf.glob("*-index.nq")]:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("<http://phenomebrowser.net/flopo/flora-assertion/") and f"<{B}taxon> <{TAXON}" in line:
                    records[line.split(f"<{B}taxon> <{TAXON}", 1)[1].split(">", 1)[0]] += 1
    source_keys = sorted({s for v in sources.values() for s in v})
    source_pos = {s: i for i, s in enumerate(source_keys)}
    families = sorted({f for f in family.values() if f})
    family_pos = {f: i for i, f in enumerate(families)}
    keys = sorted((k for k in label if k in typed), key=lambda k: sort_key(label[k], k))

    def synonyms(k: str) -> str:
        own = label[k].lower()
        names = {printed_binomial(x).replace("|", " ") for x in printed.get(k, ())}
        return "|".join(sorted(x for x in names if len(x.split()) > 1 and x.lower() != own and not own.startswith(x.lower() + " ")))

    taxa = [
        [k, label[k], auth.get(k, ""), family_pos.get(family.get(k, ""), -1), records.get(k, 0),
         sorted(source_pos[s] for s in sources.get(k, ())), " ".join(vernacular.get(k, [])), synonyms(k)]
        for k in keys
    ]
    return {"sources": source_keys, "families": families, "taxa": taxa}, {k: i for i, k in enumerate(keys)}


def write(rdf: Path, web: Path, country_taxa: dict[str, set] | None = None) -> None:
    index, position = build(rdf)
    (web / "taxa.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    if country_taxa is not None:
        by_country = {
            a3: sorted(position[t[len(TAXON):]] for t in members if t.startswith(TAXON) and t[len(TAXON):] in position)
            for a3, members in country_taxa.items()
        }
        (web / "country-taxa.json").write_text(json.dumps(by_country, separators=(",", ":")), encoding="utf-8")


def main() -> None:
    from tools.atlas_places import aggregate

    rdf, out = Path(sys.argv[1]), Path(sys.argv[2])
    write(rdf, out, aggregate(rdf).pop("_taxa"))
    print(f"wrote {out / 'taxa.json'} ({(out / 'taxa.json').stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
