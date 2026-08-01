# flopo2 — FLOPO 2.0 rebuild

LLM/Graph-RAG rebuild of the Flora Phenotype Ontology. The curated trait **database is the source
of truth**; the OWL ontology is a gated, reasoned derivative that **preserves every existing FLOPO
identifier**; taxa are normalized to **WFO + IPNI**; a dynamic Dockerized site serves the traits.

Full plan: `/home/leechuck/.claude/plans/lazy-marinating-boot.md`. Literature: `../resources/`.

## Modules (by phase)

| Module | Phase | Purpose |
|---|---|---|
| `terminology/` | 4–5 | Versioned botanical glossary registry, PO/PATO/FLOPO alignment, hybrid retrieval, span annotation, curation, SSSOM, and evaluation. **Done.** |
| `ids/registry.py` | 0 | Immutable signature→FLOPO_IRI registry from `ontology/flopo.owl`; `IdAllocator` reuses existing IRIs and mints new ones after the max. **Done.** |
| `ids/combinations.py` | 0 | Seed `config/valid_combinations.tsv` (PO×PATO whitelist/blocklist) from the registry. **Done.** |
| `ingest/florml.py`, `ingest/fdac.py`, `ingest/kew.py`, `ingest/cli.py` | 1 | Parse FlorML XML + `fdac` CSV + Kew export → `TextSegment`s (116k segments / 28k taxa). **Done.** |
| `taxon/normalize.py`, `taxon/cli.py` | 2 | GNparser + Global Names Verifier → WFO + IPNI + GBIF IDs, SQLite-cached → taxon table. **Done.** |
| `schema/flopo_trait.yaml` (+ generated `_models.py`, `_ddl.sql`) | 3 | LinkML extraction schema → Pydantic models + SQL DDL. **Done.** |
| `ANNOTATION_MODEL.md`, `../ontology/flopo-annotation-model.ttl` | 3 | SIO-aligned flora assertion/observation architecture, provenance, modality, quantitative values, seasons, PO developmental stages, scoped negation, and non-FLOPO annotation-class IDs. **Done.** |
| `eval/scoring.py`, `eval/gold.py`, `eval/cli.py` | 4 | Stratified gold sampler + metrics (exact/lenient P/R/F1, grounding confusion, negation, hallucination, flip-rate). **Done.** |
| `extract/graphrag.py` | 5 | Engine A: combined Graph-RAG over PO/PATO/TO. |
| `extract/spires_oak.py` | 5 | Engine B: SPIRES + OAK grounding. |
| `extract/router.py` | 5 | OpenRouter tiered routing (Qwen/DeepSeek → GLM 5.2). |
| `extract/baseline.py`, `extract/measurement.py`, `extract/context_recovery.py`, `extract/developmental_stage_recovery.py` | 5 | Conservative deterministic full-corpus rehearsal with audited botanical cues, explicit local bearers, exact assertion offsets, quantitative ranges, modality, seasons, scoped negation, same-bearer age/maturity qualities, and PO developmental stages. **Done.** |
| `extract/compose.py` | 6 | Source-span, related-part, and optional dependency parse-tree composition cross-check; splits accepted/review queues. **Done.** |
| `verify/gates.py` | 7 | Source-span + PO×PATO validity gates, FLOPO IRI reuse/new-class annotation, verifier/FloraTraiter hooks, accepted/review/blocked queues. **Done.** |
| `verify/missing_bearers.py` | 7 | Separates accepted existing-PO bearer vocabulary from genuinely missing FLOPO concepts and assertion-level attachment/region review. **Done.** |
| `verify/data_model.py`, `verify/merge_jsonl.py` | 7 | Strict LinkML/wire/ontology/provenance/quantitative-value/SQLite validation and identity-safe multi-flora merging. **Done.** |
| `db/schema.sql`, `db/load.py` | 7 | SQLite-compatible curated trait DB with mandatory source-statement foreign keys, an annotation-class registry, structured modality/season fields, curation views, and JSONL loader. **Done.** |
| `owl/annotation_class.py`, `owl/annotation_extension.py`, `owl/assertions.py` | 8 | Give every canonical OWL phenotype expression a stable `FAC_` IRI outside FLOPO, define it once in an annotation extension, and link lossless source assertions to it. **Done.** |
| `owl/build.py`, `owl/qc.sh`, `owl/sssom.py` | 8 | Build and check the curated reusable FLOPO vocabulary independently of annotation-expression IDs. **Done.** |

## Artifacts produced so far

In `../config/`:
- `flopo_id_registry.tsv` — the 24,689 released FLOPO classes with canonical EQ signature +
  deprecation flag. **The released identifier-stability contract.**
- `flopo_reviewed_id_reservations.tsv` — 366 explicitly reviewed, not-yet-released
  signature-to-IRI reservations. The allocator consumes this file so another build cannot reuse
  `FLOPO_0980611`–`FLOPO_0980976` before the next release registry is regenerated.
- `valid_combinations.tsv` — the allowed PO×PATO combinations used by the gate.
- `deprecated_to_reground.tsv` — 967 deprecated classes whose defining axiom was stripped; combos recovered by label-grounding in Phase 8.
- `taxon_cache.sqlite`, `taxon_table_sample.tsv` — Phase 2 resolution cache + a 60-taxon sample.
- `terminology_sources.tsv`, `botanical_terminology.tsv` — licensed-source manifest and durable
  botanical term mapping registry. See [`TERMINOLOGY.md`](TERMINOLOGY.md).

In `../gold/`:
- `annotation_template.jsonl` — 400 stratified segments (4 sources × organ × language) for botanist annotation; gates Phase 5.
- `paul_gold_review_100.tsv` — 100-segment review spreadsheet exported from the silver standard;
  Paul edits `gold_assertions_json`, which becomes the first human gold set.

## Install & run (uv)

```bash
uv venv --python 3.13
uv pip install -e '.[extract,nlp,graphrag,terminology,dev]'   # full toolchain
source .venv/bin/activate
pytest                                            # run the full test suite

python -m flopo2.ids.registry ontology/flopo.owl  # (re)build the IRI registry
python -m flopo2.ids.combinations                 # seed valid_combinations.tsv
python -m flopo2.ingest.cli stats                 # corpus stats (116k segments)
python -m flopo2.taxon.cli --limit 60             # resolve a taxon sample (network)
python -m flopo2.eval.cli sample --n 400          # build the gold annotation template
python -m flopo2.eval.curation                    # build gold/paul_gold_review_100.tsv
python -m flopo2.eval.curation --to-jsonl -o gold/gold_standard_100.jsonl
python -m flopo2.terminology.cli build
python -m flopo2.terminology.cli coverage segments.jsonl --update-frequencies
python -m flopo2.extract.compose gold/silver_standard.jsonl --limit 20 --parser auto \
  --accepted-out gold/composition_accepted.jsonl \
  --review-out gold/composition_review.jsonl
python -m flopo2.verify.gates gold/composition_checks.jsonl \
  -o gold/gated_assertions.jsonl \
  --accepted-out gold/gated_accepted.jsonl \
  --review-out gold/gated_review.jsonl \
  --blocked-out gold/gated_blocked.jsonl
python -m flopo2.verify.novel_combinations gold/gated_review.jsonl \
  -o gold/novel_po_pato_review.tsv
python -m flopo2.verify.approve_combinations gold/novel_po_pato_review.tsv \
  --approved-review curation/approved_po_pato.tsv \
  --reviewer https://orcid.org/0000-0001-8149-5890 \
  --review-date 2026-07-17 --source curator_review_2026-07-17
# Re-run the gates after approval so the reviewed assertions enter the accepted source of truth.
python -m flopo2.verify.gates gold/composition_checks.jsonl \
  -o gold/gated_assertions.jsonl \
  --accepted-out gold/gated_accepted.jsonl \
  --review-out gold/gated_review.jsonl \
  --blocked-out gold/gated_blocked.jsonl
# Losslessly upgrade an existing extraction artifact before loading/building it.
python -m flopo2.annotation.provenance legacy-gated.jsonl \
  -o provenance-gated.jsonl
# Materialize stable annotation-class links and define every distinct expression once.
python -m flopo2.owl.annotation_extension gold/gated_assertions.jsonl \
  -o ontology/flopo-annotation-extension.ofn \
  --annotated-jsonl gold/gated-annotated.jsonl \
  --registry ontology/flopo-annotation-class-registry.tsv --version candidate --format ofn
python -m flopo2.verify.data_model gold/gated-annotated.jsonl --stage gated \
  --require-annotation-class -o gold/gated-validation.json
python -m flopo2.db.load gold/gated-annotated.jsonl --db flopo2.sqlite
python -m flopo2.verify.data_model gold/gated-annotated.jsonl --stage gated \
  --require-annotation-class --db flopo2.sqlite -o gold/gated_validation.json
uv run python -m flopo2.owl.build gold/gated_assertions.jsonl \
  -o ontology/flopo-v2-candidate.ofn --version candidate --format ofn
# Promote only explicitly reviewed, newly allocated EQ classes and their reusable
# phenotype parents. The source module keeps curator and assertion-level provenance;
# the release updater is idempotent and the registry reserves the resulting IDs.
# The tracked approval table keeps aggregate evidence counts but leaves verbatim
# flora-example fields empty until the source corpora's redistribution terms are clear.
uv run python -m flopo2.owl.reviewed_extension ontology/flopo-v2-candidate.ofn \
  --approvals curation/gabon-annotation-v4-po-pato-approvals.tsv \
  --output ontology/flopo-reviewed-combinations.ttl \
  --reservations-output config/flopo_reviewed_id_reservations.tsv \
  --date 2026-07-17
uv run python tools/update_flopo_reviewed_release.py --date 2026-07-17
uv run python -m flopo2.ids.registry ontology/flopo.owl -o config/flopo_id_registry.tsv
# Re-gate and rebuild after promotion: every approved assertion must now report
# flopo_status=existing and a stable flopo_iri; a subsequent candidate must mint 0 IDs.
python -m flopo2.owl.assertions gold/gated-annotated.jsonl \
  -o ontology/flora-assertions.ofn --version candidate --format ofn
PYTHON=.venv/bin/python bash flopo2/owl/qc.sh ontology/flopo-v2-candidate.ofn gold/gated_assertions.jsonl
# Source modules can be OWL-DL checked independently; expression classification belongs to the
# imported annotation extension, where each definition occurs once.
java -cp tools/robot.jar tools/CheckOwlConsistency.java ontology/flora-assertions.ofn
python -m flopo2.owl.build gold/gated_assertions.jsonl \
  -o ontology/flopo-v2-release.ttl --version candidate --obsolete-unsupported-existing
PYTHON=.venv/bin/python bash flopo2/owl/qc.sh ontology/flopo-v2-release.ttl gold/gated_assertions.jsonl
python -m flopo2.owl.sssom ontology/flopo-v2-release.ttl \
  -o ontology/flopo-v2-mappings.sssom.tsv --to ont/trait.obo

# Rebuild locally curated categorical values after a PATO update. Exact PATO
# replacements are omitted; alternatives are OWL unions and compounds use
# explicit quality-component restrictions.
python tools/build_flopo_value_extension.py
python tools/update_flopo_release.py --date 2026-07-13
python -m flopo2.ids.registry ontology/flopo.owl -o config/flopo_id_registry.tsv

# Rebuild the approved bearer-centric hierarchy and local botanical support classes,
# then obsolete the 154 classes that accidentally used human puberty and embed their
# corrected botanical-pubescence replacements. Both release updaters are idempotent.
python tools/build_flopo_botanical_extension.py --date 2026-07-15
python tools/update_flopo_botanical_release.py --date 2026-07-15
python tools/build_flopo_pubescent_migration.py --date 2026-07-15
python tools/update_flopo_pubescent_release.py --date 2026-07-15
python -m flopo2.ids.registry ontology/flopo.owl -o config/flopo_id_registry.tsv
java -jar tools/robot.jar reason --reasoner ELK --catalog ontology/catalog-v001.xml \
  --input ontology/flopo.owl --output ontology/flopo-inferred.owl

# Build the separately reviewed PATO PR module containing open lexical colour
# umbrellas and source-qualified operational senses. The optional closed scarlet
# union is deliberately deferred.
python tools/build_pato_colour_sensu_terms.py --date 2026-07-15
python tools/apply_pato_colour_sensu_terms.py \
  --pato-edit ../pato/src/ontology/pato-edit.obo
```

The extraction JSONL is deliberately loss-aware. `assertions` contains grounded EQ records;
`source_statements` contains first-class verbatim evidence with stable source-scoped identifiers;
`unresolved_spans` contains exact source spans withheld because their negation, alternative or
mixture structure, bearer, stage/modifier, or ontology sense is not yet safe. Both collections
survive composition, gates, multi-flora merging, strict validation, and SQLite loading. A fresh
database path is required for every load so an artifact cannot be appended twice accidentally.
Every segment also carries `source_segment_index`, its zero-based occurrence within one source
file. This is part of provenance identity because real FlorML volumes can repeat identical
taxon/organ/text blocks with the same local character offsets. Gate the complete composition audit,
not only its accepted split, so composition failures remain review assertions in the database.
The `annotation.provenance` migration command streams legacy JSONL into a distinct output file,
materializes one retained source statement per source-scoped evidence span, links every assertion,
and normalizes legacy modality cues without changing the input artifact.

Bearer vocabulary and assertion attachment are separate curation decisions. A live PO class is
accepted as reusable vocabulary and is not sent back to FLOPO concept review merely because the
source syntax is uncertain. The bearer-routing report therefore has three disjoint outputs:
accepted existing PO, genuinely missing FLOPO-local concepts, and attachment/region review.
`context_recovery` may promote an assertion only when the local grammar is independently safe;
otherwise it records `accepted_existing_po` together with `container_attachment` or `syntax_hold`
and preserves the unresolved source span.

```bash
uv run --frozen python -m flopo2.verify.missing_bearers extracted.jsonl \
  -o bearer-routing.tsv \
  --accepted-existing-output accepted-existing-po.tsv \
  --concept-review-output concept-review.tsv \
  --attachment-review-output attachment-review.tsv
uv run --frozen python -m flopo2.extract.context_recovery extracted.jsonl \
  -o context-recovered.jsonl --audit context-recovery-audit.tsv
```

`gate.status == accepted` means the assertion is safe for the layered OWL build. Reusable PO–PATO
traits and manifestations go into FLOPO. Every distinct complete phenotype expression—including
source-specific intervals and arbitrary disjunctions—receives a stable `FAC_` class IRI in the
separate annotation extension. The source module retains provenance and modality and links to that
IRI; it does not repeat the expression. A finite numerical flora range is a PATO
attribute phenotype with a datatype/unit restriction, not a measurement event. `usually`, `often`,
and other qualified claims are retained as SIO-aligned meta-level assertion individuals and are not
silently promoted to universal taxon axioms. Cardinality still requires review. Negation is
accepted only when its `quality` or `absence` scope is explicit and is rendered at that exact OWL
scope. See [`ANNOTATION_MODEL.md`](ANNOTATION_MODEL.md).
The deterministic extractor recognizes frequency, epistemic, approximation, and degree cues as
separate axes and retains their exact spelling. It attaches named ENVO/application seasons and
calendar-month ranges only within the same local clause; it does not infer hemisphere or turn the
French auxiliary phrase `a été` into a summer context.

The value-extension build is governed by
`config/flopo_value_candidates.tsv` (the reviewed source values),
`config/flopo_value_pato_mappings.tsv` (provisional FLOPO values replaced by permanent
PATO terms), `config/flopo_value_id_registry.tsv` (stable identifiers), and
`config/flopo_value_axioms.tsv` (reviewed local axioms and definitions).
It produces `ontology/flopo-value-extensions.tsv` and
`ontology/flopo-value-extensions.ttl`; the release update command embeds that generated module
in the actual `ontology/flopo.owl` artifact and then the registry command reserves its identifiers.
In particular, an “A or B” flora value is an anonymous `owl:unionOf` class description on the
right-hand side of an `FAC_` equivalent-class axiom in the annotation extension. It is never
translated into conjunctive `is_a` axioms and is not minted as a reusable FLOPO class merely
because it occurs in one treatment. JSONL and SQLite use `phenotype_class_iri` as the semantic
annotation target; `value_operator` and the other decomposed fields are derivation and QC data.

The botanical hierarchy is governed by
`curation/flopo_top_level_and_local_extension_proposals.tsv`,
`config/flopo_botanical_id_registry.tsv`, and `curation/curator_approvals.tsv`.
Its generated source is `ontology/flopo-botanical-extension.ttl`; the actual release imports the
pinned GO 2026-06-15 root module and embeds the approved classes. The separate
`ontology/flopo-pubescent-migration.ttl` preserves every incorrect old identifier as an obsolete
annotation shell with `IAO:0100001` pointing to a newly minted EQ class using PATO:0001320.

Network note: `taxon/normalize.py` calls the public GNparser + Global Names Verifier APIs (no
local binary). `OPENROUTER_API_KEY` is read by the Phase 5 extraction engines (not yet built).
ROBOT is installed locally as `bin/robot` backed by `tools/robot.jar`.
