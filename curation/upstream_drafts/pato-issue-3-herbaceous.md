# DRAFT issue: Issue 3, PATO: `herbaceous` (PATO:0002352) conflates die-back with non-woodiness (row 46; also affects row 21)

- Target repository: `pato-ontology/pato`
- Status: opened 2026-09-18 as https://github.com/pato-ontology/pato/issues/621 (curator decision D2). The submitted text was revised from the draft below; see SUBMITTED.md.
- Source: `scratchpad/qwen-concept-proposal-review-20260917/CURATOR_PACKET.md`; decisions recorded in `curation/botanical_concept_proposals.tsv` and `curation/curator_approvals.tsv`.

## Rows

| packet row | proposal | decision | label | parent | provisional FLOPO bridge |
|---|---|---|---|---|---|
| 46 | `FLOPO-CAND:herb` | accept_with_revision | whole plant herbaceous | FLOPO:0900032 (FLOPO:0022142 existing) |  |
| 21 | `FLOPO-CAND:vine` | accept_with_revision | whole plant vine phenotype | FLOPO-CAND:climber (new FLOPO ID) | FLOPO:0985032 |

## Body

PATO:0002352 herbaceous sits under shedability and is defined as upper parts dying back to the rootstock. In botany, "herbaceous" and "herb" usually mean *not woody*, which includes annual herbs that have no rootstock. Annotations that follow the label therefore assert die-back where the source only says the plant is non-woody. We propose either an explicit non-woody quality (for example "non-ligneous", the complement of ligneous, PATO:0002348) with herbaceous as a synonym, or a relabel of PATO:0002352 to make the die-back sense explicit. We ask PATO editors which they prefer.
