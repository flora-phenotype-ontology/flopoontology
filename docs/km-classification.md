# Classifying FLOPO and the flora annotations with KM instead of ELK

Trial of 2026-11-13 with Kobayashi-MaRust (KM) v0.3.46 (`0b0549ce`,
`~/Public/software/kobayashi-marust/engine/target/release/km`) on ws. KM is a reasoner for full
OWL 2 DL (SROIQ); ELK, used for the FLOPO release (`tools/classify_flopo_release.py`), reads the
EL part of an ontology only and passes over unions, complements, cardinalities and data ranges.
Those are exactly the constructs of the annotation patterns: alternatives ("white or blue"),
negation ("petals absent"), pairs ("3-jugate") and measurements.

## Inputs

| Input | Content | Classes | Expressivity (km profile) |
|---|---|---:|---|
| A. FLOPO release | FLOPO 2026-11-13 + PO + PATO + plant GO (the release classification input) | 33,082 | SRIQ(D); 338,249 clauses, 8 disjunctive |
| B. A + one flora | A + the 7,104 annotation classes of Moss Flora of China (eflora-mfoc) | 40,186 | SRIQ(D) |
| C. small | PO + PATO + 1,974 annotation classes (600 unions, 174 negated, 600 numeric, 600 plain) | | |
| C without numbers | C without the 600 numeric classes | | SRIF; 34,367 clauses, 707 disjunctive |
| C-union | PO + PATO + plain + union classes | 1,919 compared | |
| C-negation | PO + PATO + plain + negated classes | 1,493 compared | |

## Results

| Input | ELK (ROBOT) | KM, automatic route |
|---|---|---|
| A | 18 s | no result in 50 min (stopped), 8.4 GB |
| B | 11 s; 21 unsatisfiable classes | no result in 50 min (stopped), 13.8 GB |
| C | seconds | stopped itself after 2 min 23 s at 27.6 GB: "selected CB mechanism did not reach its complete fixpoint" |
| C without numbers | seconds | no result in 8 min 20 s (stopped), 25.7 GB |
| C-union | seconds | **1.7 s**, 191 MB |
| C-negation | seconds | **0.8 s**, 81 MB |
| PO + PATO alone | | 0.45 s |

1. **KM does not finish the FLOPO release**, although the input is almost Horn (8 disjunctive
   clauses of 338,249). ELK classifies it in 18 seconds.
2. **Unions and negations each work; together they do not.** The union half and the negation
   half of input C take about a second each; their sum finds no fixpoint in eight minutes.
3. **On unions KM finds what ELK cannot.** On C-union KM returns every subsumption of ELK
   (2,133) and 402 more, all of union classes and all sound on inspection:

   | Subclass | Superclass |
   |---|---|
   | leaf apex: obtuse or retuse | leaf apex: blunt or obtuse |
   | tuber: orange or red | tuber: orange or red or pink |
   | leaf: tapered or acuminate | leaf: sharpness |
   | leaf margin: flat or involute | leaf margin: shape |

   A taxon with "leaves ovate or elliptic" is thereby classified under "leaf: shape" and under
   every wider alternative, which is what a query for the attribute or for the wider set needs.
4. **On negations KM returned an incomplete answer.** On C-negation it agrees with ELK on 943
   subsumptions and misses two that ELK reports and that hold:

   * `leaf lamina and not (decurrent)` ⊑ `lamina and not (decurrent)` (KM itself reports leaf
     lamina ⊑ lamina);
   * `leaf apex and not (transparent) and old` ⊑ `leaf apex and not (transparent)`.

   KM derives the first on a five-axiom copy of the pattern, so the gap appears at scale. The run
   ended with status ok, not with a refusal. The input is kept as
   `km-negation-reproducer.ofn` (see below) for the KM developers.
5. **ELK is already a useful check of the annotations**: on input B it reports 21
   unsatisfiable annotation classes, all of them "acute" grounded to PATO's process quality
   *acute* (the gate had set them to review).
6. **A defect of the OWL export surfaced**: classes for collections ("pairs of leaflets") used
   has member (RO:0002351) without declaring it, so OWLAPI read 50 class definitions of this
   flora as error classes. Fixed in `flopo2/owl/assertions.py` (`_bearer_classes`).

## Assessment

KM cannot replace ELK for the release today: it does not complete the release input, and on
negations it returned an incomplete result without saying so. Its result on unions is what the
alternatives pattern needs and ELK cannot give.

Ways forward, in order of cost:

1. Report findings 1, 2 and 4 to the KM developers with the inputs below.
2. Keep ELK for the release and for the unsatisfiability check of annotation classes; add that
   check (ROBOT reason over release + annotation classes) to the flora pipeline.
3. Use KM for the **union classes only**, per flora: PO + PATO + the plain and union classes
   (input C-union runs in under two seconds for 600 unions), and add the extra subsumptions to
   the atlas as inferred superclasses of the annotation classes.
4. Re-run the trial on the release once KM completes almost-Horn inputs of this size.

## Follow-up of 2026-11-13

* Decision: FLOPO stays with ELK for now.
* Finding 4 is a defect of v0.3.46 only: per the KM developers, KM 1.6.2 does not miss these
  subsumptions, but it still times out on the inputs above.
* Way forward 2 is done: `flopo2.verify.annotation_class_check` runs ELK over the release
  closure plus the annotation classes of a flora as stage 7a of `flopo2.ingest.pipeline` and in
  `tools/reannotate_flora.py`. Unsatisfiable classes are listed in
  `<source>-unsatisfiable.tsv`; their assertions are set to review with the reason
  `unsatisfiable_annotation_class`. On Moss Flora of China the check takes about 2.5 minutes.
* The 17 "acute" classes of finding 5 were a grounding error and are fixed: "acute" and
  "subacute" on a plant part now take the reviewed FLOPO values (acute (sensu botany)
  FLOPO:0991095), not PATO's process quality. Four unsatisfiable classes remain in that flora
  (*frequency* and *discontinuous* stated of a part).

## One taxon at a time (2026-11-13, evening)

Asked the other way round: not "classify the flora" but "is this taxon consistent", one taxon at
a time. The taxon is the conjunction of its accepted annotation classes; the input of one test is
the part of the ontologies those classes depend on (syntactic locality module, type BOT, OWLAPI),
and the reasoner tests the conjunction (`tools/TaxonConsistency.java`; with
`FLOPO_TAXON_MODULES=<dir>` it also writes each test as an `.ofn` file, class `urn:flopo:taxon`).

| Per taxon, Moss Flora of China | Axioms in the cut | HermiT 1.4 | KM 0.3.46 | KM 1.6.2 |
|---|---:|---|---|---|
| with FLOPO's precomposed classes | 22,600 to 32,700 | 8 s to more than 60 s (32 of the first 44 taxa over 60 s) | | |
| without them | 5,400 to 10,900 (mean 8,400) | mean 19 s, up to 87 s | no result in 5 min, or "selected CB mechanism did not reach its complete fixpoint" after 3 min 25 s | no result in 3 min 20 s, or the same message after 1 min 45 s |

FLOPO's precomposed classes are left out because a name for an expression cannot make a taxon
inconsistent. What remains is the upward closure of the taxon's terms in PO and PATO, and it is
the same few thousand axioms for every taxon. So a single taxon is not a small problem: KM does
not finish one (PO and PATO alone take it 0.45 s; a taxon's fifteen classes on top do not end),
and HermiT would need days for the 36 floras.

**What is used instead** is a taxon check inside the ELK run of the flora
(`flopo2/verify/annotation_class_check.py`, 43 s for the moss flora): absences are rewritten to
a disjointness that ELK reads, and each taxon with an absence gets one class. On the moss flora
it checks 139 taxa and reports 12 with a contradiction, mostly a wrong absence ("bladeless
sheaths" read as "leaf lamina absent" beside "blades brown-green"). It covers "absent against
described"; alternatives, numbers and negated qualities stay outside, as for ELK in general.

## Reproducing

The inputs and outputs are in `~/tmp/flopo-pat/km/` on ws (not in the repository):
`flopo-classification-input.ofn` (A), `mfoc-merged.ofn` (B), `small-merged.ofn` (C),
`small-nonum.ofn`, `t-plain-union.ofn`, `t-plain-neg.ofn` (= `km-negation-reproducer.ofn`),
with `prepare.py`, `build_tbox.py` and `compare.py`.

    km profile flopo-classification-input.ofn
    km classify t-plain-union.ofn > km-t-plain-union.json
    python compare.py elk-t-plain-union.owl km-t-plain-union.json small-kinds.json

Explicit multi-worker routes on input A gave no result either: `production_all8` was stopped
after 25 minutes (8.4 GB; the engine used one core), and `cb_absorb8` ended by itself after
3 min 13 s with a non-zero exit status and no classification.
