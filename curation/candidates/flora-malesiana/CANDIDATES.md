# FLOPO Candidate Additions — Flora Malesiana (FlorML) (`flora-malesiana`)

- **Records processed**: 20
- **Extracted trait rows**: 1,211
- **Formal assertions emitted**: 404
- **Distinct candidate value terms**: 53
- **Distinct candidate anatomical bearers**: 22
- **Distinct novel PO × PATO/FLOPO combinations**: 84

## Top Candidate FLOPO Value Terms (`value_term_candidates.tsv`)

| Quality word | Count | Taxa | Suggested PATO parent | Top bearers |
|---|---:|---:|---|---|
| `narrowed` | 20 | 18 | `PATO:0000141` (structure) | `FLOPO_0985027|PO_0025034|PO_0020049|frond base|FLOPO_0985026` |
| `dimorphic` | 13 | 12 | `PATO:0000141` (structure) | `FLOPO_0985026|PO_0025034` |
| `pinnatifid` | 13 | 13 | `PATO:0000052` (shape) | `FLOPO_0985026|PO_0025060|PO_0025034` |
| `enlarged` | 8 | 5 | `PATO:0000141` (structure) | `PO_0005020|strand` |
| `index` | 8 | 8 | `PATO:0000141` (structure) | `PO_0025034|PO_0009049|PO_0025278|FLOPO_0985027` |
| `elevated` | 6 | 6 | `PATO:0000141` (structure) | `PO_0004542|phyllopod` |
| `not persistent` | 6 | 6 | `PATO:0000141` (structure) | `rachis` |
| `round` | 6 | 6 | `PATO:0000141` (structure) | `PO_0025359|PO_0030070` |
| `without basal constriction` | 6 | 6 | `PATO:0000140` (position) | `FLOPO_0985027|PO_0020049` |
| `acicular` | 5 | 5 | `PATO:0000141` (structure) | `PO_0025094|PO_0000282|abscission vein` |
| `equally sized` | 5 | 5 | `PATO:0000141` (structure) | `PO_0005020` |
| `rugulate` | 5 | 5 | `PATO:0000052` (shape) | `spore` |
| `imbricated` | 4 | 4 | `PATO:0000140` (position) | `frond base` |
| `stalked` | 4 | 4 | `PATO:0000141` (structure) | `FLOPO_0985026` |
| `monomorphic` | 3 | 3 | `PATO:0000141` (structure) | `PO_0025034` |
| `pseudopeltate` | 3 | 3 | `PATO:0001435` (attachment quality) | `PO_0025278` |
| `catenate` | 2 | 1 | `PATO:0000052` (shape) | `rachis|PO_0030072` |
| `close` | 2 | 2 | `PATO:0000141` (structure) | `PO_0025359` |
| `confluent` | 2 | 2 | `PATO:0000141` (structure) | `PO_0025359` |
| `indumented` | 2 | 1 | `PATO:0000141` (structure) | `rachis|PO_0030072` |
| `laterally affixed` | 2 | 2 | `PATO:0000140` (position) | `PO_0030070` |
| `peltate` | 2 | 2 | `PATO:0001435` (attachment quality) | `PO_0030070|paraphysis blade` |
| `rowed` | 2 | 2 | `PATO:0000141` (structure) | `PO_0005020|strand` |
| `shallowly sunken` | 2 | 2 | `PATO:0000141` (structure) | `PO_0025359` |
| `thin-walled` | 2 | 1 | `PATO:0000141` (structure) | `PO_0025278|rhizome scale cell` |

## Top Candidate Anatomical Bearers (`bearer_candidates.tsv`)

| Bearer word | Count | Taxa | Qualities seen |
|---|---:|---:|---|
| `stipe` | 17 | 10 | `length|winged|thick|long|glabrous` |
| `spore` | 14 | 9 | `small|globular|spiny|spineless` |
| `strand` | 9 | 4 | `dorsal|protruding|invaginated` |
| `rachis` | 7 | 6 | `persistent|hairy` |
| `dorsal strand` | 6 | 6 | `amount` |
| `wing` | 4 | 4 | `lobed` |
| `auriculate` | 3 | 3 | `present` |
| `paraphysis blade` | 3 | 1 | `flat|entire|width` |
| `base` | 2 | 1 | `dilated|lobed` |
| `frond base` | 2 | 2 | `dilated` |
| `midrib present` | 2 | 2 | `present` |
| `rhizome scale margin` | 2 | 2 | `dentate|toothed` |
| `with small globules` | 2 | 2 | `present` |
| `cell` | 1 | 1 | `thickened` |
| `dorsal protrusion` | 1 | 1 | `present` |
| `invaginated` | 1 | 1 | `present` |
| `margin` | 1 | 1 | `dentate` |
| `marginal cells` | 1 | 1 | `membranaceous` |
| `marginal zone` | 1 | 1 | `free` |
| `phyllopod` | 1 | 1 | `amount` |
| `rhizome scale apex` | 1 | 1 | `rounded` |
| `sclerified strand` | 1 | 1 | `absent` |

## Top Novel PO × PATO / FLOPO Class Candidates (`novel_po_pato_combinations.tsv`)

| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Count | Taxa |
|---|---|---|---|---|---|---:|---:|
| `PO_0004542` | rhizome | `FLOPO_0991009` | creeping | `EQ|PO_0004542|FLOPO_0991009` | `allowed` / `new_class_candidate` | 19 | 18 |
| `FLOPO_0985027` | pinna | `PATO_0000921` | width | `EQ|FLOPO_0985027|PATO_0000921` | `novel` / `new_class_candidate` | 14 | 8 |
| `FLOPO_0985027` | pinna | `PATO_0000122` | length | `EQ|FLOPO_0985027|PATO_0000122` | `novel` / `new_class_candidate` | 13 | 7 |
| `FLOPO_0985027` | pinna | `PATO_0000467` | present | `EQ|FLOPO_0985027|PATO_0000467` | `novel` / `new_class_candidate` | 12 | 12 |
| `PO_0025094` | sporangium | `PATO_0000453` | glabrous | `EQ|PO_0025094|PATO_0000453` | `novel` / `new_class_candidate` | 10 | 10 |
| `PO_0025278` | rhizome scale leaf | `PATO_0000052` | shape | `QUALREL|PO_0025278|PATO_0000052|continuum|PATO_0002228|FLOPO_0985001` | `novel` / `structured_annotation_only` | 9 | 5 |
| `FLOPO_0985026` | frond | `PATO_0001436` | sessile (sensu botany) | `EQ|FLOPO_0985026|PATO_0001436` | `novel` / `new_class_candidate` | 8 | 8 |
| `PO_0025278` | rhizome scale leaf | `FLOPO_0985006` | spreading | `EQ|PO_0025278|FLOPO_0985006` | `novel` / `new_class_candidate` | 8 | 8 |
| `PO_0005020` | vascular bundle | `PATO_0000070` | amount | `EQC|PO_0005020|n|PATO_0000070` | `allowed` / `new_class_candidate` | 7 | 7 |
| `FLOPO_0985026` | frond | `PATO_0000122` | length | `EQ|FLOPO_0985026|PATO_0000122` | `novel` / `new_class_candidate` | 6 | 6 |
| `FLOPO_0985026` | frond | `PATO_0000921` | width | `EQ|FLOPO_0985026|PATO_0000921` | `novel` / `new_class_candidate` | 6 | 6 |
| `FLOPO_0985026` | frond | `PATO_0001979` | lobed | `EQ|FLOPO_0985026|PATO_0001979` | `novel` / `new_class_candidate` | 6 | 6 |
| `FLOPO_0985027` | pinna | `PATO_0001412` | unstructured | `EQ|FLOPO_0985027|PATO_0001412` | `novel` / `new_class_candidate` | 6 | 6 |
| `FLOPO_0985026` | frond | `PATO_0000066` | pilosity | `EQV|FLOPO_0985026|ONE_OF|PATO_0000453&PATO_0001320` | `novel` / `annotation_extension_only` | 5 | 5 |
| `FLOPO_0985027` | pinna | `PATO_0001199` | linear | `EQ|FLOPO_0985027|PATO_0001199` | `novel` / `new_class_candidate` | 5 | 5 |
| `PO_0005020` | vascular bundle | `PATO_0001748` | invaginated | `EQ|PO_0005020|PATO_0001748` | `novel` / `new_class_candidate` | 5 | 5 |
| `PO_0006023` | bundle sheath | `PATO_0000327` | low brightness | `EQ|PO_0006023|PATO_0000327` | `novel` / `new_class_candidate` | 5 | 5 |
| `PO_0025034` | leaf | `PATO_0001408` | ciliated | `EQ|PO_0025034|PATO_0001408` | `allowed` / `new_class_candidate` | 5 | 4 |
| `PO_0025278` | rhizome scale leaf | `PATO_0000467` | present | `EQ|PO_0025278|PATO_0000467` | `novel` / `annotation_extension_only` | 5 | 5 |
| `PO_0025278` | rhizome scale leaf | `PATO_0000574` | decreased length | `EQ|PO_0025278|PATO_0000574` | `novel` / `new_class_candidate` | 5 | 4 |
| `PO_0025278` | rhizome scale leaf | `PATO_0001205` | dentated | `EQ|PO_0025278|PATO_0001205` | `novel` / `new_class_candidate` | 5 | 5 |
| `FLOPO_0985027` | pinna | `PATO_0001847` | constricted | `EQ|FLOPO_0985027|PATO_0001847` | `novel` / `new_class_candidate` | 4 | 4 |
| `PO_0025034` | leaf | `PATO_0000574` | decreased length | `EQ|PO_0025034|PATO_0000574` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0025034` | leaf | `PATO_0001412` | unstructured | `EQ|PO_0025034|PATO_0001412` | `novel` / `new_class_candidate` | 3 | 3 |
| `PO_0025094` | sporangium | `PATO_0000454` | hairy | `EQ|PO_0025094|PATO_0000454` | `novel` / `new_class_candidate` | 3 | 3 |
