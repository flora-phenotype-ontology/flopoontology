"""Where the taxa of the atlas are recorded, by country: ``places.json`` for the Map page.

The place records of the floras (``fb:Occurrence`` with ``fb:locality``, in
``local-corpora/saudi-flora/rdf/*-places.nt``) name countries, states, provinces, regions and
single localities as text. A locality is counted for a country when it is

- a country name (``config/atlas_country_names.json``, the names of Natural Earth's 1:110m
  countries, public domain), a former name or a common short form (``ALIASES``);
- a state or province of the countries whose floras are in the atlas (``SUBDIVISIONS``), also
  with a compass word ("Northwest Yunnan") or as the first part of "Yunnan, China";
- a list of such names ("California, Oregon").

A place record with a coded region (``fb:region`` .../geo/region/SA-02, ISO 3166-2) counts for
that region's country, whatever its locality text ("Taif").

A taxon is also counted for the countries a regional flora covers (``FLORA_AREAS``): every taxon
that NCVC or Collenette describe is part of the flora of Saudi Arabia, every taxon of the Flora of
China grows in China. Worldwide and continental sources (WFO, Plazi, GrassBase, North American
Flora...) have no area. ``taxa`` is the union; ``taxa_flora`` and ``taxa_places`` give the parts.

Continents, mountain ranges, islands shared by countries and single localities without a
country stay uncounted and are listed under ``unmatched``.

    python -m tools.atlas_places [--rdf DIR] [-o places.json]
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

NAMES = Path("config/atlas_country_names.json")
# The countries each regional flora covers (ISO 3166-1 alpha-3, as in the map's country outlines).
FLORA_AREAS = {
    "ncvc": ["SAU"], "collenette": ["SAU"],
    "eflora-fna": ["USA", "CAN"], "eflora-foc": ["CHN"], "eflora-fop": ["PAK"], "eflora-fom": ["USA"],
    "eflora-mfoc": ["CHN"], "eflora-andes": ["ECU", "CHL"],
    "powo-fz": ["ZMB", "ZWE", "MWI", "MOZ", "BWA"], "powo-ftea": ["KEN", "TZA", "UGA"], "powo-fsom": ["SOM"],
    "powo-fwta": ["SEN", "GMB", "GNB", "GIN", "SLE", "LBR", "CIV", "MLI", "BFA", "GHA", "TGO", "BEN", "NER",
                  "NGA", "CMR", "TCD"],
    "powo-fiq": ["IRQ"], "powo-cayman": ["CYM"], "powo-tong": ["PNG", "IDN"],
    "flora-guianas": ["GUY", "SUR", "GUF"], "flora-malesiana": ["IDN", "MYS", "PHL", "PNG", "BRN", "TLS", "SGP"],
    "flora-gabon": ["GAB"], "fdac": ["COD", "RWA", "BDI"], "fdac-genera": ["COD", "RWA", "BDI"],
    "flora-zimbabwe": ["ZWE"], "illinois-wildflowers": ["USA"], "usda-plants": ["USA"], "feis-plants": ["USA"],
    "silvics-na": ["USA", "CAN"], "plants-tibet": ["CHN"], "korup-flora": ["CMR"],
}
REGION_COUNTRY = {"SA": "SAU"}  # ISO 3166-2 prefixes of the coded regions in the place records
RDF = Path("local-corpora/saudi-flora/rdf")
ALIASES = {
    "usa": "USA", "u.s.a.": "USA", "united states": "USA", "u.s.": "USA", "us": "USA", "korea": "KOR",
    "south korea": "KOR", "north korea": "PRK", "burma": "MMR", "zaire": "COD", "belgian congo": "COD",
    "congo (kinshasa)": "COD", "dr congo": "COD", "congo": "COG", "congo (brazzaville)": "COG", "tanganyika": "TZA",
    "rhodesia": "ZWE", "southern rhodesia": "ZWE", "northern rhodesia": "ZMB", "nyasaland": "MWI",
    "ceylon": "LKA", "siam": "THA", "persia": "IRN", "formosa": "TWN", "ivory coast": "CIV", "côte d'ivoire": "CIV",
    "cote d'ivoire": "CIV", "swaziland": "SWZ", "bechuanaland": "BWA", "south west africa": "NAM",
    "abyssinia": "ETH", "west pakistan": "PAK", "east pakistan": "BGD", "kashmir": "IND", "sikkim": "IND",
    "tibet": "CHN", "xizang": "CHN", "hong kong": "CHN", "england": "GBR", "scotland": "GBR", "wales": "GBR",
    "britain": "GBR", "great britain": "GBR", "uk": "GBR", "holland": "NLD", "russia": "RUS", "ussr": "RUS",
    "siberia": "RUS", "sumatra": "IDN", "java": "IDN", "sulawesi": "IDN", "celebes": "IDN", "moluccas": "IDN",
    "bali": "IDN", "luzon": "PHL", "mindanao": "PHL", "peninsular malaysia": "MYS", "malaya": "MYS",
    "sabah": "MYS", "sarawak": "MYS", "hawaii": "USA", "alaska": "USA", "puerto rico": "PRI", "cuba": "CUB",
    "jamaica": "JAM", "trinidad": "TTO", "tobago": "TTO", "guadeloupe": "FRA", "martinique": "FRA",
    "french guiana": "GUF", "reunion": "FRA", "tasmania": "AUS", "queensland": "AUS", "new south wales": "AUS",
    "victoria": "AUS", "western australia": "AUS", "south australia": "AUS", "northern territory": "AUS",
    "natal": "ZAF", "transvaal": "ZAF", "cape province": "ZAF", "zanzibar": "TZA", "socotra": "YEM",
    "sinai": "EGY", "sicily": "ITA", "sardinia": "ITA", "corsica": "FRA", "crete": "GRC", "bermuda": "GBR",
    "greenland": "GRL", "st. pierre and miquelon": "FRA", "newfoundland": "CAN", "labrador": "CAN",
}
# States and provinces of the countries whose floras are in the atlas, separated by "|".
SUBDIVISIONS = {
    "USA": "alabama|alaska|arizona|arkansas|california|colorado|connecticut|delaware|florida|georgia|hawaii|idaho|"
           "illinois|indiana|iowa|kansas|kentucky|louisiana|maine|maryland|massachusetts|michigan|minnesota|"
           "mississippi|missouri|montana|nebraska|nevada|new hampshire|new jersey|new mexico|new york|"
           "north carolina|north dakota|ohio|oklahoma|oregon|pennsylvania|rhode island|south carolina|"
           "south dakota|tennessee|texas|utah|vermont|virginia|washington|west virginia|wisconsin|wyoming|"
           "district of columbia|carolina",
    "CAN": "alberta|british columbia|manitoba|new brunswick|newfoundland and labrador|nova scotia|ontario|"
           "prince edward island|quebec|québec|saskatchewan|yukon|northwest territories|nunavut",
    "CHN": "anhui|beijing|chongqing|fujian|gansu|guangdong|guangxi|guizhou|hainan|hebei|heilongjiang|henan|hubei|"
           "hunan|inner mongolia|nei mongol|jiangsu|jiangxi|jilin|liaoning|ningxia|qinghai|shaanxi|shandong|"
           "shanghai|shanxi|sichuan|tianjin|xinjiang|yunnan|zhejiang",
    "MEX": "aguascalientes|baja california|baja california sur|campeche|chiapas|chihuahua|coahuila|colima|durango|"
           "guanajuato|guerrero|hidalgo|jalisco|michoacán|michoacan|morelos|nayarit|nuevo león|nuevo leon|oaxaca|"
           "puebla|querétaro|queretaro|quintana roo|san luis potosí|san luis potosi|sinaloa|sonora|tabasco|"
           "tamaulipas|tlaxcala|veracruz|yucatán|yucatan|zacatecas",
    "IND": "assam|arunachal pradesh|bihar|goa|gujarat|haryana|himachal pradesh|karnataka|kerala|madhya pradesh|"
           "maharashtra|manipur|meghalaya|mizoram|nagaland|odisha|orissa|rajasthan|tamil nadu|tripura|"
           "uttar pradesh|uttarakhand|west bengal|andaman islands|nicobar islands|ladakh",
    "PAK": "balochistan|baluchistan|sindh|sind|north-west frontier province|chitral|gilgit|hazara|swat|"
           "khyber pakhtunkhwa",
    "SAU": "asir|hejaz|hijaz|najd|nejd|eastern province|jiddah|jeddah|abha|taif|riyadh",
    "BRA": "amazonas|bahia|minas gerais|pará|rio de janeiro|são paulo|sao paulo|mato grosso|paraná|santa catarina",
}
_COMPASS = re.compile(
    r"^(?:(?:north|south|east|west|central|upper|lower|coastal|interior|tropical|temperate)(?:ern|-central)?"
    r"(?:\s*(?:north|south|east|west)(?:ern)?)?|n|s|e|w|ne|nw|se|sw|c)\.?\s+", re.IGNORECASE)


def gazetteer() -> dict[str, str]:
    names = {k.lower(): v for k, v in json.loads(NAMES.read_text(encoding="utf-8")).items()}
    for country, text in SUBDIVISIONS.items():
        for name in text.split("|"):
            names.setdefault(name.strip(), country)
    names.update(ALIASES)
    return names


def countries_of(locality: str, names: dict[str, str]) -> set[str]:
    """The countries a locality text names; empty when it names none or is wider than a country."""

    found: set[str] = set()
    text = re.sub(r"\s*\([^)]*\)", "", locality).strip().lower()
    parts = [p.strip() for p in re.split(r"\s*(?:,|;|/|\band\b|&)\s*", text) if p.strip()]
    for index, part in enumerate(parts):
        for name in (part, _COMPASS.sub("", part)):
            if name in names:
                found.add(names[name])
                break
        else:
            if index == 0 and len(parts) > 1:
                continue  # "Emei Shan, Sichuan": the later part decides
    return found


def aggregate(rdf: Path = RDF) -> dict:
    names = gazetteer()
    source_label = {}
    taxa: dict[str, set] = defaultdict(set)
    records: Counter = Counter()
    by_source: dict[str, Counter] = defaultdict(Counter)
    localities: dict[str, Counter] = defaultdict(Counter)
    unmatched: Counter = Counter()
    total = matched = 0
    line_re = re.compile(r'^<([^>]+)> <[^>]*browse#(taxon|locality|source|region)> (?:<([^>]+)>|"((?:[^"\\]|\\.)*)")')
    for path in sorted(rdf.glob("*-places.n[tq]")):
        # the lines of one record need not be adjacent, so collect each record's fields first
        fields: dict[str, dict[str, str]] = defaultdict(dict)
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                m = line_re.match(line)
                if not m:
                    continue
                value = m.group(3) if m.group(3) is not None else (m.group(4) or "")
                if m.group(2) == "locality" and "\\u" in value:
                    value = value.encode().decode("unicode_escape", "ignore")
                fields[m.group(1)][m.group(2)] = value
        for record in fields.values():
            locality, region = record.get("locality", ""), record.get("region", "")
            taxon, source = record.get("taxon", ""), record.get("source", "")
            if not locality and not region:
                continue
            total += 1
            hits = countries_of(locality, names) if locality else set()
            code = region.rsplit("/", 1)[-1].split("-")[0]
            if code in REGION_COUNTRY:
                hits.add(REGION_COUNTRY[code])
            if not hits:
                unmatched[locality] += 1
                continue
            matched += 1
            for a3 in hits:
                if taxon:
                    taxa[a3].add(taxon)
                records[a3] += 1
                by_source[a3][source.rsplit("/", 1)[-1]] += 1
                localities[a3][locality or region.rsplit("/", 1)[-1]] += 1
    flora_taxa: dict[str, set] = defaultdict(set)
    flora_sources: dict[str, Counter] = defaultdict(Counter)
    name_re = re.compile(r"^<[^>]*/taxon-name/(.+)/([^/]+)/[0-9a-f]+> <[^>]*browse#source> ")
    base = "http://phenomebrowser.net/flopo/taxon/"
    # printed names, taxon-name/<taxon key>/<source>/<digest> fb:source <...>: taxa.nt, or NN-taxa.nq in a release
    for taxa_file in [*rdf.glob("taxa.nt"), *rdf.glob("*-taxa.nq")]:
        with taxa_file.open(encoding="utf-8") as handle:
            for line in handle:
                m = name_re.match(line)
                if m and m.group(2) in FLORA_AREAS:
                    for a3 in FLORA_AREAS[m.group(2)]:
                        if base + m.group(1) not in flora_taxa[a3]:
                            flora_taxa[a3].add(base + m.group(1))
                            flora_sources[a3][m.group(2)] += 1
    country_taxa = {a3: taxa[a3] | flora_taxa[a3] for a3 in set(taxa) | set(flora_taxa)}
    return {
        "records": total, "matched": matched, "_taxa": country_taxa,
        "countries": {
            a3: {"taxa": len(taxa[a3] | flora_taxa[a3]), "taxa_places": len(taxa[a3]), "taxa_flora": len(flora_taxa[a3]),
                 "floras": dict(flora_sources[a3].most_common()),
                 "records": records[a3], "sources": dict(by_source[a3].most_common()),
                 "localities": [name for name, _ in localities[a3].most_common(60)]}
            for a3 in sorted(set(taxa) | set(flora_taxa))
        },
        "unmatched": [[name, count] for name, count in unmatched.most_common(40)],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--rdf", type=Path, default=RDF)
    parser.add_argument("-o", "--output", type=Path, default=Path("local-corpora/saudi-flora/places.json"))
    args = parser.parse_args()
    result = aggregate(args.rdf)
    result.pop("_taxa")
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    top = sorted(result["countries"].items(), key=lambda kv: -kv[1]["taxa"])[:12]
    print(f"{result['matched']} of {result['records']} place records in {len(result['countries'])} countries")
    print(", ".join(f"{a3} {v['taxa']}" for a3, v in top))
    print("not placed:", ", ".join(f"{n} ({c})" for n, c in result["unmatched"][:25]))


if __name__ == "__main__":
    main()
