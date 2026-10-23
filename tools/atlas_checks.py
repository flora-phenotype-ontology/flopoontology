"""Checks for deploying the Saudi Flora Trait Atlas (see docs/atlas-deploy.md).

    python -m tools.atlas_checks preflight RELEASE [--previous RELEASE]
    python -m tools.atlas_checks crawl BASE_URL --out queries.jsonl
    python -m tools.atlas_checks parity RELEASE --qlever URL --queries queries.jsonl
    python -m tools.atlas_checks smoke BASE_URL --release RELEASE

Every check prints one line and is appended to ``RELEASE/checks.json`` (or ``--report``); the
command exits 1 when a check fails. Warnings do not stop a deployment.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
import types
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DATA_NS = "http://phenomebrowser.net/flopo/"
FLOPO_GRAPH = "http://phenomebrowser.net/flopo/saudi-flora/graph/flopo"
FB = "http://phenomebrowser.net/flopo/browse#"
OBO = "http://purl.obolibrary.org/obo/"
VALUE_TERMS = Path("config/flopo_flora_value_terms.tsv")
FORBIDDEN_IRI = re.compile(r"w3id\.org/flopo|^file:|//localhost[:/]|//127\.0\.0\.1[:/]")
FORBIDDEN_LITERAL = re.compile(r"/home/leechuck|/mnt/data2|api-key|Bearer [A-Za-z0-9]|unimatrix")
OWL_NODES = ["owl#intersectionOf", "owl#unionOf", "owl#complementOf", "owl#someValuesFrom",
             "owl#onClass", "owl#withRestrictions", "owl#equivalentClass", "22-rdf-syntax-ns#first"]


class Report:
    def __init__(self, path: Path | None, stage: str):
        self.path, self.stage, self.results = path, stage, []

    def add(self, cid: str, name: str, status: str, detail: str = "") -> None:
        self.results.append({"id": cid, "name": name, "status": status, "detail": detail})
        print(f"{status.upper():4} {cid} {name}: {detail}", file=sys.stderr)

    def check(self, cid: str, name: str, ok: bool, detail: str = "", warn: bool = False) -> None:
        self.add(cid, name, "pass" if ok else ("warn" if warn else "fail"), detail)

    def finish(self) -> int:
        if self.path:
            log = json.loads(self.path.read_text()) if self.path.exists() else []
            log.append({"stage": self.stage, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "results": self.results})
            self.path.write_text(json.dumps(log, indent=1) + "\n")
        failed = [r["id"] for r in self.results if r["status"] == "fail"]
        print(f"{self.stage}: {len(self.results) - len(failed)} passed or warned, {len(failed)} failed "
              f"{' '.join(failed)}", file=sys.stderr)
        return 1 if failed else 0


def _meta(release: Path) -> dict:
    return json.loads((release / "release.json").read_text())


# ------------------------------------------------------------------------- HTTP

def http(url: str, data: bytes | None = None, headers: dict | None = None, method: str | None = None,
         timeout: float = 120):
    """(status, headers, body, seconds); never raises on HTTP errors and never follows redirects."""

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None

    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    started = time.time()
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            return response.status, response.headers, response.read(), time.time() - started
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers, exc.read(), time.time() - started


def select(endpoint: str, query: str, timeout: float = 120) -> tuple[dict, float]:
    data = urllib.parse.urlencode({"query": query}).encode()
    status, _h, body, seconds = http(endpoint, data, {"Accept": "application/sparql-results+json",
                                                      "Content-Type": "application/x-www-form-urlencoded"},
                                     timeout=timeout)
    if status != 200:
        raise RuntimeError(f"HTTP {status}: {body[:300].decode(errors='replace')}")
    return json.loads(body), seconds


def rows(result: dict) -> list[dict[str, str]]:
    return [{k: v["value"] for k, v in b.items()} for b in result.get("results", {}).get("bindings", [])]


# -------------------------------------------------------------------- preflight

def preflight(release: Path, previous: Path | None, report: Report) -> None:
    meta = _meta(release)
    from tools.atlas_release import _sha256

    bad_hash = [g["file"] for g in meta["graphs"] if _sha256(release / g["file"]) != g["sha256"]]
    report.check("C3a", "files match release.json", not bad_hash, ", ".join(bad_hash) or f"{len(meta['graphs'])} graphs")

    iri = re.compile(r"<([^>]*)>")
    literal = re.compile(r'"((?:[^"\\]|\\.)*)"')
    counts, foreign, forbidden, secrets = {}, Counter(), Counter(), Counter()
    flopo_used: set[str] = set()
    declared: set[str] = set()
    deprecated: set[str] = set()
    status: dict[str, str] = {}
    for graph in meta["graphs"]:
        n = 0
        is_flopo = graph["graph"] == FLOPO_GRAPH
        with (release / graph["file"]).open(encoding="utf-8") as handle:
            for line in handle:
                n += 1
                terms = iri.findall(line)
                for term in terms:
                    if FORBIDDEN_IRI.search(term):
                        forbidden[term] += 1
                    if not is_flopo and term.startswith("http://phenomebrowser.net/") and not term.startswith(DATA_NS):
                        foreign[term.split("#")[0][:60]] += 1
                    if not is_flopo and term.startswith(OBO + "FLOPO_"):
                        flopo_used.add(term)
                if not is_flopo:
                    for text in literal.findall(line):
                        if FORBIDDEN_LITERAL.search(text):
                            secrets[text[:60]] += 1
                elif len(terms) >= 3 and terms[0].startswith(OBO + "FLOPO_"):
                    s, p, o = terms[0], terms[1], terms[2]
                    if p.endswith("22-rdf-syntax-ns#type") and o.endswith("owl#Class"):
                        declared.add(s)
                    elif p.endswith("IAO_0000114"):
                        status[s] = o
                    elif p.endswith("owl#deprecated") and '"true"' in line:
                        deprecated.add(s)
        counts[graph["graph"]] = n
    drift = [g["graph"] for g in meta["graphs"] if counts[g["graph"]] != g["triples"]]
    report.check("C3b", "every graph parses with its recorded triple count", not drift,
                 ", ".join(drift) or f"{meta['triples']} triples")
    report.check("C4a", "data IRIs under http://phenomebrowser.net/flopo/", not foreign,
                 "; ".join(f"{k} ({v})" for k, v in foreign.most_common(5)))
    report.check("C4b", "no w3id, file: or localhost IRIs", not forbidden,
                 "; ".join(f"{k} ({v})" for k, v in forbidden.most_common(5)))
    report.check("C2", "no local paths or secrets in literals", not secrets,
                 "; ".join(f"{k} ({v})" for k, v in secrets.most_common(5)))
    dangling = sorted(flopo_used - declared)
    report.check("C4c", "every FLOPO class used by the data is in the ontology", not dangling,
                 " ".join(dangling[:10]) or f"{len(flopo_used)} classes")
    used_obsolete = sorted(flopo_used & deprecated)
    report.check("C4d", "data uses no obsolete FLOPO class", not used_obsolete,
                 " ".join(used_obsolete[:10]) or "none", warn=True)

    with VALUE_TERMS.open(encoding="utf-8", newline="") as handle:
        spec = {OBO + r["flopo_id"].replace(":", "_"): r for r in csv.DictReader(handle, delimiter="\t")}
    unmarked = [k for k, r in spec.items() if r.get("status") == "provisional" and status.get(k) != OBO + "IAO_0000125"]
    report.check("C5a", "provisional value terms carry curation status 'pending final vetting'", not unmarked,
                 " ".join(unmarked) or f"{sum(r.get('status') == 'provisional' for r in spec.values())} provisional")
    block = {k for k in flopo_used if re.search(r"FLOPO_0991\d{3}$", k)}
    unknown = sorted(block - set(spec))
    report.check("C5b", "every flora value term used is in the reviewed spec", not unknown, " ".join(unknown))
    provisional_used = sorted(k for k in block if spec.get(k, {}).get("status") == "provisional")
    report.add("C5c", "provisional terms used by the data", "pass", f"{len(provisional_used)}")

    if previous:
        old = json.loads((previous / "web" / "summary.json").read_text())
        new = json.loads((release / "web" / "summary.json").read_text())
        drops = []
        for source in ("ncvc", "collenette"):
            a, b = old.get(source, {}).get("gate_accepted", 0), new.get(source, {}).get("gate_accepted", 0)
            if b < a * 0.99:
                drops.append(f"{source} accepted {a} -> {b}")
        a, b = old["taxa"]["taxa"], new["taxa"]["taxa"]
        if b < a * 0.99:
            drops.append(f"taxa {a} -> {b}")
        report.check("C6", "coverage not lower than the live release", not drops,
                     "; ".join(drops) or f"against {previous.name}")
    else:
        report.add("C6", "coverage not lower than the live release", "pass", "first release")


# ------------------------------------------------------------------------ crawl

def crawl(base: str, out: Path, report: Report, taxa: int = 10) -> None:
    from playwright.sync_api import sync_playwright

    endpoint = urllib.parse.urljoin(base, "sparql")
    pick = rows(select(endpoint, f"SELECT ?t WHERE {{ ?t a <{FB}Taxon> }} ORDER BY ?t")[0])
    random.Random(0).shuffle(pick)
    taxon_routes = ["#/taxon/" + urllib.parse.quote(r["t"].removeprefix(DATA_NS + "taxon/"), safe="") for r in pick[:taxa]]
    fac = rows(select(endpoint, "SELECT ?c WHERE { ?c <http://www.w3.org/2002/07/owl#equivalentClass> ?x "
                                f"FILTER(STRSTARTS(STR(?c), '{DATA_NS}annotation-class/')) }} LIMIT 1")[0])
    routes = ["#/", "#/taxa", *taxon_routes, "#/traits", "#/identify", "#/coverage", "#/query"]
    if fac:
        routes.append("#/query?describe=" + urllib.parse.quote(fac[0]["c"], safe=""))

    queries: dict[str, str] = {}
    problems: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        page = browser.new_page()
        page.on("console", lambda m: m.type == "error" and problems.append(f"console: {m.text[:160]}"))
        page.on("pageerror", lambda e: problems.append(f"page error: {str(e)[:160]}"))

        def on_response(response):
            if response.status >= 400:
                problems.append(f"HTTP {response.status} {response.url[:120]}")

        def on_request(request):
            if "/sparql" not in request.url:
                return
            if request.method == "POST":
                q = urllib.parse.parse_qs(request.post_data or "").get("query", [""])[0]
            else:
                q = urllib.parse.parse_qs(urllib.parse.urlparse(request.url).query).get("query", [""])[0]
            if q:
                queries.setdefault(q, page.url)

        page.on("response", on_response)
        page.on("request", on_request)

        def visit(route: str) -> None:
            page.goto(urllib.parse.urljoin(base, route), wait_until="networkidle", timeout=180_000)
            page.wait_for_function("() => !document.querySelector('#view .loading')", timeout=180_000)
            if page.query_selector("#view .error") or "Something went wrong" in page.inner_text("#view"):
                problems.append(f"{route}: {page.inner_text('#view')[:200]}")

        for route in routes:
            visit(route)
        # Every trait group, every example query.
        page.goto(urllib.parse.urljoin(base, "#/traits"), wait_until="networkidle")
        organs = page.eval_on_selector_all("a[href^='#/traits/']", "as => [...new Set(as.map(a => a.getAttribute('href')))]")
        for route in organs[:40]:
            visit(route)
        visit("#/query")
        for option in page.eval_on_selector_all("#ex option", "os => os.map(o => o.textContent)"):
            page.select_option("#ex", label=option)
            page.click("#runq")
            page.wait_for_function("() => !document.querySelector('#qout .loading')", timeout=180_000)
            if page.query_selector("#qout .error"):
                problems.append(f"example '{option}': {page.inner_text('#qout')[:200]}")
        browser.close()
    with out.open("w") as handle:
        for q, url in queries.items():
            handle.write(json.dumps({"query": q, "page": url}) + "\n")
    report.check("C18", "browser pages render without errors", not problems,
                 "; ".join(problems[:5]) or f"{len(routes) + len(organs[:40])} pages, {len(queries)} distinct queries")


# ----------------------------------------------------------------------- parity

def _load_reference(release: Path):
    import pyoxigraph as ox

    store = ox.Store()
    for graph in _meta(release)["graphs"]:
        store.load(path=str(release / graph["file"]), format=ox.RdfFormat.N_QUADS)
    return store


def _reference_select(store, query: str) -> tuple[list[dict], float]:
    import pyoxigraph as ox

    started = time.time()
    result = store.query(query, use_default_graph_as_union=True)
    data = json.loads(result.serialize(format=ox.QueryResultsFormat.JSON))
    return data, time.time() - started


def _norm_value(binding: dict | None):
    if binding is None:
        return None
    if binding["type"] == "bnode":
        return ("bnode",)
    value = binding["value"]
    datatype = binding.get("datatype", "")
    if datatype.startswith("http://www.w3.org/2001/XMLSchema#") and datatype.rsplit("#", 1)[1] in {
            "int", "integer", "decimal", "double", "float", "long"}:
        try:
            return ("num", round(float(value), 6))
        except ValueError:
            pass
    # Language tags are ignored: QLever's SAMPLE() drops them, and the browser shows only the text.
    return (binding["type"].replace("typed-literal", "literal"), value)


def _same_cell(a, b) -> bool:
    if a == b:
        return True
    if not (a and b and a[0] == b[0] == "literal"):
        return False
    for sep in (" | ", "; ", "|", ", ", ",", " "):  # GROUP_CONCAT order is unspecified
        if sorted(a[1].split(sep)) == sorted(b[1].split(sep)):
            return True
    return False


def compare(a: dict, b: dict, rows_only: bool = False) -> tuple[bool, int, int]:
    """(same row count, differing cells, total cells) between two SPARQL JSON results.

    ``rows_only`` compares the row count alone (a LIMIT without ORDER BY may return any rows).
    """

    if "boolean" in a or "boolean" in b:
        return a.get("boolean") == b.get("boolean"), 0, 1
    variables = a["head"]["vars"]
    ra = sorted((tuple(_norm_value(r.get(v)) for v in variables) for r in a["results"]["bindings"]), key=repr)
    rb = sorted((tuple(_norm_value(r.get(v)) for v in variables) for r in b["results"]["bindings"]), key=repr)
    if len(ra) != len(rb):
        return False, 0, max(len(ra), len(rb)) * len(variables)
    if rows_only:
        return True, 0, 0
    diff = sum(not _same_cell(x, y) for row_a, row_b in zip(ra, rb) for x, y in zip(row_a, row_b))
    return True, diff, len(ra) * len(variables)


def _canonical(graph):
    """Literals by value: QLever writes integers as xsd:int and omits ^^xsd:string."""

    from rdflib import Graph, Literal
    from rdflib.namespace import XSD

    out = Graph()
    for s, p, o in graph:
        if isinstance(o, Literal) and o.datatype == XSD.string:
            o = Literal(str(o))
        elif isinstance(o, Literal) and o.datatype in {XSD.int, XSD.integer, XSD.long, XSD.short}:
            o = Literal(int(o), datatype=XSD.integer)
        out.add((s, p, o))
    return out


def parity(release: Path, qlever: str, queries: Path, report: Report) -> None:
    meta = _meta(release)
    graphs = {r["g"]: int(r["n"]) for r in rows(select(qlever, "SELECT ?g (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } } GROUP BY ?g")[0])}
    drift = [f"{g['graph'].rsplit('/graph/', 1)[-1]} {g['triples']} -> {graphs.get(g['graph'])}"
             for g in meta["graphs"] if graphs.get(g["graph"]) != g["triples"]]
    report.check("C7", "QLever triple count per graph equals release.json", not drift,
                 "; ".join(drift) or f"{sum(graphs.values())} triples in {len(graphs)} graphs")

    started = time.time()
    store = _load_reference(release)
    print(f"reference Oxigraph store loaded in {time.time() - started:.0f}s", file=sys.stderr)

    owl_query = ("SELECT ?p (COUNT(*) AS ?n) WHERE { ?s ?p ?o VALUES ?p { "
                 + " ".join(f"<http://www.w3.org/{'2002/07/' if n.startswith('owl') else '1999/02/'}{n}>" for n in OWL_NODES)
                 + " } } GROUP BY ?p")
    same, diff, _ = compare(select(qlever, owl_query)[0], _reference_select(store, owl_query)[0])
    report.check("C8", "OWL class expressions are complete (QLever = Oxigraph)", same and not diff,
                 "equal counts of intersectionOf, unionOf, complementOf, restrictions and list cells"
                 if same and not diff else "counts differ")

    mismatched, value_diffs, slow, very_slow, errors = [], [], [], [], []
    cells = diff_cells = 0
    entries = [json.loads(line) for line in queries.read_text().splitlines() if line.strip()]
    selects = [e for e in entries if not re.match(r"^\s*(PREFIX[^\n]*\n\s*)*(DESCRIBE|CONSTRUCT)", e["query"], re.I)]
    for entry in selects:
        q = entry["query"]
        try:
            qa, seconds = select(qlever, q)
            ref, _ = _reference_select(store, q)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{entry['page']}: {str(exc)[:160]}")
            continue
        if seconds > 5:
            very_slow.append(f"{seconds:.1f}s {entry['page']}")
        elif seconds > 2:
            slow.append(f"{seconds:.1f}s {entry['page']}")
        arbitrary = bool(re.search(r"\bLIMIT\s+\d+", q, re.I)) and not re.search(r"\bORDER\s+BY\b", q, re.I)
        same, diff, total = compare(qa, ref, rows_only=arbitrary)
        cells += total
        diff_cells += diff
        if not same:
            mismatched.append(f"{entry['page']}: {len(qa['results']['bindings']) if 'results' in qa else '?'} vs "
                              f"{len(ref['results']['bindings']) if 'results' in ref else '?'} rows | {q[-160:]!r}")
        elif diff:
            value_diffs.append(f"{entry['page']}: {diff}/{total} cells")
    report.check("C9a", "every browser query runs on QLever", not errors, "; ".join(errors[:3]) or f"{len(selects)} queries")
    report.check("C9b", "same number of result rows as Oxigraph", not mismatched, "; ".join(mismatched[:3]) or "all equal")
    share = diff_cells / cells if cells else 0
    report.check("C9c", "same values as Oxigraph (SAMPLE() may pick other labels)", share < 0.01 and not value_diffs,
                 f"{diff_cells}/{cells} cells differ ({share:.2%}); " + "; ".join(value_diffs[:3]), warn=share < 0.05)
    report.check("C10", "browser queries answer within 2 s (fail above 5 s)", not slow and not very_slow,
                 "; ".join((very_slow + slow)[:5]) or "all within 2 s", warn=not very_slow)

    from rdflib import Graph
    from rdflib.compare import isomorphic

    from flopo2.saudi.server import Handler

    sample = rows(select(qlever, f"""SELECT ?x WHERE {{
        {{ SELECT ?x WHERE {{ ?x <http://www.w3.org/2002/07/owl#equivalentClass> ?e FILTER(STRSTARTS(STR(?x), "{DATA_NS}")) }} LIMIT 20 }}
        UNION {{ SELECT ?x WHERE {{ ?x a <{FB}TraitRecord> }} LIMIT 10 }}
        UNION {{ SELECT ?x WHERE {{ ?x a <{FB}Taxon> }} LIMIT 10 }} }}""")[0])
    fake = types.SimpleNamespace(store=store)
    differing = []
    for r in sample:
        status, _h, body, _s = http(qlever + "?" + urllib.parse.urlencode({"query": f"DESCRIBE <{r['x']}>"}),
                                    headers={"Accept": "application/n-triples"})
        got = _canonical(Graph().parse(data=body.decode(), format="nt") if status == 200 else Graph())
        want = _canonical(Graph().parse(data=Handler._describe(fake, r["x"]).decode(), format="turtle"))
        if not isomorphic(got, want):
            differing.append(f"{r['x']} ({len(got)} vs {len(want)} triples)")
    report.check("C11", "DESCRIBE returns the same triples as the development server", bool(sample) and not differing,
                 "; ".join(differing[:3]) or f"{len(sample)} resources")


# ------------------------------------------------------------------------ smoke

def smoke(base: str, release: Path | None, report: Report, expect_release: bool = True) -> None:
    base = base.rstrip("/") + "/"
    meta = _meta(release) if release else None
    endpoint = base + "sparql"

    status, headers, body, _ = http(base)
    stamp = headers.get("X-Atlas-Release", "") if headers else ""
    ok = status == 200 and b"<title>Saudi Flora Trait Atlas</title>" in body
    if meta and expect_release:
        ok = ok and stamp == meta["stamp"]
    report.check("C13a", "the page loads (and is this release)", ok, f"HTTP {status}, release {stamp or '?'}")
    missing = [name for name in ("app.js", "styles.css", "summary.json", "release.json") if http(base + name)[0] != 200]
    report.check("C13b", "static files are served", not missing, " ".join(missing) or "all 200")

    try:
        result, seconds = select(endpoint, "SELECT (COUNT(*) AS ?n) WHERE { GRAPH ?g { ?s ?p ?o } }")
        n = int(result["results"]["bindings"][0]["n"]["value"])
        ok = n == meta["triples"] if meta else n > 0
        report.check("C14", "the endpoint answers with the release's quad count", ok, f"{n} triples in {seconds:.2f}s")
    except Exception as exc:  # noqa: BLE001
        report.add("C14", "the endpoint answers with the release's quad count", "fail", str(exc)[:200])

    q = urllib.parse.urlencode({"query": f"SELECT ?t WHERE {{ ?t a <{FB}Taxon> }} LIMIT 3", "format": "csv"})
    status, headers, body, _ = http(endpoint + "?" + q)
    report.check("C15a", "?format=csv returns CSV", status == 200 and "text/csv" in (headers.get("Content-Type") or ""),
                 f"HTTP {status} {headers.get('Content-Type') if headers else ''}")
    q = urllib.parse.urlencode({"query": f"CONSTRUCT {{ ?t a <{FB}Taxon> }} WHERE {{ ?t a <{FB}Taxon> }} LIMIT 3"})
    status, headers, body, _ = http(endpoint + "?" + q, headers={"Accept": "text/turtle"})
    report.check("C15b", "CONSTRUCT returns Turtle", status == 200 and "turtle" in (headers.get("Content-Type") or ""),
                 f"HTTP {status} {headers.get('Content-Type') if headers else ''}")
    report.check("C15c", "the endpoint sends CORS headers", (headers.get("Access-Control-Allow-Origin") if headers else "") == "*")
    status, *_ = http(endpoint + "?" + urllib.parse.urlencode({"query": "SELECT * WHERE { ?s ?p "}))
    report.check("C15d", "a malformed query is a 400", status == 400, f"HTTP {status}")

    fac = rows(select(endpoint, "SELECT ?c WHERE { ?c <http://www.w3.org/2002/07/owl#equivalentClass> ?x "
                                f"FILTER(STRSTARTS(STR(?c), '{DATA_NS}annotation-class/')) }} LIMIT 1")[0])
    taxon = rows(select(endpoint, f"SELECT ?t WHERE {{ ?t a <{FB}Taxon> FILTER(STRSTARTS(STR(?t), '{DATA_NS}taxon/')) }} LIMIT 1")[0])
    if fac and taxon:
        iri = fac[0]["c"]
        url = base + iri.removeprefix(DATA_NS)
        status, headers, body, _ = http(url, headers={"Accept": "text/turtle"})
        report.check("C16a", "a data IRI returns Turtle", status == 200 and b"equivalentClass" in body,
                     f"{url} HTTP {status}, {len(body.splitlines())} lines")
        status, headers, _b, _ = http(url, headers={"Accept": "text/html"})
        location = headers.get("Location", "") if headers else ""
        report.check("C16b", "the same IRI sends people to the browser", status == 303 and "#/query?describe=" in location,
                     f"HTTP {status} -> {location[:90]}")
        url = base + taxon[0]["t"].removeprefix(DATA_NS)
        status, headers, _b, _ = http(url, headers={"Accept": "text/html"})
        location = headers.get("Location", "") if headers else ""
        report.check("C16c", "a taxon IRI opens the taxon page", status == 303 and "#/taxon/" in location,
                     f"HTTP {status} -> {location[:90]}")
    else:
        report.add("C16", "data IRIs dereference", "fail", "no annotation class or taxon found")

    update = urllib.parse.urlencode({"update": "INSERT DATA { <http://example.org/x> <http://example.org/y> 1 }"}).encode()
    status, *_ = http(endpoint, update, {"Content-Type": "application/x-www-form-urlencoded"})
    written = select(endpoint, "ASK { <http://example.org/x> ?p ?o }")[0].get("boolean")
    report.check("C17", "the endpoint refuses updates", status in {400, 401, 403, 405} and not written,
                 f"HTTP {status}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("preflight")
    p.add_argument("release", type=Path)
    p.add_argument("--previous", type=Path)
    p = sub.add_parser("crawl")
    p.add_argument("base")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--release", type=Path)
    p = sub.add_parser("parity")
    p.add_argument("release", type=Path)
    p.add_argument("--qlever", required=True)
    p.add_argument("--queries", type=Path, required=True)
    p = sub.add_parser("smoke")
    p.add_argument("base")
    p.add_argument("--release", type=Path)
    p.add_argument("--stage", default="smoke")
    p.add_argument("--any-release", action="store_true", help="do not require the page to be this release")
    for p in sub.choices.values():
        p.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    release = getattr(args, "release", None)
    path = args.report or (release / "checks.json" if release else None)
    report = Report(path, getattr(args, "stage", args.command) if args.command == "smoke" else args.command)
    if args.command == "preflight":
        preflight(args.release, args.previous, report)
    elif args.command == "crawl":
        crawl(args.base, args.out, report)
    elif args.command == "parity":
        parity(args.release, args.qlever, args.queries, report)
    else:
        smoke(args.base, args.release, report, expect_release=not args.any_release)
    return report.finish()


if __name__ == "__main__":
    sys.exit(main())
