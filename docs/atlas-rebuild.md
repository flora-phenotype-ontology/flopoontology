# Rebuilding the trait atlas after the ontology, the rules or the annotator change

The Qwen transcriptions of a flora do not depend on the ontology. After a FLOPO release, a new
rule table or a new annotation pattern, only the deterministic part runs again: annotation, the
passes that follow it, the checks, the data build and the deploy. No model endpoint is used.

One script does it, `tools/atlas_rebuild/run.sh`:

```bash
NOTE="All floras annotated again with FLOPO 2026-11-24: ..." \
  nohup tools/atlas_rebuild/run.sh > ~/tmp/atlas-rebuild/run.log 2>&1 &
```

`NOTE` is the sentence that goes into the release history (`deploy/atlas/data-releases.tsv`) and is
shown on the site. The script stops at the first step that fails and says why; after the cause is
fixed, `FROM=passes` or `FROM=build` continues from that step. `DEPLOY=0` stops after the build.

## Steps

| Step | What it does | Time (24 Nov 2026, 40 sources, 3.7 million statements) |
|---|---|---|
| backup | copies every `*-annotated.jsonl` to `$BACKUP` | 1 min, 8.4 GB |
| re-annotation | `tools.reannotate_flora` for every flora with a done marker, three at a time; the two Saudi guides with `ncvc_annotate` and `collenette_annotate` | 95 min (Flora of China alone 80 min) |
| position and plant group | `apply_bearer_position` (pattern 04) and `apply_plant_group` (grass-only PO terms in other families go to review) | 5 min |
| bryophyte terms | `apply_bryophyte_terms` (`docs/bryophyte-terms.md`) | 3 min |
| copies | `tools.atlas_duplicates` (`docs/duplicate-descriptions.md`) | 6 min |
| ELK check | `annotation_class_check` on every source (`docs/phene-consistency.md`) | 40 min |
| class expressions | builds the OWL expression of every record once; the data build would fail on the first record that has none, hours in | 10 min |
| build | `python -m flopo2.saudi.build --rebuild-assertions` | 4 to 5 hours |
| deploy | `tools/deploy_atlas.sh --stamp ...` (`docs/atlas-deploy.md`) | 2 to 3 hours |

A source whose full run is unfinished (World Flora Online on 24 November) is not re-annotated; the
passes and the build use the snapshot of it in `local-corpora/saudi-flora/rdf/`, never the live
corpus of the running extraction.

## What the script requires, and why

- **No flora fails and no flora has data-model errors** before the passes start. A flora that
  fails leaves a truncated annotation file; run it again with
  `python -m tools.reannotate_flora NAME` after the fix, then continue with `FROM=passes`.
- **150 GB of free disk** before the build. The build writes about 60 GB of new RDF beside the
  files of the live release, sorting the largest flora needs 27 GB more for a moment, and a release
  is about 86 GB. Releases share files by hard links, so deleting one old release frees nothing
  while another one still links to the same files: `du` on the release directories shows which
  ones go together.
- **Memory**: ws runs with strict overcommit. The script waits for 14 to 45 GB of commit room
  before the steps that need it, up to a day.
- **No deploy is running.** Do not rewrite a corpus while a build reads it.

## What went wrong on 24 November 2026, and what now prevents it

| Failure | Cause | Now |
|---|---|---|
| 26 of 37 floras failed in re-annotation | a reader of the new patterns converted a number slot in which Qwen had written a word ("height") | reader ignores such rows; test in `tests/test_annotation_patterns.py` |
| data-model errors on "style present or absent", "petals 6 or more" | the data-model rule on "or" was stricter than the gate | the rule follows the gate (patterns 19, 20, 23) |
| three accepted "A or B" pairs gave errors | pairs are reviewed on the terms before colour terms are replaced by their FLOPO colour; after it the two values share an attribute, or the pair is one rejected earlier | pairs set to reject in `config/flora_union_pairs.tsv`; check new pairs that contain a colour term |
| build stopped after four hours on a moss record | the bryophyte pass changed leaf to non-vascular leaf and kept the carrier of an arrangement (pattern 16) of the old part | the pass resets the carrier; the class-expression step finds such records in ten minutes |
| build stopped: disk full | 53 GB free was not enough | the 150 GB requirement above |

Open: the carrier tables (`flopo2/owl/carrier.py`) name no whole for a non-vascular leaf, so "leaves
imbricate" in a moss is a quality of the leaf alone (750 records).
