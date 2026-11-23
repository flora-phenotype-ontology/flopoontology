# Descriptions held twice, and what the two extractions say

Raised by Marco Schmidt (Senckenberg), 2026-11-22: World Flora Online carries the descriptions of
the Kew and Meise floras and of Flora of China, so the atlas would show the same description
twice. `python -m tools.atlas_duplicates` finds the copies; the atlas build leaves them out.

## What counts as a copy

A description is a copy when at least 90% of its sentences (40 characters or more, compared
without case, spaces and punctuation; at least three) are sentences of one description of
another source. Of two copies the flora is kept and the aggregator dropped (order: any flora,
then `powo-ftea`, `powo-kew`, `eflora-other`, `wfo`); between two floras the larger one is kept.

## Result (2026-11-23)

29,137 copies, 27,129 of them in World Flora Online (of 111,454 descriptions there):

| Copy in | Kept in | Descriptions |
|---|---|---|
| World Flora Online | Flora of China | 20,216 |
| World Flora Online | Flora of Tropical East Africa (Kew 2014) | 3,029 |
| World Flora Online | Flora of North America | 1,802 |
| eFloras additional floras | Moss Flora of China | 1,642 |
| World Flora Online | Flora of Pakistan | 989 |
| World Flora Online | Flore d'Afrique Centrale | 635 |
| Flora of Tropical East Africa (POWO) | Flora of Tropical East Africa (Kew 2014) | 183 |

The atlas showed World Flora Online only as a pilot of 19 taxa on that day (its full run was not
finished), so the doubling was small on the site; the list is in place before the full source
arrives. Flora of Zimbabwe has no word-for-word overlap with the 798 Flora Zambesiaca
descriptions we hold (via POWO); whether it paraphrases them could not be tested.

## Two extractions of one text

Each copy was read by the model on its own, so a copied description is a repeat of the
extraction. On accepted statements (same annotation class in both):

| | Statements |
|---|---|
| in both extractions | 792,399 |
| in one only | 419,824 |
| agreement | 65% |

By pair of sources the agreement is 60 to 75% (`duplicate-agreement.tsv`). Where the text is
identical character for character the picture is the same (62 to 77%), so the differences come
from the extraction, not from small differences between the copies. Most statements found once
are measurements and counts (petal, corolla, leaf blade length; number of flowers, of veins, of
lobes): the same sentence gives "2-5 mm" in one run and nothing, or another range, in the other.
`duplicate-disagreements.tsv` lists them by part and quality, most frequent first; it is the
place to look for unstable rules.

What follows for the atlas: a statement that is found in one of two runs is not wrong, but one
run misses about one statement in five that the other finds. The copies are not used to add
statements to the kept description (not done; it would raise recall).

## Files

`local-corpora/saudi-flora/duplicates.tsv` (read by `flopo2.saudi.build`),
`duplicate-agreement.tsv`, `duplicate-disagreements.tsv`; rebuilt by the tool before each build.
