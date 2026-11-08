# Curated Shortlist of Remaining FLOPO Addition Candidates (Across 40 Floras)

After accepting and embedding **25 unambiguous botanical value terms (`FLOPO:0991046`–`FLOPO:0991070`)**, **20 cross-flora lexical normalization rules (`C149`–`C168`)**, and **36 allowed `(PO, PATO/FLOPO)` combinations**, this shortlist isolates the remaining high-leverage candidates across all **40 flora sources** (3,248 treatments; 52,410 extracted trait rows; 35,326 grounded assertions) that genuinely require **curator modeling judgment** before ontology promotion.

---

## 1. Value Term Candidates Requiring Curator Judgment (22 terms)

These recurring botanical descriptors were held back from automatic promotion because they involve either **(a)** relational/comparative semantics across a whorl or organ series, **(b)** fuzzy/approximate modifier prefixes (`sub-`), **(c)** compound quality + part-presence semantics, or **(d)** overlap with existing PO/PATO structural patterns.

| Priority | Candidate Term(s) | Floras | Count | Proposed Parent / Pattern | Modeling Question for Curator |
|---|---|---:|---:|---|---|
| 1 | `unequal` / `subequal` | 17 / 10 | 34 | `PATO:0000141` (`structure`) or collection-level size-variation quality | Applies to collective series (`sepals unequal`, `stamens subequal`, `phyllaries unequal`). Should this be a quality of the collective whorl (`calyx`, `androecium`, `involucre`) or a relational quality on the plural organ class? |
| 2 | `subcoriaceous` | 11 | 36 | `FLOPO:0991008` (`coriaceous`) / `PATO:0000150` (`texture`) | Should `sub-` texture intermediates (`subcoriaceous`, `submembranous`) be minted as distinct `FLOPO:0991xxx` subclasses of `coriaceous`, or represented as `coriaceous` with `value_qualifier = "approximately"`? |
| 3 | `subentire` | 9 | 18 | `PATO:0001412` (`unstructured` / entire) | Same `sub-` modeling choice as `subcoriaceous` (`leaf margin subentire`). |
| 4 | `suborbicular` | 8 | 10 | `PATO:0000411` (`circular` / orbicular) | Same `sub-` modeling choice (`leaf blade suborbicular`, `seed suborbicular`). |
| 5 | `lax` / `compact` | 8 / 4 | 20 | `PATO:0000060` (`spatial pattern`) or `FLOPO:0991021` (`crowded`) | Used primarily for inflorescences (`inflorescence lax`, `panicle compact`). Should `lax` be a new `FLOPO:0991xxx` under `PATO:0000060` (`spatial pattern`) or mapped to `PATO:0001609` (`sparse`)? |
| 6 | `accrescent` | 8 | 10 | `PATO:0000141` (`structure`) or developmental-stage quality | Calyx/perianth continuing to grow after pollination (`calyx accrescent in fruit`). Requires deciding whether to model as a structural quality or a post-anthesis process/stage quality. |
| 7 | `serrulate` | 7 | 11 | `PATO:0001204` (`serrate`) / `PATO:0000052` (`shape`) | Finely serrate margin (`leaf margin serrulate`, `leaflet serrulate`). Clear candidate for `FLOPO:0991xxx` under `PATO:0001204` (`serrate`). |
| 8 | `resinous` | 6 | 51 | `PATO:0000150` (`texture`) vs. secretion presence | High frequency across tree/shrub and desert/temperate floras (`stems resinous`, `leaves resinous-dotted`, `buds resinous`). |
| 9 | `turbinate` | 6 | 27 | `PATO:0000052` (`shape`) | Top-shaped / obconical (`receptacle turbinate`, `calyx turbinate`, `fruit turbinate`). |
| 10 | `tuberous` | 6 | 9 | `PATO:0000052` (`shape`) vs. `PO:0025077` (`tuberous root`) | When applied to `root` or `rhizome`, PO already has `PO:0025077` (`tuberous root`) and `PO:0004547` (`stem tuber`). Should `tuberous` be a shape/structure quality or a bearer-specialization rule? |
| 11 | `boat-shaped` / `navicular` | 6 | 8 | `PATO:0000052` (`shape`) | Concave keeled bracts/spathes/glumes/petals (`spathe boat-shaped`, `bract boat-shaped`, `keel boat-shaped`). |
| 12 | `spirally arranged` | 6 | 7 | `PATO:0000060` (`spatial pattern`) | Phyllotaxy / organ arrangement alongside `alternate` (`FLOPO:0991001`), `opposite` (`FLOPO:0991004`), and `whorled` (`FLOPO:0991005`). |
| 13 | `strigose` | 6 | 7 | `PATO:0000066` (`pilosity`) | Stiff, appressed bristle-like hairs. Clear candidate for `FLOPO:0991xxx` under `PATO:0000066` (`pilosity`). |
| 14 | `adnate` | 6 | 6 | `PATO:0001435` (`attachment quality`) | Fusion of unlike whorls (`stamens adnate to corolla tube`, `stipules adnate to petiole`; contrast `connate` `FLOPO:0991067`). |
| 15 | `pinnatifid` / `bipinnatifid` | 5 | 24 | `PATO:0000052` (`shape`) | Leaf-division depth intermediate between `lobed` and `pinnatisect` (`FLOPO:0991039`). |
| 16 | `glandular-pubescent` / `gland-tipped` | 5 / 3 | 29 | `PATO:0000066` (`pilosity`) vs. `has_part some (trichome and has_part some gland)` | Compound indumentum quality combining pilosity with glandular trichomes. |
| 17 | `included` | 5 | 14 | `PATO:0000140` (`position`) | Antonym of `exserted` (`FLOPO:0991015`; `stamens included`, `style included within corolla tube`). |
| 18 | `lenticellate` | 5 | 12 | `PATO:0000150` (`texture`) vs. `entity_presence` of `PO:0000031` (`lenticel`) | `branches lenticellate` — model as `entity_presence` of `PO:0000031` (`lenticel`) or as a surface texture quality? |
| 19 | `divaricate` | 5 | 11 | `PATO:0000140` (`position`) / `PATO:0000052` (`shape`) | Widely diverging at a large angle (`branches divaricate`, `anther thecae divaricate`). |
| 20 | `barbellate` | 4 | 7 | `PATO:0000150` (`texture`) or `PATO:0000052` (`shape`) | Specifically describes pappus bristles with short upward barbs (`pappus bristles barbellate`, contrast `plumose` `FLOPO:0991032`). |
| 21 | `peltate` | 4 | 6 | `PATO:0001435` (`attachment quality`) or `PATO:0000052` (`shape`) | Stalk attached to the lower surface rather than the margin (`leaves peltate`, `indusium peltate`, `scales peltate`). |
| 22 | `canaliculate` | 4 | 6 | `PATO:0000052` (`shape`) | Longitudinally channelled/grooved (`petiole canaliculate above`, `rachis canaliculate`). |

---

## 2. Anatomical Bearer Candidates Requiring Curator Judgment (16 bearers)

These anatomical structures occur across 3–12 floras and are either **(a)** context-dependent terms that map to different PO classes depending on the enclosing organ (`rachis`, `scale`, `wing`, `stipe`, `disk`/`disc`), or **(b)** specialized botanical structures missing from `config/po_lexicon.tsv` and `config/reviewed_local_bearers.tsv`.

| Priority | Bearer Surface | Floras | Count | Candidate Target / Disambiguation Needed |
|---|---|---:|---:|---|
| 1 | `rachis` (unqualified) | 12 | 54 | Ambiguous between `PO:0020041` (`leaf rachis`, for compound leaves/fronds) and `PO:0020122` (`inflorescence axis` / `inflorescence rachis`). Should unqualified `rachis` inherit the preceding clause's organ scope (`leaf` vs. `inflorescence`)? |
| 2 | `scale` | 9 | 103 | Context-dependent: fern rhizome/stipe palea (`trichome` / `scale`), bud scale (`cataphyll` `PO:0020030`), conifer cone scale (`PO:0025319`), or floral/corolla scale. |
| 3 | `gland` | 9 | 20 | Map to `PO:0025406` (`secretory structure` / `plant gland`) or `FLOPO:0986xxx`? |
| 4 | `floret` | 8 | 55 | Grass/Asteraceae individual flower (`PO:0009046` `flower`, or `PO:0009082` `spikelet floret` / `PO:0025330` `disk flower` depending on family context). |
| 5 | `wing` (unqualified) | 8 | 29 | Context-dependent: papilionaceous `wing petal` (`FLOPO:0985015`), `fruit wing`, `seed wing`, or `stem/petiole wing`. Requires clause-context disambiguation rather than a single global lexical rule. |
| 6 | `stipe` | 7 | 63 | In pteridophytes (`eflora-fna`, `powo-fz`, `nybg-naf`), `stipe` is the fern frond petiole (`PO:0020038`); in angiosperm flowers/fruits, `stipe` is a gynophore/carpophore (`PO:0009065`). |
| 7 | `spathe` | 6 | 154 | High count in `powo-cate` (Araceae/Palmweb) and `flora-guianas`. Map to `PO:0025318` (`spathe bract`) or mint `FLOPO:0986xxx` subclass of `PO:0009055` (`bract`). |
| 8 | `phyllary` / `involucral bract` | 6 | 110 | Map to `PO:0009055` (`bract`) or mint a provisional FLOPO-local bearer `FLOPO:0986xxx` (`involucral bract / phyllary`, subclass of `PO:0009055` `bract` and part of `PO:0009050` `involucre`)? |
| 9 | `spore` | 6 | 36 | Map to `PO:0025017` (`plant spore`) in `config/po_lexicon.tsv`. |
| 10 | `scape` | 6 | 33 | Leafless flowering stem (`inflorescence axis` `PO:0020122` vs. `peduncle` `PO:0009053` vs. dedicated `FLOPO:0986xxx` `scape`). |
| 11 | `disk` / `disc` | 9 | 48 | Ambiguous between floral `nectary disc` (hypogynous/epigynous disc in Sapindales/Celastraceae) and Asteraceae `capitulum disk`. |
| 12 | `rootstock` | 5 | 14 | Subterranean perennating axis (`rhizome` `PO:0004542` vs. `subterranean shoot axis` `PO:0025029`). |
| 13 | `cataphyll` | 4 | 57 | Map to `PO:0020030` (`cataphyll`) in `config/po_lexicon.tsv`. |
| 14 | `perianth tube` | 4 | 8 | Parallel to `calyx tube` (`FLOPO:0985012`) and `corolla tube` (`FLOPO:0985018`); strong candidate for `FLOPO:0986xxx` (`perianth tube`, part of `PO:0009058` `perianth`). |
| 15 | `indusium` | 3 | 17 | Fern sorus covering (`FLOPO:0986xxx` `indusium`, part of `PO:0025343` `sorus`). |
| 16 | `seed cone` / `pollen cone` | 3 | 61 | Gymnosperm strobili (`PO:0005032` `seed cone` / `PO:0005031` `pollen cone`). |

---

## 3. Novel `PO × PATO` Combinations Requiring Modeling Decisions (2 high-frequency patterns)

1. **`PO:0025034` (`leaf`) / `PO:0020039` (`leaf lamina`) × `PATO:0001412` (`unstructured`, from `"leaves entire"` — 18+ floras, 82 occurrences):**
   - In botanical prose, `"leaves entire"` or `"leaf blade entire"` is metonymy for **`leaf margin` (`PO:0020128`) + `PATO:0001412` (`entire / unstructured`)**.
   - **Decision needed:** Should the normalizer automatically re-anchor `(PO:0025034 leaf | PO:0020039 leaf lamina, "entire")` to bearer `PO:0020128` (`leaf margin`) with `bearer_scope = "margin"`, or should `PO:0025034 × PATO:0001412` be allowed directly?
2. **`PO:0025034` (`leaf`) / `PO:0020039` (`leaf lamina`) / `PO:0009031` (`sepal`) / `PO:0009032` (`petal`) / `PO:0009055` (`bract`) × `PATO:0000389` (`acute` — 16+ floras, 68+ occurrences):**
   - `PATO:0000389` (`acute`) in PATO is the *process-quality* `"having a sudden onset, sharp rise, and short course"` (which is why `flopo2.verify.gates.MANUAL_REVIEW_PATO_IDS` blocks it from automatic acceptance).
   - **Decision needed:** Mint a dedicated botanical shape value term **`FLOPO:0991071` (`acute`, subclass of `PATO:0000052` `shape`, definition: *"A shape quality inhering in a plant organ or organ apex by virtue of tapering to a sharp point with straight or slightly convex sides meeting at an angle of less than 90 degrees."* — sibling to `acuminate` `FLOPO:0991017`, `obtuse` `PATO:0001912`, and `mucronate` `FLOPO:0991054`)** so that botanical `"acute"` stops colliding with PATO's clinical process quality `PATO:0000389`.
