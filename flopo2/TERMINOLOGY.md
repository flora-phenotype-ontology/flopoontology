# Botanical terminology layer

FLOPO extraction uses a terminology-first, context-second workflow. Botanical glossary entries are
aligned once to PO, PATO, or FLOPO, then detected as source spans before the LLM binds entities to
qualities. The alignments are soft evidence: the extractor can reject a candidate, construct a
compound, preserve an alternative, or leave a term unmapped.

At runtime the complete PO and PATO label/synonym catalog and the labels, definitions, hierarchy,
and scoped synonyms from the released `ontology/flopo.owl` are layered under the glossary registry,
so an ontology term need not occur in a bundled glossary to be recognized. OBO synonym scope is
enforced: RELATED/BROAD/NARROW forms are useful for curation, but are withheld as normalization
answers. FLOPO forms enter as phenotype candidates rather than PO entities or PATO qualities.
Retrieval-only candidates must also clear the configured score threshold before entering the
extraction prompt. The streaming RDF/XML reader recognizes both `owl:Class` elements and
`rdf:Description` elements explicitly typed as `owl:Class`; untyped annotation subjects do not
become normalization targets merely because their identifier occurs in the registry.

## Durable and derived artifacts

- `config/terminology_sources.tsv` is the source/version/license manifest. A source must be enabled
  explicitly; definitions are copied into derived artifacts only when the manifest says they are
  redistributable.
- `config/botanical_terminology.tsv` is the versioned, reviewable registry. Stable `BTERM` IDs,
  mappings, relations, confidence, provenance, review state, logical components, and corpus
  frequencies live here.
- `ontology/botanical-terminology.sssom.tsv` is the reviewed one-to-one SSSOM projection.
  Compositional entries stay authoritative in the registry; their component links are exported as
  related mappings with an explicit `one_of` or `all_of` comment.
- `curation/FLOPO_TOP_LEVEL_REVIEW.md` and its companion TSV are a review-only design for FLOPO's
  bearer-centric phenotype hierarchy, separate PATO-quality and GO-process support vocabularies,
  local support classes, and term-stability policy. They do not change the released ontology or
  reserve identifiers.
- `curation/botanical_colour_prototypes.tsv` records source-qualified botanical recognition
  criteria. It distinguishes physical chart chips and historical standards from non-normative
  display RGB approximations.
- `curation/BOTANICAL_COLOUR_SENSU_REVIEW.md` and its companion TSV propose open generic colour
  umbrellas for unqualified annotations and operational `sensu` subclasses for named standards.
  Generic umbrellas are not finite unions of the currently reviewed standards.
- Search structures and queues under `scratchpad/` are reproducible derivatives, not sources of
  truth.

The current registry schema supports entity, quality, value, and ambiguous terminology but not a
GO process role. Before process annotations are enabled, add an explicit `process` semantic role,
permit `GO` as a target namespace, and load a pinned GO biological-process module. A process term
selects a GO target; any altered rate, timing, or duration remains a PATO process-characteristic
filler in the composed FLOPO phenotype.

The bundled glossary sources currently contribute FNA/OTO categories, botanical attribute names,
an English–French lexicon, organ-specific vocabularies, Flora du Gabon glossaries, and reviewed
FLOPO/PATO value mappings. UPOV TGP/14, the NYBG vascular-plant glossary, and NSW PlantNET are
listed but disabled until their versions and reuse terms have been audited. TRY is disabled because
the bundled workbook is a species-state table, not a terminology glossary.

## Build, inspect, and curate

```bash
python -m flopo2.terminology.cli sources
python -m flopo2.terminology.cli build
python -m flopo2.terminology.cli annotate \
  "greenish or pinkish flowers with creamy petals" --language en --organ flower
python -m flopo2.terminology.cli coverage segments.jsonl \
  -o scratchpad/terminology-coverage.json --update-frequencies
python -m flopo2.terminology.cli review-queue \
  -o scratchpad/terminology-review.tsv
python -m flopo2.terminology.catalog_recovery \
  -o scratchpad/botanical-terminology-catalog-recovery.json
python -m flopo2.terminology.obo_lexicon ont/plant_ontology.obo \
  --ontology PO -o config/po_lexicon.tsv
python -m flopo2.terminology.obo_lexicon ont/quality.obo \
  --ontology PATO -o config/pato_lexicon.tsv
python -m flopo2.terminology.measurement_recovery segments.jsonl \
  -o scratchpad/measurement-recovery.json
python -m flopo2.terminology.evidence \
  --summary-out scratchpad/botanical-evidence-validation.json
python -m flopo2.terminology.proposal_validation \
  --summary-out scratchpad/botanical-proposal-validation.json
python -m flopo2.owl.pubescent_migration \
  -o scratchpad/pubescent-migration-review.tsv \
  --summary-out scratchpad/pubescent-migration-review.json
```

Freeze a proposal baseline before an ontology audit, validate every independent run against that
same baseline and pinned current ontology artifacts, then generate a surface-by-surface curator
comparison:

```bash
python -m flopo2.terminology.audit \
  -o scratchpad/botanical-terminology-baseline/manifest.json
python -m flopo2.terminology.validate_audit scratchpad/claude-audit/run-01 \
  --baseline-manifest scratchpad/botanical-terminology-baseline/manifest.json \
  --ontology-obo scratchpad/sources/po-current.obo \
  --ontology-obo scratchpad/sources/pato-current.obo
python -m flopo2.terminology.compare_audits scratchpad/claude-audit/run-0{1,2,3} \
  --baseline-manifest scratchpad/botanical-terminology-baseline/manifest.json \
  -o scratchpad/claude-audit/curator-comparison.tsv \
  --summary-out scratchpad/claude-audit/curator-comparison.json
python -m flopo2.terminology.mapping_validation \
  --baseline-manifest scratchpad/botanical-terminology-baseline/manifest.json \
  --po-obo scratchpad/sources/po-current.obo \
  --pato-obo scratchpad/sources/pato-current.obo \
  -o scratchpad/botanical-terminology-baseline/mapping-validation.tsv \
  --summary-out scratchpad/botanical-terminology-baseline/mapping-validation.json
python -m flopo2.terminology.curation_table \
  --mapping-report scratchpad/botanical-terminology-baseline/mapping-validation.tsv \
  --proposals curation/botanical_concept_proposals.tsv \
  --evidence-manifest curation/botanical_evidence.tsv \
  -o scratchpad/botanical-terminology-baseline/curator-decision-table.tsv \
  --summary-out scratchpad/botanical-terminology-baseline/curator-decision-table.json
```

The validator requires numeric confidence, known target identifiers, no curator attribution on
machine proposals, and an exact duplicate-free, disjoint partition of all frozen surfaces across
the mapping and gap/noise tables. The comparator canonicalizes OBO CURIE syntax but otherwise
reports differing relations, targets, or gap decisions as disagreements rather than choosing one.

The coverage report separates any retrieved candidate from an eligible candidate and from a
reviewed/automatic exact mapping. Use `trusted_mention_rate`, not the much looser
`mention_mapping_rate`, when deciding how much of a flora is already normalized.

Mapping validation reads the pinned PO and PATO OBO files directly rather than the repository's
legacy TSV lexicons. Obsolete terms remain visible for diagnostics but cannot become candidates;
formal OBO synonym scope is preserved, PO editorial suffixes such as `(narrow)` are removed from
the searchable literal, and explicitly non-English synonyms are excluded from the English index.
The generated curator table is complete for the frozen missing-surface set and leaves every
`curator_decision` blank.

OAK `lexmatch` is used as an independent exact-lexical retrieval check, not as an authority for
mapping direction. On the 436-surface frozen audit it recovers 87/91 scope-preserving lexical pairs
(95.60% pair recall) with its default case/whitespace normalization. Its four misses are
hyphen-versus-space variants. Adding the explicit, versioned
`config/oak_botanical_lexmatch_rules.yaml` hyphen rule recovers 91/91 pairs. OAK emits a generic
`skos:closeMatch` for all of these, so the ontology's preferred-label and OBO synonym scope still
determine whether a candidate is exact, broad, narrow, or related and whether it is eligible.

The proposal schema also permits `intended_ontology=NONE` with
`recommendation=reject_as_noise`. This means that the inspected corpus occurrence is outside the
phenotype task, not that the token is globally forbidden: habitat geology, locality phrases, and
population abundance are rejected only under their verified constructions. Likewise, isolated
suffixes such as `stemmed` and degree adverbs such as `sparsely` are retained as compositional
evidence for their full phrase instead of being mistaken for missing atomic ontology terms.

Grounding TSVs are deterministic derivatives of the checked-in OBO sources. Regenerate them with
`obo_lexicon` whenever PO or PATO is refreshed; the builder excludes obsolete and explicitly
non-English terms, cleans editorial synonym-scope suffixes, retains formal scope in the OBO source,
and produces byte-identical output on repeated runs.

Changes to the runtime form catalog can alter longest-span segmentation, so compare both end-to-end
coverage and recovery on the old fixed mention spans. Adding released FLOPO exact forms recovered
812 previously ineligible Saudi mentions on fixed spans in the 2026-07-14 baseline; the end-to-end
eligible rate changed from 52.61% to 55.89% because longer FLOPO forms also merged some spans.

Curators fill `curator_decision` in the review queue with `accept`, `unmapped`, or `reject`, edit
the proposed target/relation/components where needed, and apply it explicitly:

```bash
python -m flopo2.terminology.cli apply-review scratchpad/terminology-review.tsv \
  --curator-orcid 0000-0001-8149-5890 --date 2026-07-14
python -m flopo2.terminology.cli sssom
```

The optional adjudicator can populate proposals but can never mark them reviewed:

```bash
python -m flopo2.terminology.cli adjudicate --limit 100 \
  --model openai/gpt-oss-120b -o scratchpad/terminology-proposed.tsv
```

## Mapping policy

- Primary labels and OBO `EXACT` synonyms may receive deterministic `auto` mappings.
- OBO `RELATED`, `BROAD`, and `NARROW` synonym scopes are retained as non-exact SKOS relations and
  require review. In particular, `palmate` is not collapsed to PATO `digitate`.
- Glossary categories and part-of-speech information determine whether candidates come from PO or
  PATO. Organ-specific placement is a ranking feature, not a hard restriction.
- Parallel English–French entries transfer an established candidate as a `proposed` close match;
  translation alone never produces a reviewed mapping.
- Unions and compounds live in FLOPO. `A or B` is `one_of`; it is emitted in OWL using
  `owl:unionOf`. `all_of` uses separate `has quality some` restrictions. Neither is translated into
  multiple conjunctive PATO `is_a` axioms.
- Proposed new atomic colour values require a referenced operational range or prototype. Circular
  definitions such as “a colour described as creamy” are not acceptable.
- Scalar adjectives next to a number and unit are parsed as measurements of the corresponding
  PATO attribute, not as categorical increased/decreased values. The deterministic parser requires
  number + recognized length unit + an English/French attribute cue, normalizes the unit against
  UO, and retains an exact source span. It deliberately rejects context-free readings such as
  `wide plain`, `high altitude`, and `large grove`.

`measurement_recovery` reports this grammar separately from ontology normalization. A recovered
measurement cue is not yet a complete phenotype assertion: the number, unit, and PATO attribute
are grounded, but a contextual PO bearer still has to be linked and validated.

Botanical `pubescent` is a known lexical homonym in PATO. `PATO:0000455` denotes sexual puberty;
the botanical pilosity concept is `PATO:0001320`, defined by coverage with short hairs or soft
down. Runtime grounding has an explicit botanical override. Because substituting the PATO class
changes the existing classes' formal referents, the migration command proposes an
obsolete-and-replace operation rather than an in-place signature edit. It produces a blank-decision
curator table with exact replacement links, checks that every affected registry signature has a
corresponding restriction in the released OWL, and never edits or reserves identifiers in the
ontology.

Ordinary anatomy words also require corpus-aware synonym handling. In the Saudi material, plural
`hairs` denotes trichomes but singular `Hair` is a place name, and nearly every `frond(s)` mention
denotes a palm leaf rather than a fern leaf. Candidate PO extensions therefore carry downloaded,
checksum-pinned definitions and explicit taxonomic or bearer caveats; a NARROW synonym is promoted
to a subclass only when a distinguishing definition is available. Botanical `hair` has no such
differentia in the checked glossaries, so its synonym scope is proposed for revision rather than
inventing a subclass.

## Evaluation

Create a 400-term normalization template with equal corpus-attested and glossary-only halves.
Sampling balances source and language first, then semantic role/category within each slice:

```bash
python -m flopo2.terminology.cli sample-alignment-gold \
  -o scratchpad/terminology-gold-400.tsv --corpus-n 200
python -m flopo2.terminology.cli evaluate scratchpad/terminology-gold-400.tsv
```

The normalization gate is candidate recall@10 >= 0.95 and precision >= 0.95 among mappings eligible
for automatic acceptance. Extraction must be evaluated separately; a higher assertion count is not
evidence of correctness.

The controlled extraction ablation runs four configurations with the same model and input:

1. PO/PATO labels only (`off`);
2. ontology labels, definitions, and hierarchy (`ontology`);
3. glossary registry used for grounding without prompt annotations (`registry`);
4. full terminology-guided extraction (`full`).

```bash
python -m flopo2.terminology.ablation --silver gold/gold_standard_100.jsonl \
  --model openai/gpt-oss-120b --lenient -o gold/terminology_ablation.json
```

Adoption requires at least +0.05 exact EQ F1, no hallucination-rate increase, and no language slice
losing more than 0.02 F1. The Saudi low-yield review sample is generated under `scratchpad/` so the
copyrighted source descriptions are not accidentally committed.
