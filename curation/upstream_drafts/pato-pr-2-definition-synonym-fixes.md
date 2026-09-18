# DRAFT pull request: PR 2, PATO: definition and synonym fixes (rows 54, 72, 73, 74, 100, 116, 129)

- Target repository: `pato-ontology/pato`
- Status: opened 2026-09-18 as https://github.com/pato-ontology/pato/pull/620 (drooping fix split out as https://github.com/pato-ontology/pato/pull/619) (curator decision D2). The submitted text was revised from the draft below; see SUBMITTED.md.
- Source: `scratchpad/qwen-concept-proposal-review-20260917/CURATOR_PACKET.md`; decisions recorded in `curation/botanical_concept_proposals.tsv` and `curation/curator_approvals.tsv`.

## Rows

| packet row | proposal | decision | label | parent | provisional FLOPO bridge |
|---|---|---|---|---|---|
| 54 | `PATO-CAND:botanical_pubescent` | accept | pubescent hair | PATO:0001320 (existing; synonyms only) |  |
| 72 | `MAP-CAND:arching_arched` | accept | arched | PATO:0001594 |  |
| 73 | `MAP-CAND:botanical_sessile` | accept_with_revision | sessile (sensu botany) | PATO:0001436 |  |
| 74 | `MAP-CAND:scented_odorous` | accept | odorous | PATO:0001331 |  |
| 100 | `PATO-CAND:striped_colour_pattern` | defer | striped |  |  |
| 116 | `PATO-CAND:nodding` | defer | nodding |  |  |
| 129 | `MAP-CAND:lax_loose` | accept | loose | PATO:0001802 |  |

## Body

This PR contains small corrections, and no term is added or removed. (1) The definition of sessile (sensu botany) (PATO:0001436) says "inhering in a flower" but then glosses "as in flowers or leaves". It is replaced with a bearer-independent attachment definition, and the bare synonym "sessile" is added only as RELATED because sessile (sensu zoology) (PATO:0001437) shares the word. (2) The ungrammatical drooping (PATO:0002165) definition "To bent or hang downwards" is replaced; the text is already drafted in `pato-drooping-pr-body.md`. (3) Banded (PATO:0001946) is defined by *transverse* stripes but carries "striped" as EXACT. This PR downgrades it to RELATED. (4) The botanical synonyms "pubescent (sensu botany)" and "downy" (RELATED) are added to pubescent hair (PATO:0001320). This addresses a documented homonym hazard: FLOPO had annotated 154 plant phenotypes to the puberty quality pubescent (PATO:0000455). (5) Inflectional botanical synonyms are added: "arching" to arched (PATO:0001594), "scented" to odorous (PATO:0001331), and "lax" (RELATED) to loose (PATO:0001802). The PATO parent of each touched term is unchanged.

## Appendix: drooping definition fix (separate PR body already drafted)

Title: Fix malformed definition of drooping (PATO:0002165)

The definition of `drooping` (PATO:0002165) currently reads:

> To bent or hang downwards.

This is ungrammatical and is not a genus-differentia definition. This PR replaces it with:

> A shape quality inhering in a bearer by virtue of the bearer's bending or hanging downwards.

The genus matches the asserted parent `shape` (PATO:0000052). The label, the exact synonym `sagging`, the subset, the definition cross-reference, and the classification are unchanged.

Context: found while reviewing botanical term proposals for the FLOPO v2 rebuild, where `nodding` is a candidate subtype of `drooping` and `pendent` (PATO:0104035) is its orientation counterpart. Whether `drooping` belongs under `shape` or `orientation` is a separate question and deliberately not touched here.

Local validation:
- `robot convert -i src/ontology/pato-edit.obo -o /tmp/pato-edit-check.owl` passed.
- `git diff --check` passed.
