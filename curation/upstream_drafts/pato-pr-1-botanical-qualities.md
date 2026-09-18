# DRAFT pull request: PR 1, PATO: add 17 botanical morphology, indumentum and life-span qualities (rows 1, 2, 3, 76, 77, 78, 79, 80, 81, 82, 84, 85, 103, 121, 122, 164, 222)

- Target repository: `pato-ontology/pato`
- Status: opened 2026-09-18 as https://github.com/pato-ontology/pato/pull/618 (curator decision D2). The submitted text was revised from the draft below; see SUBMITTED.md.
- Source: `scratchpad/qwen-concept-proposal-review-20260917/CURATOR_PACKET.md`; decisions recorded in `curation/botanical_concept_proposals.tsv` and `curation/curator_approvals.tsv`.

## Rows

| packet row | proposal | decision | label | parent | provisional FLOPO bridge |
|---|---|---|---|---|---|
| 1 | `PATO-CAND:campanulate` | accept | campanulate | PATO:0000052 | FLOPO:0985000 |
| 2 | `PATO-CAND:filiform` | accept_with_revision | filiform | PATO:0000052 | FLOPO:0985001 |
| 3 | `PATO-CAND:hastate` | accept | hastate | PATO:0000052 | FLOPO:0985002 |
| 76 | `PATO-CAND:reflexed` | accept | reflexed | PATO:0000617 | FLOPO:0985003 |
| 77 | `PATO-CAND:winged` | accept | winged | PATO:0000052 | FLOPO:0985004 |
| 78 | `PATO-CAND:ascending` | accept_with_revision | ascending | PATO:0002481 | FLOPO:0985005 |
| 79 | `PATO-CAND:spreading` | accept | spreading | PATO:0000133 | FLOPO:0985006 |
| 80 | `PATO-CAND:lanate` | accept | lanate | PATO:0000454 | FLOPO:0985007 |
| 81 | `PATO-CAND:sericeous` | accept | sericeous | PATO:0000454 | FLOPO:0985008 |
| 82 | `PATO-CAND:entire_margin` | accept_with_revision | entire | PATO:0001975 | FLOPO:0985009 |
| 84 | `PATO-CAND:annual_life_span` | accept | annual life span | PATO:0000050 | FLOPO:0985010 |
| 85 | `PATO-CAND:perennial_life_span` | accept_with_revision | perennial life span | PATO:0000050 | FLOPO:0985011 |
| 103 | `PATO-CAND:dissected` | accept_with_revision | dissected | PATO:0001786 | FLOPO:0985012 |
| 121 | `PATO-CAND:clasping` | accept_with_revision | clasping | PATO:0000140 | FLOPO:0985013 |
| 122 | `PATO-CAND:mealy_surface` | accept | mealy | PATO:0000150 | FLOPO:0985014 |
| 164 | `PATO-CAND:plicate` | accept | plicate | PATO:0001910 | FLOPO:0985015 |
| 222 | `PATO-CAND:floccose_cottony` | accept | floccose | PATO:0000454 | FLOPO:0985016 |

## Body

This PR adds 17 qualities that flora descriptions use constantly and that PATO lacks. Shapes: campanulate, filiform, hastate and winged under shape (PATO:0000052); dissected under split (PATO:0001786); plicate under folded (PATO:0001910); reflexed under bent (PATO:0000617); entire under unserrated (PATO:0001975). Positions and orientations: ascending under oblique orientation (PATO:0002481), spreading under orientation (PATO:0000133), clasping under position (PATO:0000140). Indumentum: lanate, sericeous and floccose under hairy (PATO:0000454), and mealy under texture (PATO:0000150). Life span: annual life span and perennial life span under life span (PATO:0000050), with explicit one-year and more-than-two-year boundaries. Every term has a bearer-independent genus-differentia definition whose genus matches its parent, and each is cited to a pinned glossary (UPOV TGP/14, NYBG, PlantNET, Flora of Australia). Near neighbours are separated explicitly rather than merged. Hastate is not sagittate (PATO:0001881). Reflexed is neither recurved (PATO:0002211) nor retrorse (PATO:0002237). Dissected is neither cut (PATO:0001978) nor lobed (PATO:0001979). Spreading is neither radiating (PATO:0005005) nor divergent from (PATO:0002424). Lanate is not tomentose (PATO:0002341). Ambiguous vernacular words (woolly, silky, pleated, cottony, amplexicaul) enter only as RELATED or NARROW synonyms. The terms come from a 436-surface gap analysis of a Saudi flora corpus for the FLOPO v2 rebuild; FLOPO will carry provisional local IDs until these are merged.

## Migration note

FLOPO carries the provisional bridge classes listed above in `ontology/flopo-botanical-extension-2.ttl` (identifier block FLOPO:0985000-0985999). When the upstream ontology assigns identifiers, obsolete each bridge with `IAO:0100001` (term replaced by) pointing to the new PO/PATO term and update mappings; no PO or PATO identifier is minted locally.
