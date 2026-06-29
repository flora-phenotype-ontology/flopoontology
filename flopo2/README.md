# flopo2 — FLOPO 2.0 rebuild

LLM/Graph-RAG rebuild of the Flora Phenotype Ontology. The curated trait **database is the source
of truth**; the OWL ontology is a gated, reasoned derivative that **preserves every existing FLOPO
identifier**; taxa are normalized to **WFO + IPNI**; a dynamic Dockerized site serves the traits.

Full plan: `/home/leechuck/.claude/plans/lazy-marinating-boot.md`. Literature: `../resources/`.

## Modules (by phase)

| Module | Phase | Purpose |
|---|---|---|
| `ids/registry.py` | 0 | Immutable signature→FLOPO_IRI registry from `ontology/flopo.owl`; `IdAllocator` reuses existing IRIs and mints new ones after the max. **Done.** |
| `ids/combinations.py` | 0 | Seed `config/valid_combinations.tsv` (PO×PATO whitelist/blocklist) from the registry. **Done.** |
| `ingest/florml.py`, `ingest/fdac.py`, `ingest/kew.py`, `ingest/cli.py` | 1 | Parse FlorML XML + `fdac` CSV + Kew export → `TextSegment`s (116k segments / 28k taxa). **Done.** |
| `taxon/normalize.py`, `taxon/cli.py` | 2 | GNparser + Global Names Verifier → WFO + IPNI + GBIF IDs, SQLite-cached → taxon table. **Done.** |
| `schema/flopo_trait.yaml` (+ generated `_models.py`, `_ddl.sql`) | 3 | LinkML extraction schema → Pydantic models + SQL DDL. **Done.** |
| `eval/scoring.py`, `eval/gold.py`, `eval/cli.py` | 4 | Stratified gold sampler + metrics (exact/lenient P/R/F1, grounding confusion, negation, hallucination, flip-rate). **Done.** |
| `extract/graphrag.py` | 5 | Engine A: combined Graph-RAG over PO/PATO/TO. |
| `extract/spires_oak.py` | 5 | Engine B: SPIRES + OAK grounding. |
| `extract/router.py` | 5 | OpenRouter tiered routing (Qwen/DeepSeek → GLM 5.2). |
| `extract/compose.py` | 6 | LLM binding + dependency parse-tree cross-check. |
| `verify/gates.py` | 7 | Source-span / PO×PATO validity / verifier LLM / FloraTraiter cross-check. |
| `db/schema.sql` | 7 | Postgres schema + materialized views. |
| `owl/build.py`, `owl/qc.sh` | 8 | ROBOT EQ-pattern build; reason/report; obsolete-in-place; SSSOM→TO/OBA. |

## Artifacts produced so far

In `../config/`:
- `flopo_id_registry.tsv` — 24,200 FLOPO classes with canonical EQ signature + deprecation flag. **The identifier-stability contract.**
- `valid_combinations.tsv` — 22,865 allowed + 7 blocked PO×PATO combinations (2016 seed).
- `deprecated_to_reground.tsv` — 967 deprecated classes whose defining axiom was stripped; combos recovered by label-grounding in Phase 8.
- `taxon_cache.sqlite`, `taxon_table_sample.tsv` — Phase 2 resolution cache + a 60-taxon sample.

In `../gold/`:
- `annotation_template.jsonl` — 400 stratified segments (4 sources × organ × language) for botanist annotation; gates Phase 5.

## Install & run (uv)

```bash
uv venv --python 3.13
uv pip install -e '.[extract,nlp,graphrag,dev]'   # full toolchain
source .venv/bin/activate
pytest                                            # 28 tests

python -m flopo2.ids.registry ontology/flopo.owl  # (re)build the IRI registry
python -m flopo2.ids.combinations                 # seed valid_combinations.tsv
python -m flopo2.ingest.cli stats                 # corpus stats (116k segments)
python -m flopo2.taxon.cli --limit 60             # resolve a taxon sample (network)
python -m flopo2.eval.cli sample --n 400          # build the gold annotation template
```

Network note: `taxon/normalize.py` calls the public GNparser + Global Names Verifier APIs (no
local binary). `OPENROUTER_API_KEY` is read by the Phase 5 extraction engines (not yet built).
