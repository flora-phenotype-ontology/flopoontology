"""Which flora records the trait-vision labels use: vascular plants only, and every description once.

* Bryophytes are left out (FLOPO and the Plant Ontology parts used here describe vascular plants; a moss "capsule"
  is not a fruit): the moss flora as a whole, and any record whose family and genus are both unknown to the
  World Checklist of Vascular Plants (``vascular.json``, written by ``build``).
* A description that an aggregator republishes is left out (``local-corpora/saudi-flora/duplicates.tsv`` of
  ``tools.atlas_duplicates``): the copy in the flora itself is kept.

    python3 -m flopo2.traitvision.scope build
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path('local-corpora/trait-vision')
MOSS_SOURCES = {'eflora-mfoc'}
_state = {}


def build():
    csv.field_size_limit(10 ** 9)
    fam, gen = set(), set()
    for r in csv.DictReader(open('local-corpora/wcvp/raw/wcvp_names.csv'), delimiter='|', quoting=csv.QUOTE_NONE):
        fam.add(r['family']); gen.add(r['genus'])
    (HERE / 'vascular.json').write_text(json.dumps({'families': sorted(fam), 'genera': sorted(gen)}))
    print('families', len(fam), 'genera', len(gen))


def skip(record, source):
    """True for a record outside the scope; counts the reasons in ``skip.count``."""
    if not _state:
        v = json.loads((HERE / 'vascular.json').read_text())
        _state['fam'], _state['gen'] = set(v['families']) | {'Compositae', 'Leguminosae', 'Gramineae', 'Labiatae', 'Cruciferae', 'Umbelliferae', 'Palmae', 'Guttiferae'}, set(v['genera'])
        dup = Path('local-corpora/saudi-flora/duplicates.tsv')
        _state['dup'] = {r['source_id'] for r in csv.DictReader(open(dup), delimiter='\t')} if dup.exists() else set()
        skip.count = {'moss flora': 0, 'not a vascular plant': 0, 'copy of another description': 0}
    if source in MOSS_SOURCES:
        skip.count['moss flora'] += 1
        return True
    genus = (record.get('taxon') or ' ').split()[0] if (record.get('taxon') or '').strip() else ''
    family = record.get('taxon_family') or ''
    if genus not in _state['gen'] and family not in _state['fam']:
        skip.count['not a vascular plant'] += 1
        return True
    if record.get('source_id') in _state['dup']:
        skip.count['copy of another description'] += 1
        return True
    return False


if __name__ == '__main__':
    {'build': build}[sys.argv[1]]()
