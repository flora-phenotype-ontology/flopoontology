# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

FLOPO (the Flora Phenotype Ontology). The repository holds two things: (1) a set of
standalone Groovy scripts that mine plant phenotypes from digitized flora descriptions
and assemble them into an OWL ontology, and (2) the released ontology artifacts. The
ontology is CC-0; the code is BSD (see `LICENSE` and `LICENSE-ontology.txt`).

There is **no build system** — no `pom.xml`, `build.gradle`, or test suite. Each `.groovy`
file is an independent script run from the repo root. Most read/write fixed filenames or
take positional `args`, and are meant to be run in sequence as a pipeline (see below).

## Running scripts

Scripts run with the system `groovy` from the repo root:

```bash
groovy MakePlantPhenotypeOntology.groovy -i eq.txt -o plantphenotype.owl -a annotations.txt
groovy DeprecateDumbClasses.groovy        # reads ontology/flopo.owl, writes /tmp/flopo-clean.owl
```

Dependency handling is inconsistent and matters when editing:
- `DeprecateDumbClasses.groovy` and `GenerateLuceneIndexEnglishSolana.groovy` declare deps
  via `@Grab`/`@Grapes` (OWLAPI 4.1.0, ELK 0.4.2, groovycsv) — these self-resolve.
- All other scripts have **no `@Grab`** and assume the libraries are already on the Groovy
  classpath (OpenNLP, Apache Lucene 4.7, LingPipe/`com.aliasi`, OWLAPI, ELK, commons-io).
  Running them requires that classpath to be configured externally (e.g. `~/.groovy/lib`).
- `MakePlantPhenotypeOntology.groovy` parses `args` with `CliBuilder` (`-i -o -a [-t]`);
  scripts like `ExtractLabels`, `AddLabelToAnnotations`, `MakeFuncInput`, `MakeNexusFile`
  read bare positional `args[n]` (TSV files). Read the top of a script before running it.

## Pipeline architecture

The scripts form a text-mining → ontology-construction → analysis pipeline. Understanding
the flow matters because intermediate files are passed between stages by filename.

1. **Source ontologies** live in `ont/` as OBO (`plant_ontology.obo` = PO entities,
   `quality.obo` = PATO qualities, plus GO/trait/unit). Scripts parse these line-by-line
   (matching `id:`/`name:`/`synonym:`/`is_a:` prefixes) rather than with an OWL library.

2. **Source flora** are FlorML/XML descriptions in `flora-gabon/`, `flora-malesiana/`,
   `flora-central-africa/`, `floras*/`. `glossary/` holds lexicons; `models/` (and the
   duplicated `en-*.bin` at the root) hold OpenNLP English/French sentence/token/pos/chunk
   models.

3. **Entity–quality extraction** — two implementations of the same idea:
   - `ParseFloraFile.groovy` is the original (pro-iBiosphere Leiden hackathon) NER pass:
     OpenNLP + dictionary lookup against `ont/`, emitting `eq.txt` (entity/quality pairs)
     and `missing-*.txt` reports.
   - The Lucene-based refactor: `GenerateOntologyIndex` → `GenerateLuceneIndex[English|
     French|Solana]` build indexes, then `QueryLuceneIndex*` and `GenFeaturesFromCooccurrences*`
     extract phenotype features.

4. **Ontology construction** — `MakePlantPhenotypeOntology.groovy` is the core: it reads the
   EQ file plus PO + PATO from `ont/` and emits the phenotype ontology (`plantphenotype.owl`
   / FLOPO) and a separate FLOPO annotation file. `-t` adds taxa as subclasses of phenotypes.

5. **Reasoning / cleanup** — `DeprecateDumbClasses.groovy` runs the ELK reasoner over
   `ontology/flopo.owl`, finds classes equivalent to `owl:Nothing`, and marks them
   `owl:deprecated`. Run this after adding any axiom (e.g. a GCI like
   `has-part some (owl:Thing and has-quality some 'process quality') SubClassOf owl:Nothing`)
   that can render classes unsatisfiable.

6. **Downstream analysis** — `ExtractLabels` (OWL → id↔label TSV), `AddLabelToAnnotations`
   (joins labels into the annotation file), `MakeFuncInput` + `FindEnrichedCategoriesInFuncOutput`
   (functional enrichment), `MakeMakeNexusFileInput` + `MakeNexusFile` (phylogenetic NEXUS export).

## Ontology files and IRIs

- `ontology/` holds the released ontology: `flopo.owl` (main), `flopo-inferred.owl` (with
  reasoning materialized), `flopo-obo.owl`, `flopo-orig.owl`.
- Root-level `flopo-classified.owl`, `flopo-unclassified.owl`, `plantphenotype.owl` are
  generated artifacts (pipeline output), not hand-edited sources.
- `catalog-v001.xml` maps ontology IRIs to local files for offline OWL loading (Protégé/OWLAPI).
- Two IRI namespaces are in play: pipeline-generated classes use
  `http://phenomebrowser.net/plant-phenotype.owl#`; released FLOPO terms use the OBO PURL
  `http://purl.obolibrary.org/obo/FLOPO_<n>` (`flopo.yml` is the PURL config; terms resolve
  via aber-owl.net). Several scripts strip the `phenomebrowser.net` prefix when emitting IDs.

## flopo-database/

A **nested separate git repository** (not a submodule of this one) containing plant trait
data annotated with FLOPO, plus its own normalization scripts (`NormalizeSpecies.groovy`,
`NormalizeAfricanPlants.groovy`). Commit it independently from its own directory.

## Notes

- `.groovy~` files are editor backups — ignore them; edit the `.groovy` files.
- Many data/model files are large binaries (multi-MB `.owl`, `.obo`, `.bin`, `fdac.backup`).
  Avoid reading them whole; grep or stream instead.
