# The Flora Phenotype Ontology (FLOPO), 2016

**Hoehndorf et al., *Journal of Biomedical Semantics* 2016.** The system this project rebuilds.

- Paper: https://link.springer.com/article/10.1186/s13326-016-0107-8
- PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC5109718/
- PubMed: https://pubmed.ncbi.nlm.nih.gov/27842607/
- Local manuscript: `~/Documents/papers/flopo/flopo.tex`

## Method

Used **PO** (Plant Ontology, anatomical entities) and **PATO** (qualities) to extract
**Entity-Quality (EQ)** pairs from digitized taxon descriptions in Floras, then a formal
ontological approach with **phenotype description patterns + automated reasoning (ELK)** to build
the ontology.

**Text mining:** Apache Lucene standard analyzer (stemming, stopword removal) + OpenNLP sentence
tokenization → full-text index of taxon-tagged sentences. Queried for sentences containing both a
PATO label/synonym and a PO label/synonym. French Floras handled by dictionary translation
(Missouri Botanical Garden glossary) before matching. **Stanford parser** verified an attributive
relationship between quality and entity. Result: **502,693 EQ descriptions**, 20,584 distinct
PO×PATO combinations (287 PO structures × 545 qualities), over **26,104 taxa**.

## EQ design pattern (preserve verbatim)

For each pair (E, Q):
- `'E phenotype' EquivalentTo: has-part some ((part-of some E) and has-quality some quality)`
- `'E Q' EquivalentTo: has-part some (E and has-quality some Q)`
- If Q ∈ PATO `value_slim`: T = most specific `attribute_slim` superclass of Q →
  `'E T' EquivalentTo: has-part some (E and has-quality some T)`

Example (flower, red): `flower phenotype`, `flower red`, `flower color`. The `has-part some` prefix
lets simple phenotypes combine into complex ones via intersection (flower and anther are disjoint,
so without the prefix they couldn't combine). `part-of`/`has-part` are reflexive+transitive so
parthood organizes the hierarchy (petal phenotype ⊑ flower phenotype). GCI added to exclude process
qualities: `has-part some (owl:Thing and has-quality some 'process quality') SubClassOf owl:Nothing`.

If classes ever need to be subclasses of `quality`, prefix all patterns with `inheres-in some` — no
change to inferences.

## Scale & properties

25,407 classes (24,076 unique to FLOPO + PO/PATO). IRIs `http://purl.obolibrary.org/obo/FLOPO_<n>`
(e.g. `flower red` = FLOPO:0007599). Properties: has_part=BFO:0000051, part_of=BFO:0000050
(transitive+reflexive), has_quality=RO:0000053. Imports po.owl, pato.owl. CC-0. 198 manually-added
classes (>50% fully defined).

## Limitations (what the rebuild must fix)

- **Coverage 48–70%** of characters per taxon. Misses from exact matching: `truncated`≠`truncate`,
  `ovule`≠`plant ovule` (PO label is "plant ovule"). Missing PATO qualities: `caulescent`,
  `chartaceous`, `axillary`, comparatives (`unequal`, `longer than`).
- **564 classes deprecated** as nonsensical (`xylem vessel member tomentose`, `peduncle female`,
  `lower glume subacute`). Two causes: (1) parsing mis-associates entity/quality in a sentence;
  (2) polysemous PATO terms (`acute` = a process/disease quality, but in plants an angle) propagate
  up the hierarchy yielding junk like `leaf intensity`.
- No values/measurements, no negation/modifiers, no provenance to source sentence.
- 55% match (44,200/80,887) to the "African Plants" photo-guide trait DB; only 315/5,186 direct
  matches to model-organism (Arabidopsis/maize/etc.) phenotypes (rest had superclasses).

## Stated future work (this project delivers much of it)

CharaParser evaluation; **IPNI linking + Linked Open Data** publication of taxon annotations;
PROV-O / BCO / PEAO / EDAM provenance; **EnvO + environmental NER** for habitat (noted as harder
than morphology); mappings to **Plant Trait Ontology**, Crop Ontology, Plant Trait Thesaurus.
