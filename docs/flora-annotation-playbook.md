# Annotating a new flora with FLOPO

This playbook records how the Saudi floras (NCVC 2024, Collenette 1985) were annotated, and the
fixes that every new flora should get from the start. The code is shared: a new source needs a
transcription step that writes NCVC-style records, then everything below applies unchanged.

## Pipeline

`tools/build_saudi_flora.sh` is the reference. In order:

1. **Transcribe** each species entry into rows `entity_en, quality_en, value_low, value_high,
   unit, source_en, qualifiers{negated, stage, frequency, alternatives}` (Qwen on unimatrix01:
   `flopo2.ingest.collenette_llm`; prompt rules in `INSTRUCTIONS`). `source_en` must be verbatim.
2. **Annotate** (`flopo2.ingest.ncvc_annotate.annotate_record`, atlas options on): anchor each row
   in the text, ground part and quality through the rule tables and lexicons, run the FLOPO gates.
3. **Re-read unmatched rows** with Qwen (`flopo2.ingest.llm_reread`), then annotate again.
4. **Choose terms for the words still unmatched** among lexical candidates
   (`flopo2.ingest.llm_term_rules`, with an independent verification call).
5. **Locate the values of alternatives and continua** (`flopo2.ingest.llm_relations`), then
   annotate a final time.
6. Validate, merge taxa (WFO), build RDF (`flopo2.saudi.build`).

Every LLM step is cached in `local-corpora/saudi-flora/*.jsonl` and nothing it says is taken on
trust: spans are re-located verbatim, terms are re-grounded through the normal rules and
lexicons, and the gates run on the result.

## Representation patterns

| Source says | Representation |
|---|---|
| leaves ovate | `leaf and has_quality some ovate` |
| leaves 2–3 cm long | `has_quality some (length and has_magnitude some decimal[>=2, <=3] and has_value_unit some cm)` |
| containing 2–3 seeds; corolla has 5 petals | count: E = the counted part, Q = PATO amount, unit UO count unit (`normalize_counts`) |
| 3 seeds per fruit | count of `(seed and part_of some fruit)` |
| 11–15 pairs of leaflets per pinna | count of `(object aggregate and has_member exactly 2 leaflet and part_of some pinna)` |
| flowers in groups of 4–6 | count of `(object aggregate and has_member some flower)` |
| annual or perennial; white, pink or purple | disjunction: `has_quality some (annual or perennial)`, `value_operator: one_of` (`alternatives_as_union`) |
| linear-lanceolate; ovate to elongate-linear | compound shapes: "X-Y" is between X and Y, a continuum; "elongate" in a compound repeats the other word and is dropped (`chain_from_phrase`) |
| ovate to subglobose; red tending to orange | continuum: a qualitative value relation between the two values (reified; no OWL class, because an intermediate value is neither endpoint) |
| white becoming pink | temporal transition: qualitative value relation |
| petals absent; no scent | `ObjectComplementOf` (absence of the part, or lack of the quality) |

A disjunction is a union only when every value grounds under one PATO attribute and no value
has its own degree cue ("pale yellow or white" stays a relation).

## Fixes to apply to every new flora

1. **Re-read unmatched rows** (`llm_reread`). Transcriptions put more than a quality into the
   quality field. The re-read returns, per row, a part, one glossary-style quality and a kind:
   - "medium tree growth form" → whole plant / tree + whole plant / medium-sized;
   - "longitudinally fissured" → fissured (modifier dropped);
   - "pitcher-shaped (urceolate)" → urceolate (use the glossed standard term);
   - "head", "corona" as a quality → structure present;
   - "four petals" → count (then `count_from_text` makes it petal amount 4);
   - "flowers before the leaves appear", "exudes latex when broken" → `process_or_event`;
     "attached in the leaf axil" → `relation_to_another_part`; grazing, uses →
     `not_a_plant_trait`. These keep a precise reason instead of "no ontology term".
2. **Split inline alternatives** (`split_inline_alternatives`): a quality written as "shrub or
   small tree" / "ovate to subglobose" / "red tending to purple" becomes quality + alternatives,
   so the union and relation patterns apply. A comma list without "or"/"to" ("thin, leathery")
   states every value: it becomes one row per value, not alternatives.
   Lists and compounds are then read deterministically (`chain_from_phrase`) before the LLM
   relation cache: values are grounded one by one, a hyphenated compound ("linear-lanceolate")
   is a continuum between its words, and a chain "linear-lanceolate to oblong-ovate" is the
   continuum linear - lanceolate - oblong - ovate (an approximation: the source range runs
   between two intermediates).
   A measurement written as the quality ("2-5 cm long", "60 cm tall") becomes the attribute
   with its value (`measurements_from_quality`).
3. **Counts** (`normalize_counts`): numbered parts with a non-length unit become PATO amount with
   the UO count unit; the counted part comes from the quality ("number of petals"), the unit
   ("seeds") or the entity. Nothing about the count is dropped (user's design, 2026-10-15):
   - the structure the parts belong to ("per fruit", "in each locule", or the row's entity when
     it is not the counted part) is a `part_of` restriction on the bearer (`bearer_container`):
     "3 seeds per fruit" is `has_part some ((seed and part_of some fruit) and has_quality some
     (amount and has_magnitude some decimal[3, 3] and has_value_unit some 'count unit'))`;
   - pairs are collections (`bearer_collection_size`): "11–15 pairs of leaflets per pinna" is the
     amount 11–15 of `(object aggregate and has_member exactly 2 leaflet and part_of some pinna)`;
   - groups ("flowers in groups of 4–6", "clusters of 2 to 16", "whorls of 1–4") are collections
     of any size (`bearer_collection`): the amount 4–6 of `(object aggregate and has_member some
     flower)`;
   - a count per position ("1–3 fruits per leaf axil") is not parthood and stays pending as
     `count_per_position`.
4. **Shared attribute of two values** (`ground_value`): a relation or union needs both values
   under one PATO attribute. FLOPO value terms inherit the attribute ancestors of their PATO
   parent ("ovate" beneath 2-D shape and "cordate" share shape). "Morphology" is too general and
   is ignored ("spiny or hairy" is not one quality), except between growth forms (herbaceous,
   ligneous, arborescent, frutescent, suffrutescent), for which PATO has no habit attribute.
5. **Alternatives not in the sentence** are dropped: a transcriber sometimes lists alternatives
   for a phrase that states one value ("white flowers"); the row is then annotated as that value.
6. **Standard botanical words missing from PATO's synonyms** get reviewed rules
   (`collenette_normalization.tsv`): globose = spherical, elongate = elongated, three-lobed =
   trilobed, semi-globose / hemispherical = hemispheroid, subglobose → spheroid (broader),
   ciliate = ciliated, sturdy / strong (stems, roots) = robust, round fruits or heads =
   spherical, round stems = terete, rudimentary = vestigial. Words naming a structure become
   its presence: rhizomatous (rhizome), arillate (aril), scale-like leaves (scale leaf).
   Words PATO lacks become FLOPO flora value terms (fibrous, fibrous-rooted, beaked, horned,
   zigzag, umbelliform, pectinate = comb-like, virgate = broom-like, palm-like, claw-shaped,
   subterranean, aerial, androgynous, medium-sized, ...; FLOPO:0991026-0991045).
7. **PATO label traps** (`PATO_LABEL_TRAPS`, `rules_over_pato_label`): the transcriber's PATO label
   is taken at face value, so reviewed rules win for words PATO names misleadingly:
   - "ovate" is the plane shape (FLOPO:0991024 until pato#627), "ovoid" PATO:0001891;
   - "pubescent"/"downy" is botanical pubescence PATO:0001320, never PATO:0000455 (puberty);
   - "oval" is elliptic, "ellipsoid" is prolate.
8. **Compound habits** (`merge_compound_habits`): "herbaceous shrub", "shrubby herb", "woody herb"
   are one habit (subshrub), not two exclusive ones.
9. **Absence** is one representation: "absent", "no X" and "without X" are the complement of
   presence.
10. **Colours** are read on the ISCC-NBS backbone; compounds of two hues are the intermediate
   category.
11. **Measurements** must be anchored on their printed numbers.

## Reviewing what is left

The atlas Coverage tab lists the unannotated statements by reason. Open a reason to see the
transcribed qualities with the part and sentence (and download them as CSV). Words that remain
under "no ontology term for quality" are candidates for FLOPO flora value terms
(`config/flopo_flora_value_terms.tsv`, FLOPO:0991xxx, beneath the closest PATO class), which are
reviewed before release and later proposed to PATO. Comparisons such as "palm-like" or
"comb-like" belong in FLOPO, not PATO. A term withdrawn in review (semi-prostrate, FLOPO:0991008,
not distinguishable from decumbent) is not re-added.
