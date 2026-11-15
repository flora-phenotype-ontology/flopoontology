# FLOPO Candidate Additions — World Flora Online Species Descriptions (WFO) (`wfo`)

- **Records processed**: 20
- **Extracted trait rows**: 960
- **Formal assertions emitted**: 534
- **Distinct candidate value terms**: 49
- **Distinct candidate anatomical bearers**: 19
- **Distinct novel PO × PATO/FLOPO combinations**: 29

## Top Candidate FLOPO Value Terms (`value_term_candidates.tsv`)

| Quality word | Count | Taxa | Suggested PATO parent | Top bearers |
|---|---:|---:|---|---|
| `ebracteate` | 2 | 1 | `PATO:0000052` (shape) | `PO_0009049|PO_0030112` |
| `heterogamous` | 2 | 2 | `PATO:0000141` (structure) | `PO_0009046|PO_0009049` |
| `radiate` | 2 | 2 | `PATO:0000052` (shape) | `PO_0030121|PO_0009049` |
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
| `glabrate` | 1 | 1 | `PATO:0000052` (shape) | `PO_0009059` |
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
| `phyllary` | 23 | 4 | `amount|ovate|oblong|ciliate|obtuse` |
| `chaff` | 2 | 1 | `persistent|scarious` |
| `fleur` | 2 | 1 | `amount` |
| `floret` | 2 | 2 | `amount` |
| `lacinia` | 2 | 1 | `rounded|pilose` |
| `annular` | 1 | 1 | `present` |
| `aristado` | 1 | 1 | `amount` |
| `capitulescence` | 1 | 1 | `present` |
| `collar` | 1 | 1 | `present` |
| `intercostal space` | 1 | 1 | `glabrous` |
| `involucalyptus` | 1 | 1 | `clawed` |
| `leaf abaxial surface` | 1 | 1 | `pubescent` |
| `leaf vein` | 1 | 1 | `amount` |
| `pistil` | 1 | 1 | `length` |
| `scales and slender bristle` | 1 | 1 | `amount` |
| `soy` | 1 | 1 | `amount` |
| `stipe` | 1 | 1 | `small` |
| `séry` | 1 | 1 | `amount` |
| `thickening` | 1 | 1 | `amount` |

## Top Novel PO × PATO / FLOPO Class Candidates (`novel_po_pato_combinations.tsv`)

| PO ID | PO Label | Quality ID | Quality Label | Signature | Status | Count | Taxa |
|---|---|---|---|---|---|---:|---:|
| `PO_0009045` | involucral bract | `PATO_0000052` | shape | `EQ|PO_0009045|PATO_0000052` | `allowed` / `new_class_candidate` | 3 | 1 |
| `PO_0025517` | leaf lamina lobe | `PATO_0002006` | 2-D shape | `QUALREL|PO_0025517|PATO_0002006|continuum|PATO_0000946|PATO_0001875` | `novel` / `structured_annotation_only` | 3 | 2 |
| `PO_0030107` | achene fruit | `PATO_0000052` | shape | `EQ|PO_0030107|PATO_0000052` | `novel` / `new_class_candidate` | 3 | 2 |
| `PO_0000003` | whole plant | `PATO_0002352` | herbaceous | `EQ|PO_0000003|PATO_0002352` | `allowed` / `new_class_candidate` | 2 | 2 |
| `PO_0009059` | corolla | `FLOPO_0991048` | pilose | `EQ|PO_0009059|FLOPO_0991048` | `allowed` / `new_class_candidate` | 2 | 1 |
| `PO_0025034` | leaf | `PATO_0104359` | entire | `EQ|PO_0025034|PATO_0104359` | `novel` / `new_class_candidate` | 2 | 2 |
| `PO_0025517` | leaf lamina lobe | `PATO_0000052` | shape | `QUALREL|PO_0025517|PATO_0000052|continuum|FLOPO_0991095|PATO_0001935` | `novel` / `structured_annotation_only` | 2 | 2 |
| `PO_0025517` | leaf lamina lobe | `PATO_0000389` | acute | `EQ|PO_0025517|PATO_0000389` | `novel` / `new_class_candidate` | 2 | 2 |
| `PO_0009001` | fruit | `FLOPO_0991086` | strigose | `EQ|PO_0009001|FLOPO_0991086` | `allowed` / `new_class_candidate` | 1 | 1 |
| `PO_0009039` | glume | `PATO_0000001` | characteristic | `EQ|PO_0009039|PATO_0000001` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0009045` | involucral bract | `PATO_0000389` | acute | `EQ|PO_0009045|PATO_0000389` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0009045` | involucral bract | `FLOPO_0991067` | connate | `EQ|PO_0009045|FLOPO_0991067` | `novel` / `existing` | 1 | 1 |
| `PO_0009045` | involucral bract | `PATO_0001436` | sessile (sensu botany) | `EQ|PO_0009045|PATO_0001436` | `novel` / `annotation_extension_only` | 1 | 1 |
| `PO_0009047` | stem | `PATO_0104366` | floccose | `EQ|PO_0009047|PATO_0104366` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0009049` | inflorescence | `PATO_0000690` | discontinuous | `EQ|PO_0009049|PATO_0000690` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0009059` | corolla | `PATO_0000389` | acute | `EQ|PO_0009059|PATO_0000389` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0009100` | involucre | `PATO_0000389` | acute | `EQ|PO_0009100|PATO_0000389` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0020104` | leaf sheath | `PATO_0104311` | purplish red | `EQ|PO_0020104|PATO_0104311` | `allowed` / `new_class_candidate` | 1 | 1 |
| `PO_0020128` | leaf margin | `PATO_0104359` | entire | `EQ|PO_0020128|PATO_0104359` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0025034` | leaf | `FLOPO_0991076` | subcoriaceous | `EQ|PO_0025034|FLOPO_0991076` | `allowed` / `new_class_candidate` | 1 | 1 |
| `PO_0025034` | leaf | `PATO_0000389` | acute | `EQ|PO_0025034|PATO_0000389` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0025393` | pappus | `FLOPO_0991068` | free | `EQ|PO_0025393|FLOPO_0991068` | `novel` / `existing` | 1 | 1 |
| `PO_0025394` | pappus element | `FLOPO_0991090` | uniseriate | `EQ|PO_0025394|FLOPO_0991090` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0025517` | leaf lamina lobe | `PATO_0104359` | entire | `EQ|PO_0025517|PATO_0104359` | `novel` / `new_class_candidate` | 1 | 1 |
| `PO_0030107` | achene fruit | `FLOPO_0991062` | ribbed | `EQ|PO_0030107|FLOPO_0991062` | `novel` / `existing` | 1 | 1 |
