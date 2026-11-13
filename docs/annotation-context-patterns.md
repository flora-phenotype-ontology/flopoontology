# Context, disjunction and relation patterns in the flora annotations

Review of 2026-11-13 of what the flora pipeline (`flopo2.ingest.ncvc_annotate`) transcribes but
does not yet annotate, over the 38 external floras (4.9 M transcribed rows, 3.1 M annotated).
Counts are rows; the sub-pattern counts come from regular expressions over the transcribed
phrase and are estimates.

## What is already represented

| Source wording | Representation |
|---|---|
| white, pink or purple | union of values of one attribute: `value_operator: one_of` (`alternatives_as_union`) |
| ovate to lanceolate; linear-lanceolate | continuum: reified `qualitative_value_relation` between the two values |
| white becoming pink | temporal transition: `qualitative_value_relation` |
| often, rarely | `frequency_qualifier` with its cue |
| greenish (colour), suborbicular | the value with `value_qualifier: approximately` |
| no petals, leafless | negation (`negated`, `negation_scope`) |

## 1. The transcriber's `stage` qualifier (392,644 rows)

Every row with a `stage` qualifier was left unannotated (`developmental_stage_context`). The
qualifier holds six different things:

| | Kind | Rows | Examples | Representation | Status |
|---|---|---:|---|---|---|
| A | growth stage of the part, or its state | 117,944 | in fruit, at anthesis; when young, at maturity | `developmental_stage_contexts` (a PO stage, `present_during`) for stages; `bearer_context_qualities` (a PATO quality of the same bearer: young, mature, old) for states | **implemented 2026-11-13** (`config/flora_context_words.tsv`) |
| A2 | other stage wording | 22,266 | after flowering, in the second year, soon | as A; needs more table rows, and `before`/`after` relations to a stage (the model has `present_during` only) | table to extend |
| B | sex or morph of the flower | 8,092 | male, pistillate, in short-styled flowers | on a flower, inflorescence or plant: `bearer_context_qualities` (PATO male/female) — implemented with A. On a part ("calyx of male flowers"): the part is `part_of` a flower that has the quality — needs slot 1 below | partly implemented |
| C | place on the part | 104,448 | above, beneath, at the base, inside, on the veins | the quality inheres in a part of the bearer — slot 1 below | **implemented 2026-11-13** for the reviewed surfaces and regions |
| D | which member of a series | 51,763 | basal, cauline, inner, outer, upper | a position quality of the bearer itself: `bearer_context_qualities` with the FLOPO position values (basal FLOPO:0991002, cauline FLOPO:0991117, ...); the slot accepts PATO classes only and must accept FLOPO values | designed |
| E | condition of the specimen | 20,217 | when dry, in sicco, when fresh | not a quality of the living plant: an annotation-level qualifier — slot 2 below | designed |
| F | other | 67,914 | mixed: taxon names of varieties, habitats, free text | to be sampled | open |

A reading is used only when the context word stands, once, in the clause of the annotated span;
its offsets are stored as the cue (`stage_text`, `start`, `end`), so the data-model gate can check
it against the source.

### Slot 1: the part of the bearer (kind C) — implemented 2026-11-13

"Leaves glabrous beneath" says that the abaxial surface of the leaf is glabrous. The model had the
slot already (`bearer_scope` and `part_restrictions`, schema extension E3, curator decision of
2026-09-18: *PO first, then pinned BSPO, never free text*; `flopo2.annotation.positional`); the
flora annotator did not use it. `plan_bearer_scope` now applies those rules to the reviewed
context words (kinds `surface` and `region` of `config/flora_context_words.tsv`):

- a **surface** of a dorsiventral organ is PO's epidermis class of that side and replaces the
  bearer (leaf lamina abaxial epidermis PO:0000049; `bearer_scope.mode = substituted_bearer`),
  for colours, hairs and smooth/rough only; "inside"/"outside" only on single perianth members
  and bracts;
- a **region** is PO's apex, base or margin class of the organ where PO has one (leaf apex,
  petal base, stem base);
- otherwise the organ stays the bearer and the value is stated of a pinned BSPO region of it
  (apical, basal, proximal, distal region, margin) as a `part_restrictions` filler; the
  top-level quality is the value itself only when the part entails it for the organ (hairs at
  the base: the organ is hairy), else its attribute ("filaments white at base": the stamen
  filament has a colour, and a basal region that is white).

"above"/"below" are a side of a leaf and the upper/lower part of a stem; the table tells them
apart by the bearer. A cue across an alternative ("involute or expanded at the base") is left
alone. Kind B on a part ("calyx of male flowers") still needs a bearer that is part of a
qualified whole and is open.

### Slot 2: `specimen_condition` (kind E)

`{"specimen_condition": "dry", "condition_text": "when dry", "start": .., "end": ..}`. The
assertion is exported with the condition as an annotation and is **not** linked to a FLOPO class
and not used by the identification key unless the reader asks for dried-specimen characters:
"black when dry" is not "black".

## 2. Alternatives and continua that stay unresolved (270,178 rows)

`taxon_level_alternatives_or_continuum` 132,269, `atomic_clause_contains_disjunction` 81,618,
`explicit_disjunction` 56,291. The union and continuum patterns exist; these rows miss them for
four reasons.

| Cause | Rows (est.) | Example | Way to represent |
|---|---:|---|---|
| a value of the list has no term | most | "nodding or erect" (nodding had no rule) | none needed: each term or rule added in the candidate review releases its rows on re-annotation |
| values under different attributes | — | "woody or fleshy", "sessile or shortly stalked" | allow the union over full statements instead of over values: `value_operator: one_of` with `operands`, each a (quality, value) of the same bearer; OWL `has_characteristic some (Q1 or Q2)` holds for any two qualities. The same-attribute rule stays for the **continuum**, which needs comparable values |
| an extreme in parentheses | 22,331 | "3-8(-11) cm", "(5-)7-15(-20)" | measurement with the usual range in `value_low`/`value_high` and the extremes in new `value_min_extreme`/`value_max_extreme`; the class and the key use the usual range |
| "±" before the value | 5,907 | "± erect" | the value with `value_qualifier: approximately` and "±" as cue (as for "sub-") |
| an alternative with its own frequency | 5,457 | "dioecious or rarely monoecious" | `one_of` operands, the second with `frequency_qualifier: rarely` |

## 3. Relations to another part (30,766 rows, and part of the above)

| Pattern | Rows (est.) | Example | Way to represent |
|---|---:|---|---|
| comparison of a dimension | 12,594 | "style shorter than the corolla tube", "bracts exceeding the flowers" | slot 3: a relational quality with its second term |
| attachment or position | 3,437 | "stamens adnate to the corolla", "inserted at the base of the tube", "opposite the petals" | slot 3 |
| spacing | 598 | "leaves 1-2.5 cm apart" | a measurement of PATO distance (PATO:0000040) `towards` the same kind of part |
| ratio | 329 | "2-3 times as long as wide" | a measurement with unit "ratio" and, when two parts are compared, slot 3 |

### Slot 3: `towards` — implemented 2026-11-13 for comparisons of a dimension

PATO's relative qualities take their second term through RO:0002503 *towards*.

```json
{"po_id": "PO_0009074", "pato_id": "PATO_0000574",
 "towards": {"target_term": "PO_0009029", "target_text": "stamens", "start": 32, "end": 39,
             "comparison_text": "slightly shorter than"}}
```

OWL: `has_part some (style and has_characteristic some (decreased length and towards some
stamen))`; the target is part of the annotation-class signature. `comparison()` reads
"shorter / longer / broader / wider / narrower / larger / smaller / thicker / thinner / taller
than X" and "exceeding / overtopping X" when X grounds to a PO or FLOPO class other than the
bearer and stands once in the clause. Open: "as long as", "equalling" (PATO has no "same length
as"), ratios ("2-3 times as long as"), and attachment or position ("adnate to", "inserted at",
"opposite"), which use the same slot with fused with (PATO:0000642), inserted into
(PATO:0000624) and opposite (PATO:0001933). The transcription re-read separates many of these rows
(`relation_to_another_part`) without naming the second part; it has to return it.

## 4. Counts (39,762 rows)

| Pattern | Rows (est.) | Example | Way to represent |
|---|---:|---|---|
| the counted part is in the word | 15,691 | "5-nerved", "3-lobed", "5-merous", "3-foliolate" | deterministic split of "N-xed" into a count of x: the existing count pattern (`has number of`, PATO:0001555) with the part from a table (nerved → vein, lobed → lobe, foliolate → leaflet, merous → flower part) |
| count at a position | 5,067 | "veins 5-10 on each side of the midrib" | the count with slot 1 (`bearer_part`: the side of the midrib) |
| container not grounded | 5,544 | "nerves 5-7" (of what?) | resolved by the bearer rules of the candidate review, and by the organ of the sentence |

## 5. Other

- **Upper bounds** (4,103): "to about 8 m", "seldom exceeding 40 cm", "under 1 mm" are upper
  bounds with a cue the parser does not know; extend the cue list (`gates`), no model change.
- **Processes** (8,121): "rooting at the nodes", "dehiscing by slits", "bark flaking". Most are
  qualities under another name (dehiscent and its kinds were added on 2026-11-13) or the presence
  of a part at a place (adventitious roots at the nodes: presence with slot 1).

## Order of work

1. Done: kinds A and B (stage and bearer state), 117,944 rows at most.
2. No model change: "±" as an approximation cue, upper-bound cues, "N-xed" counts, kind D once
   the slot accepts FLOPO values, more rows of the context table.
3. Model change (data model, OWL export, atlas): slot 1 `bearer_part` (about 110,000 rows), then
   slot 3 `towards` (about 17,000), extremes of ranges (22,000), slot 2 `specimen_condition`
   (20,000), unions over attributes.
