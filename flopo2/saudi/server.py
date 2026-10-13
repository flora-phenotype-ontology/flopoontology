"""Serve the Saudi-flora RDF dataset: a SPARQL endpoint plus the browser in ``web/saudi/``.

    python -m flopo2.saudi.server            # http://localhost:8777/

The Oxigraph store under ``local-corpora/saudi-flora/store`` is (re)loaded from the files listed
in ``manifest.json`` whenever they change, each into its named graph; the released
``ontology/flopo-inferred.owl`` is loaded as graph ``.../graph/flopo`` so queries can use the FLOPO
class hierarchy.  Queries see the union of all graphs as their default graph.

Endpoints
    GET/POST /sparql   SPARQL 1.1 query (``query`` parameter or ``application/sparql-query`` body);
                       results as SPARQL JSON, or CSV/TSV/XML by ``Accept`` or ``format``.
    GET /summary.json  build summary (coverage per source).
    GET /*             static files of the browser.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import shutil
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pyoxigraph as ox

DATA = Path("local-corpora/saudi-flora")
WEB = Path("web/saudi")
FLOPO_GRAPH = "http://phenomebrowser.net/flopo/saudi-flora/graph/flopo"
FLOPO_FILE = Path("ontology/flopo-inferred.owl")
FORMATS = {
    "json": (ox.QueryResultsFormat.JSON, "application/sparql-results+json"),
    "csv": (ox.QueryResultsFormat.CSV, "text/csv"),
    "tsv": (ox.QueryResultsFormat.TSV, "text/tab-separated-values"),
    "xml": (ox.QueryResultsFormat.XML, "application/sparql-results+xml"),
}
GRAPH_FORMATS = {
    "text/turtle": ox.RdfFormat.TURTLE,
    "application/n-triples": ox.RdfFormat.N_TRIPLES,
}
PREFIXES = {
    "fb": "http://phenomebrowser.net/flopo/browse#",
    "flopoann": "http://phenomebrowser.net/flopo/annotation/",
    "obo": "http://purl.obolibrary.org/obo/",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dcterms": "http://purl.org/dc/terms/",
    "sio": "http://semanticscience.org/resource/",
    "prov": "http://www.w3.org/ns/prov#",
    "dwc": "http://rs.tdwg.org/dwc/terms/",
    "geo": "http://www.opengis.net/ont/geosparql#",
}


def _inputs(data: Path, with_flopo: bool) -> list[tuple[str, Path]]:
    manifest = json.loads((data / "manifest.json").read_text())
    inputs = [(entry["graph"], Path(entry["file"])) for entry in manifest.values()]
    if with_flopo and FLOPO_FILE.exists():
        inputs.append((FLOPO_GRAPH, FLOPO_FILE))
    return inputs


def _fingerprint(inputs: list[tuple[str, Path]]) -> str:
    h = hashlib.sha256()
    for graph, path in sorted(inputs):
        stat = path.stat()
        h.update(f"{graph}\t{path}\t{stat.st_size}\t{stat.st_mtime_ns}\n".encode())
    return h.hexdigest()


def open_store(data: Path = DATA, with_flopo: bool = True) -> ox.Store:
    inputs = _inputs(data, with_flopo)
    fingerprint = _fingerprint(inputs)
    store_dir = data / "store"
    stamp = data / "store.fingerprint"
    if store_dir.exists() and stamp.exists() and stamp.read_text() == fingerprint:
        return ox.Store(str(store_dir))
    if store_dir.exists():
        shutil.rmtree(store_dir)
    store = ox.Store(str(store_dir))
    for graph, path in inputs:
        started = time.time()
        fmt = ox.RdfFormat.RDF_XML if path.suffix == ".owl" else None
        # load(), not bulk_load(): bulk loading parses files in parallel chunks and does not keep
        # blank-node labels consistent across chunks, which breaks the OWL class expressions.
        store.load(path=str(path), format=fmt, to_graph=ox.NamedNode(graph), lenient=True)
        print(f"loaded {path} into <{graph}> in {time.time() - started:.1f}s", file=sys.stderr)
    store.optimize()
    stamp.write_text(fingerprint)
    return store


class Handler(BaseHTTPRequestHandler):
    store: ox.Store
    web: Path
    data: Path

    def log_message(self, fmt: str, *args) -> None:  # quieter log
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        url = urlparse(self.path)
        if url.path == "/sparql":
            params = parse_qs(url.query)
            if "query" not in params:
                return self._send(400, b"missing query parameter", "text/plain")
            return self._query(params["query"][0], params.get("format", [""])[0])
        if url.path == "/summary.json":
            return self._file(self.data / "summary.json")
        path = (self.web / url.path.lstrip("/")).resolve()
        if url.path in {"", "/"} or not path.is_file():
            path = self.web / "index.html"  # client-side routes
        if self.web.resolve() not in path.resolve().parents and path != self.web / "index.html":
            return self._send(404, b"not found", "text/plain")
        return self._file(path)

    def do_POST(self) -> None:
        url = urlparse(self.path)
        if url.path != "/sparql":
            return self._send(404, b"not found", "text/plain")
        body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
        ctype = self.headers.get("Content-Type", "")
        if ctype.startswith("application/sparql-query"):
            query = body
        else:
            query = parse_qs(body).get("query", [""])[0]
        return self._query(query, parse_qs(url.query).get("format", [""])[0])

    def _file(self, path: Path) -> None:
        if not path.is_file():
            return self._send(404, b"not found", "text/plain")
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in {"application/javascript", "application/json"}:
            ctype += "; charset=utf-8"
        self._send(200, path.read_bytes(), ctype)

    def _describe(self, iri: str) -> bytes:
        """Concise bounded description: the resource's triples, following blank nodes."""

        from rdflib import BNode as RBNode, Graph as RGraph, Literal as RLiteral, URIRef as RURIRef

        def term(t):
            if isinstance(t, ox.NamedNode):
                return RURIRef(t.value)
            if isinstance(t, ox.BlankNode):
                return RBNode(t.value)
            datatype = RURIRef(t.datatype.value) if t.datatype and not t.language else None
            return RLiteral(t.value, lang=t.language, datatype=datatype)

        graph, todo, seen = RGraph(), [ox.NamedNode(iri)], set()
        graph.bind("obo", "http://purl.obolibrary.org/obo/")
        graph.bind("fb", PREFIXES["fb"])
        graph.bind("flopoann", PREFIXES["flopoann"])
        while todo:
            node = todo.pop()
            if node in seen:
                continue
            seen.add(node)
            for quad in self.store.quads_for_pattern(node, None, None, None):
                graph.add((term(quad.subject), term(quad.predicate), term(quad.object)))
                if isinstance(quad.object, ox.BlankNode):
                    todo.append(quad.object)
        return graph.serialize(format="turtle").encode("utf-8")

    def _query(self, query: str, fmt: str) -> None:
        accept = self.headers.get("Accept", "")
        single = re.fullmatch(r"\s*DESCRIBE\s+<([^>\s]+)>\s*", query, re.IGNORECASE)
        if single:
            return self._send(200, self._describe(single.group(1)), "text/turtle; charset=utf-8")
        try:
            result = self.store.query(query, use_default_graph_as_union=True, prefixes=PREFIXES)
        except SyntaxError as exc:
            return self._send(400, f"SPARQL syntax error: {exc}".encode(), "text/plain; charset=utf-8")
        except Exception as exc:  # noqa: BLE001
            return self._send(500, f"query failed: {exc}".encode(), "text/plain; charset=utf-8")
        if isinstance(result, ox.QueryTriples):
            for media, rdf_format in GRAPH_FORMATS.items():
                if media in accept:
                    break
            else:
                media, rdf_format = "text/turtle", ox.RdfFormat.TURTLE
            return self._send(200, result.serialize(format=rdf_format), media + "; charset=utf-8")
        key = fmt or next((k for k, (_f, m) in FORMATS.items() if m in accept or f"text/{k}" in accept), "json")
        results_format, media = FORMATS.get(key, FORMATS["json"])
        self._send(200, result.serialize(format=results_format), media + "; charset=utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8777)
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--web", type=Path, default=WEB)
    parser.add_argument("--no-flopo", action="store_true", help="do not load flopo-inferred.owl")
    args = parser.parse_args(argv)
    Handler.store = open_store(args.data, with_flopo=not args.no_flopo)
    Handler.web = args.web
    Handler.data = args.data
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Saudi flora browser on http://{args.host}:{args.port}/", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
