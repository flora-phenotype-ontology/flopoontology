# Deploying the Saudi Flora Trait Atlas to phenomebrowser.net/flopo/

Design for serving the atlas publicly: the browser in `web/saudi/`, backed by live SPARQL queries
against a QLever endpoint, at `http://phenomebrowser.net/flopo/`. Nothing here is implemented yet.

## Why this location

The atlas data IRIs are already `http://phenomebrowser.net/flopo/…` (annotations, browse index,
places, vocabulary). FLOPO has no w3id redirect and keeps its own identifier space (curator
decision 2026-10-05), so serving the atlas under `/flopo/` makes those IRIs dereferenceable
without any redirect service. Ontology terms stay OBO PURLs.

## Target layout

```
phenomebrowser.net (nginx 1.20, 45.223.22.138; "/" is an existing Express app, /flopo/ is 404 today)
  /flopo/                 static browser (index.html, app.js, styles.css, summary.json)
  /flopo/sparql           -> QLever (read-only, GET + POST, SPARQL JSON/CSV/TSV, Turtle for CONSTRUCT/DESCRIBE)
  /flopo/annotation/…     -> 303 to /flopo/#/query?describe=<iri>, or Turtle by Accept (DESCRIBE via QLever)
  /flopo/browse, /taxon/…, /place/…, /vocab/…   same dereferencing rule
  /flopo/releases/<stamp>/  the dumped RDF of each deployment (only for the public profile, see below)

QLever container(s) on the web host, bound to 127.0.0.1, blue/green ports 7001/7002.
```

Oxigraph stays as the local development server (`flopo2.saudi.server`); QLever is the public
endpoint. Both read the same RDF files, and the checks below prove they answer the browser's
queries identically.

## Changes to the code before the first deployment

1. **Relative endpoints in `web/saudi/app.js`.** `fetch("/sparql")` and `fetch("/summary.json")`
   are absolute and break under `/flopo/`. Use `new URL("sparql", document.baseURI)`, or a
   `<meta name="sparql-endpoint">` in `index.html` so the same build runs locally and under a
   prefix. Same for `window.open("/sparql?…")` in the Query tab.
2. **Prefixes.** The browser already prepends its `PREFIX` block, except for queries typed in the
   Query tab, which today rely on the server predefining `fb:`, `obo:`, … . QLever has no
   predefined prefixes, so the Query tab must also prepend the declarations that the query does
   not declare itself. The example queries keep working.
3. **DESCRIBE.** The Oxigraph server answers `DESCRIBE <iri>` itself, following blank nodes, so
   OWL class expressions come out whole. QLever's DESCRIBE also expands blank-node objects; the
   parity check (below) verifies that the triples match. If they do not, the browser sends a
   `CONSTRUCT` with a bounded property path over blank nodes instead.
4. **Graph semantics.** Oxigraph runs with the default graph as the union of all named graphs;
   QLever's default graph is also the union. Keep one input file per named graph (as in
   `manifest.json`) so that blank-node labels stay scoped to one file, which is what broke
   Oxigraph's `bulk_load`.
5. **`build_release` step** (`tools/build_atlas_release.py`, new): writes a self-contained
   directory `deploy/atlas/<stamp>/` with
   - `rdf/*.nq` (each manifest file converted to N-Quads in its named graph, plus
     `ontology/flopo-inferred.owl` as graph `…/graph/flopo`);
   - `web/` with the stamped static files and `summary.json`;
   - `Qleverfile` and `release.json` (git commit, build stamp, triple counts per graph,
     SHA-256 of every file).

## The public profile: a decision needed first

The atlas quotes the sentences of two copyrighted guides as evidence (`fb:text`, `fb:context`,
`source_en` in the browse index and pending statements), which is why the data is git-ignored.
A public endpoint publishes those quotes to anyone who runs a `SELECT ?t { ?x fb:text ?t }`.
The release step therefore has a **profile**:

| Profile | Quotes | Who can reach it |
|---|---|---|
| `public` | removed; each statement keeps its source, page and taxon, so readers can check the printed guide | phenomebrowser.net/flopo/ |
| `restricted` | kept | behind nginx basic auth or KAUST network only |

Check `C2` below blocks a `public` deployment that still contains a quote. Which profile goes live
(or whether permission from NCVC is sought for the quotes) is the user's call.

The 20 value terms FLOPO:0991026–0991045 are not yet reviewed. Either review them before the first
public deployment, or deploy them marked provisional; check `C5` enforces whichever is chosen.

## Workflow

`tools/deploy_atlas.sh <stamp> [--profile public|restricted] [--target staging|production]`
runs the stages in order and stops at the first failed check. Every stage writes its result to
`deploy/atlas/<stamp>/checks.json`, so a deployment is auditable afterwards.

### Stage 1: build and pre-flight (local, on ws)

| Check | What it verifies | Fails when |
|---|---|---|
| C1 tests | `pytest tests/test_atlas_patterns.py tests/test_saudi_flora.py tests/test_ncvc_annotate.py` and the release compatibility test | any test fails |
| C2 profile | no `fb:text`/`fb:context`/quote literal in a `public` release; no local paths, hostnames or API keys in any literal | a quote or secret is present |
| C3 parse | every `rdf/*.nq` parses with rapper/riot; counts per graph match `release.json` | parse error or count drift |
| C4 IRIs | every data IRI is under `http://phenomebrowser.net/flopo/`; no `w3id.org/flopo`, no `file:`, no `localhost`; every FLOPO IRI used exists in `flopo-inferred.owl` | foreign or dangling IRI |
| C5 terms | terms used by the data are released or listed as approved/provisional | unreviewed term in a public release |
| C6 coverage | `summary.json` coverage per source is not lower than the last deployed release by more than 1 point | silent regression |

### Stage 2: index and parity (local)

1. Build the QLever index from the release (`qlever index` with the `Qleverfile`, docker image
   `adfreiburg/qlever` pinned by digest).
2. Start it on localhost and run:

| Check | What it verifies |
|---|---|
| C7 graph counts | `SELECT ?g (COUNT(*) …) GROUP BY ?g` equals `release.json` (catches blank-node merging and dropped triples) |
| C8 OWL integrity | every annotation class has its full equivalent-class expression: same number of `owl:intersectionOf`/`owl:complementOf`/`owl:withRestrictions` nodes in QLever and Oxigraph |
| C9 query parity | every query the browser issues gives the same result set in QLever and Oxigraph |
| C10 latency | each browser query answers within 2 s (the overview and Coverage queries are the heaviest) |
| C11 DESCRIBE | `DESCRIBE` of 50 sampled annotations and annotation classes returns the same triples as the Oxigraph server |

C9 needs the browser's queries. A small `--record` flag on `flopo2.saudi.server` logs every
`/sparql` request to `queries.jsonl`, and a headless pass over the browser (overview, ten taxa,
every trait group, identify, query examples, coverage) fills it. `tools/atlas_parity.py` then
replays the log against both endpoints and compares sorted bindings. Literal comparison ignores
`GROUP_CONCAT` order; numbers are compared as numbers.

### Stage 3: ship (to the web host)

1. `rsync` the release directory (index + web, no source PDFs, no LLM caches) to
   `/srv/flopo-atlas/releases/<stamp>/`.
2. Start QLever for the release on the idle colour (blue 7001 / green 7002), read-only: no
   access token for updates, query timeout 30 s, memory limit set.
3. **Staging checks against the new container on localhost** (C12): health query, C7 again, five
   browser queries, a malformed query returns 400, an `INSERT` is refused.
4. Switch: `/srv/flopo-atlas/current` → the new release; nginx `upstream flopo_sparql` points to
   the new colour (one include file); `nginx -t && nginx -s reload`.

### Stage 4: post-deploy checks (from outside, against the public URL)

| Check | Request | Expect |
|---|---|---|
| C13 page | `GET /flopo/` | 200, `<title>Saudi Flora Trait Atlas`, `app.js` and `styles.css` 200 |
| C14 endpoint | `POST /flopo/sparql` with the overview query | 200 SPARQL JSON, count equals `release.json` |
| C15 formats | `format=csv`, `Accept: text/turtle` on a CONSTRUCT | right content types |
| C16 IRIs | `GET` 10 sampled annotation IRIs with `Accept: text/turtle` and with `text/html` | Turtle description / 303 to the browser view |
| C17 read-only | `INSERT DATA {…}` | refused |
| C18 browser | headless load of `/flopo/#/taxon/<sample>` | no console errors, the record table has rows |
| C19 not leaking | profile `public`: `SELECT (COUNT(*) …) { ?s fb:text ?o }` | 0 |

Any failure in stage 4 triggers the rollback: point the upstream back at the previous colour,
reload nginx, and record the failure in `checks.json`. The previous release stays on disk until
the next successful deployment.

### Stage 5: after

- Freeze: copy `release.json` and the public RDF dump to `/flopo/releases/<stamp>/`.
- Monitoring: a cron job on the web host runs C13, C14 and C17 every 15 minutes and mails the
  user on failure.

## nginx sketch

```nginx
upstream flopo_sparql { server 127.0.0.1:7001; }   # managed by deploy_atlas.sh (blue/green)

location = /flopo { return 301 /flopo/; }
location /flopo/ {
    alias /srv/flopo-atlas/current/web/;
    try_files $uri /flopo/index.html;
    add_header Cache-Control "public, max-age=300";
}
location = /flopo/sparql {
    limit_req zone=sparql burst=20 nodelay;            # limit_req_zone defined in http {}
    client_max_body_size 64k;
    proxy_read_timeout 60s;
    proxy_pass http://flopo_sparql/;                   # QLever answers SPARQL at its root
    add_header Access-Control-Allow-Origin "*";
}
# Data IRIs: Turtle for machines, the browser for people.
location ~ ^/flopo/(annotation|browse|taxon|place|vocab|saudi-flora)/ {
    if ($http_accept ~* "text/turtle|application/n-triples") {
        rewrite ^ /flopo/describe last;                # a small handler that issues DESCRIBE <$scheme://$host$request_uri>
    }
    return 303 /flopo/#/query?describe=$scheme://$host$request_uri;
}
```

The `/flopo/describe` handler can be a 20-line script (or nginx `njs`) that builds the DESCRIBE
query from the request IRI and proxies it to QLever.

## Open questions

1. **Host access.** phenomebrowser.net is nginx in front of an Express app at 45.223.22.138.
   Who administers it, can QLever run there (the RDF is 158 MB plus the 43 MB inferred ontology, a few million
   triples; Oxigraph's store is 1.9 GB, and a QLever index of this size needs a few GB of RAM and disk), and how do deployments reach it?
   `webfront` (10.254.145.58) was not reachable from ws.
2. **Profile.** public without quotes, restricted with quotes, or ask NCVC for permission.
3. **Unreviewed terms** FLOPO:0991026–0991045: review first, or deploy as provisional.
4. **https.** The server has no https today; the IRIs stay `http://` either way, but the browser
   page would benefit from TLS (Let's Encrypt) if the host allows it.
