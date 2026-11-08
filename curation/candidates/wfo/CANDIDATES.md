# FLOPO Candidate Additions — World Flora Online Species Descriptions (WFO) (`wfo`)

- **Records processed**: 20
- **Extracted trait rows**: 960
- **Formal assertions emitted**: 526
- **Distinct candidate value terms**: 51
- **Distinct candidate anatomical bearers**: 22
- **Distinct novel PO × PATO/FLOPO combinations**: 123

## Top Candidate FLOPO Value Terms (`value_term_candidates.tsv`)

| Quality word | Count | Taxa | Suggested PATO parent | Top bearers |
|---|---:|---:|---|---|
| `ebracteate` | 2 | 1 | `PATO:0000052` (shape) | `PO_0009049|PO_0030112` |
| `heterogamous` | 2 | 2 | `PATO:0000141` (structure) | `PO_0009046|PO_0009049` |
| `radiate` | 2 | 2 | `PATO:0000052` (shape) | `PO_0030121|PO_0009049` |
| `uniseriate` | 2 | 2 | `PATO:0000052` (shape) | `PO_0025394|phyllary` |
| `alveolate` | 1 | 1 | `PATO:0000052` (shape) | `PO_0009064` |
| `boat-shaped` | 1 | 1 | `PATO:0000052` (shape) | `PO_0009055` |
| `broader` | 1 | 1 | `PATO:0000141` (structure) | `PO_0009055` |
| `cauline` | 1 | 1 | `PATO:0000140` (position) | `PO_0025034` |
| `collared` | 1 | 1 | `PATO:0000141` (structure) | `PO_0009066` |
| `compound` | 1 | 1 | `PATO:0000141` (structure) | `PO_0009049` |
| `compound corymb` | 1 | 1 | `PATO:0000141` (structure) | `PO_0009049` |
| `cupuliform` | 1 | 1 | `PATO:0000052` (shape) | `PO_0009100` |
| `developed` | 1 | 1 | `PATO:0000141` (structure) | `PO_0025034` |
| `ecaliculate` | 1 | 1 | `PATO:0000052` (shape) | `PO_0009100` |
| `elliptic-linear` | 1 | 1 | `PATO:0000052` (shape) | `phyllary` |
| `epaleate` | 1 | 1 | `PATO:0000052` (shape) | `PO_0009064` |
| `evident` | 1 | 1 | `PATO:0000141` (structure) | `PO_0009032` |
| `funnel-form` | 1 | 1 | `PATO:0000141` (structure) | `PO_0009059` |
| `glandular-ciliolate` | 1 | 1 | `PATO:0000066` (pilosity) | `PO_0009055` |
| `glandular-puberulent` | 1 | 1 | `PATO:0000066` (pilosity) | `PO_0009059` |
| `glomerulate` | 1 | 1 | `PATO:0000060` (spatial pattern) | `PO_0009049` |
| `homogamous` | 1 | 1 | `PATO:0000141` (structure) | `PO_0009049` |
| `hyphodromous` | 1 | 1 | `PATO:0000141` (structure) | `PO_0025034` |
| `intermediate` | 1 | 1 | `PATO:0000052` (shape) | `phyllary` |
| `lanceolate-oblong` | 1 | 1 | `PATO:0000052` (shape) | `PO_0009045` |

## Top Candidate Anatomical Bearers (`bearer_candidates.tsv`)

| Bearer word | Count | Taxa | Qualities seen |
|---|---:|---:|---|
| `phyllary` | 22 | 4 | `amount|ovate|oblong|ciliate|obtuse` |
| `bristle` | 4 | 2 | `amount|fragile|scabrous|ciliate` |
| `chaff` | 2 | 1 | `persistent|scarious` |
| `fleur` | 2 | 1 | `amount` |
| `floret` | 2 | 2 | `amount` |
| `lacinia` | 2 | 1 | `rounded|pilose` |
| `annular` | 1 | 1 | `present` |
| `appendaged` | 1 | 1 | `present` |
| `aristado` | 1 | 1 | `amount` |
| `capitulescence` | 1 | 1 | `present` |
| `collar` | 1 | 1 | `present` |
| `intercostal space` | 1 | 1 | `glabrous` |
| `involucalyptus` | 1 | 1 | `clawed` |
| `leaf abaxial surface` | 1 | 1 | `pubescent` |
| `leaf vein` | 1 | 1 | `amount` |
| `pistil` | 1 | 1 | `length` |
| `scales and slender bristle` | 1 | 1 | `amount` |
| `segment` | 1 | 1 | `acute` |
| `soy` | 1 | 1 | `amount` |
| `stipe` | 1 | 1 | `small` |
| `séry` | 1 | 1 | `amount` |
| `thickening` | 1 | 1 | `amount` |

## Top Novel PO × PATO / FLOPO Class Candidates (`novel_po_pato_combinations.tsv`)

| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Count | Taxa |
|---|---|---|---|---|---|---:|---:|
| `PO_0025034` | leaf | `FLOPO_0991023` | petiolate | `EQ|PO_0025034|FLOPO_0991023` | `allowed` / `new_class_candidate` | 6 | 5 |
| `PO_0009045` | involucral bract | `PATO_0000122` | length | `EQ|PO_0009045|PATO_0000122` | `allowed` / `new_class_candidate` | 4 | 2 |
| `PO_0009045` | involucral bract | `PATO_0000052` | shape | `EQ|PO_0009045|PATO_0000052` | `allowed` / `new_class_candidate` | 3 | 1 |
| `PO_0009047` | stem | `FLOPO_0991007` | caespitose | `EQ|PO_0009047|FLOPO_0991007` | `allowed` / `new_class_candidate` | 3 | 3 |
| `PO_0009059` | corolla | `FLOPO_0985000` | campanulate | `EQ|PO_0009059|FLOPO_0985000` | `allowed` / `new_class_candidate` | 3 | 3 |
| `PO_0025517` | leaf lamina lobe | `PATO_0002006` | 2-D shape | `QUALREL|PO_0025517|PATO_0002006|continuum|PATO_0000946|PATO_0001875` | `novel` / `structured_annotation_only` | 3 | 2 |
| `PO_0030107` | achene fruit | `PATO_0000052` | shape | `EQ|PO_0030107|PATO_0000052` | `novel` / `new_class_candidate` | 3 | 2 |
| `PO_0030121` | capitulum inflorescence | `PATO_0000070` | amount | `EQ|PO_0030121|PATO_0000070` | `allowed` / `new_class_candidate` | 3 | 3 |
| `FLOPO_0985018` | corolla tube | `PATO_0000122` | length | `EQ|FLOPO_0985018|PATO_0000122` | `allowed` / `new_class_candidate` | 2 | 2 |
| `FLOPO_0986006` | corolla lobe | `PATO_0000122` | length | `EQ|FLOPO_0986006|PATO_0000122` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0009047` | stem | `FLOPO_0991003` | solitary | `EQ|PO_0009047|FLOPO_0991003` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0009049` | inflorescence | `PATO_0002455` | corymb-like | `EQ|PO_0009049|PATO_0002455` | `novel` / `new_class_candidate` | 2 | 2 |
| `PO_0009055` | bract | `PATO_0001408` | ciliated | `EQ|PO_0009055|PATO_0001408` | `allowed` / `new_class_candidate` | 2 | 1 |
| `PO_0009059` | corolla | `FLOPO_0991048` | pilose | `EQ|PO_0009059|FLOPO_0991048` | `allowed` / `new_class_candidate` | 2 | 1 |
| `PO_0009100` | involucre | `PATO_0000921` | width | `EQ|PO_0009100|PATO_0000921` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0025034` | leaf | `FLOPO_0991049` | puberulous | `EQ|PO_0025034|FLOPO_0991049` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0025034` | leaf | `FLOPO_0991052` | glabrescent | `EQ|PO_0025034|FLOPO_0991052` | `allowed` / `new_class_candidate` | 2 | 1 |
| `PO_0025034` | leaf | `PATO_0000133` | orientation | `EQ|PO_0025034|PATO_0000133` | `novel` / `new_class_candidate` | 2 | 1 |
| `PO_0025034` | leaf | `FLOPO_0991058` | scabrous | `EQ|PO_0025034|FLOPO_0991058` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0025034` | leaf | `PATO_0001412` | unstructured | `EQ|PO_0025034|PATO_0001412` | `novel` / `new_class_candidate` | 2 | 2 |
| `PO_0025331` | ray flower | `PATO_0000070` | amount | `EQ|PO_0025331|PATO_0000070` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0025517` | leaf lamina lobe | `PATO_0000389` | acute | `EQ|PO_0025517|PATO_0000389` | `novel` / `new_class_candidate` | 2 | 2 |
| `PO_0030121` | capitulum inflorescence | `PATO_0001438` | pedicellate | `EQ|PO_0030121|PATO_0001438` | `novel` / `new_class_candidate` | 2 | 2 |
| `FLOPO_0985018` | corolla tube | `PATO_0000453` | glabrous | `EQ|FLOPO_0985018|PATO_0000453` | `novel` / `new_class_candidate` | 1 | 1 |
| `FLOPO_0986006` | corolla lobe | `PATO_0000070` | amount | `EQ|FLOPO_0986006|PATO_0000070` | `novel` / `new_class_candidate` | 1 | 1 |
