# Deploying the Saudi Flora Trait Atlas at phenomebrowser.net/flopo/

The browser in `web/saudi/` runs live SPARQL queries against a QLever endpoint. Both run on ws
(10.73.11.158) in Docker; the phenomebrowser.net frontends proxy `/flopo/` to ws.

```
phenomebrowser.net/flopo/…  (frontend, frontend1: nginx, deploy/atlas/frontend-phenomebrowser.conf)
   │  strips /flopo, sends X-Forwarded-Prefix: /flopo
   ▼
ws :8778  flopo-atlas-nginx (live)          ws 127.0.0.1:8779 (staging: the release being deployed)
   │  /            browser of the live release
   │  /sparql      → QLever (read-only, CORS, 10 req/s per client, ?format=csv|tsv|json|xml)
   │  /<ns>/<id>   data IRIs: Turtle/N-Triples by Accept (DESCRIBE), otherwise 303 to the browser
   ▼
127.0.0.1:7001 flopo-atlas-qlever-blue   127.0.0.1:7002 flopo-atlas-qlever-green
```

The data IRIs are `http://phenomebrowser.net/flopo/…` (FLOPO keeps its own identifier space; there
is no w3id redirect), so serving the atlas at `/flopo/` makes them resolve:
`curl -H 'Accept: text/turtle' http://phenomebrowser.net/flopo/annotation-class/FAC_…`.
Ontology terms stay OBO PURLs.

The Oxigraph server (`flopo2.saudi.server`, port 8777) stays the development server. The checks
prove that QLever gives the browser the same answers.

## Deploying

```bash
tools/build_saudi_flora.sh            # rebuild the data, when it changed
tools/deploy_atlas.sh                 # release, index, check, switch, check
tools/deploy_atlas.sh --status        # what is live
tools/deploy_atlas.sh --rollback      # previous release back (its QLever is kept running)
```

`PUBLIC_URL` (default `http://phenomebrowser.net/flopo/`) is checked after the switch; use
`PUBLIC_URL= tools/deploy_atlas.sh` while the frontends do not yet proxy `/flopo/`.

A release is `local-corpora/saudi-flora/releases/<stamp>/` (git-ignored):

- `rdf/*.nq`: one N-Quads file per named graph (the manifest graphs and `flopo-inferred.owl`), with
  blank-node labels prefixed per file;
- `index/`: the QLever index;
- `web/`: the browser, `summary.json`, `release.json`;
- `release.json`: commit, triple count and SHA-256 per graph;
- `queries.jsonl`: every query the browser sent during the crawl;
- `checks.json`: the result of every check, per stage.

`releases/state/` holds what is live (`live.env`) and the nginx includes that point the live and
staging servers at a release and its QLever container.

The browser uses relative URLs (`sparql`, `summary.json`), so the same files work at `/` and under
`/flopo/`. It adds the PREFIX declarations a query does not make (QLever predefines none).

## Checks

The script stops at the first failed check. Before the switch nothing live changes. After the
switch, a failure restores the previous release. Warnings are recorded and do not stop a deployment.

| Stage | Check | What it verifies |
|---|---|---|
| pre-flight | C1 | atlas, Saudi flora and NCVC annotation tests pass |
| | C2 | no local paths, hostnames or API keys in literals |
| | C3 | every N-Quads file matches its SHA-256 and triple count |
| | C4 | data IRIs are under `http://phenomebrowser.net/flopo/`, none on w3id, `file:` or localhost; every FLOPO class used exists (obsolete ones: warning) |
| | C5 | provisional value terms carry IAO:0000114 'pending final vetting'; every FLOPO:0991xxx used is in the spec |
| | C6 | accepted statements and taxa are not more than 1% below the live release |
| staging | C13–C17 | below, against the staging server |
| | C18 | headless Chromium opens the overview, 10 taxa, every trait group, identify, coverage and every example query, without console errors, failed requests or error messages |
| | C7 | QLever's triple count per graph equals `release.json` |
| | C8 | OWL class expressions are complete: the counts of intersectionOf, unionOf, complementOf, restrictions and list cells equal Oxigraph's |
| | C9 | every query from C18 runs on QLever and gives the same number of rows as Oxigraph on the same files; values are compared too, except for a LIMIT without ORDER BY (any rows are right) and language tags (QLever's `SAMPLE()` drops them). `SAMPLE()` may pick another label: a warning below 5% of cells |
| | C10 | every browser query answers within 2 s (warning), 5 s (failure) |
| | C11 | `DESCRIBE` of 40 annotation classes, records and taxa equals the development server's description (literals by value: QLever writes integers as `xsd:int`) |
| live, public | C13 | page and static files load, and the page is the expected release (`X-Atlas-Release`) |
| | C14 | the endpoint answers with the release's quad count (the union default graph counts a triple stated in two graphs once) |
| | C15 | `?format=csv`, Turtle for CONSTRUCT, CORS, a malformed query is a 400 |
| | C16 | an annotation-class IRI returns Turtle with its OWL definition; with `Accept: text/html` it redirects to the browser; a taxon IRI opens the taxon page |
| | C17 | updates are refused and nothing is written |

Oxigraph accepts `(SAMPLE(?x) AS ?x)`; SPARQL and QLever do not, so a browser query must not
name an aggregate after a variable of its body. The first deployment found five such queries.

The reference for C8, C9 and C11 is an in-memory Oxigraph store loaded from the release's own
N-Quads, so both engines read identical data.

## Monitoring

`tools/deploy_atlas.sh --monitor` runs C13–C17 against the live and public addresses. It appends
one line to `releases/state/monitor.log` and keeps the details in `state/monitor-last.json`.
ws's crontab runs it every 15 minutes, with `PUBLIC_URL=` until the frontends proxy `/flopo/`
(then drop that setting so the public address is checked too). It writes to the log only and does
not send mail.

## Connecting phenomebrowser.net

`deploy/atlas/frontend-phenomebrowser.conf` is the location block for the phenomebrowser.net server
on `frontend` and `frontend1` (borg-infrastructure: `/etc/nginx/sites-available/phenomebrowser.net`,
root via `sudo rootsh`). It was tested against a local nginx with the same block: C13–C18 pass
under `/flopo/`. After it is applied, run `tools/deploy_atlas.sh --monitor` without `PUBLIC_URL=`.

## Provisional terms

FLOPO:0991026–0991045 are not yet reviewed. They carry IAO:0000114 'pending final vetting'
(IAO:0000125), and their editor note says "Provisional: not yet reviewed by the curator". They
are set by the `status` column of `config/flopo_flora_value_terms.tsv`. C5 checks the marking.

## Pinned images

`tools/deploy_atlas.sh` pins `adfreiburg/qlever` and `nginx:1.27-alpine` by digest. To upgrade,
pull the new image, put its digest in the script and deploy; C7–C11 show whether the new QLever
answers like the old one.
