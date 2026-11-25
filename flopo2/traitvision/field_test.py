"""Map iNaturalist observation-field values to pilot classes; write the test table and photo manifest.

    python -m flopo2.traitvision.field_test local-corpora/trait-vision
"""
import collections
import json
import sys
from pathlib import Path

COLOUR = {c: c for c in 'white yellow red pink purple blue orange green brown'.split()}
COLOUR.update({'lavender': 'purple', 'maroon': 'red'})
HABIT = {'herb': 'herb', 'forb or herb': 'herb', 'annual': 'herb', 'tree': 'tree', 'tree - small': 'tree',
         'tree - large': 'tree', 'shrub': 'shrub', 'shrub - small': 'shrub', 'shrub - large': 'shrub',
         'shrub - size unknown': 'shrub', 'vine': 'climber', 'vines': 'climber'}
ARR = {'alternate': 'alternate', 'opposite': 'opposite', 'decussate': 'opposite', 'whorled': 'whorled',
       'verticillate': 'whorled'}
MAP = {'Primary flower color': ('flower_colour', COLOUR), 'Flower Color': ('flower_colour', COLOUR),
       'Plant Growth Form [IUCN Red List]': ('habit', HABIT), 'Growth Form (Type)': ('habit', HABIT),
       'Growth Form (habit)': ('habit', HABIT), 'Leaf arrangement [Plant Identification]': ('leaf_arrangement', ARR),
       'leaf arrangement': ('leaf_arrangement', ARR),
       'Simple leaf margin': ('leaf_margin', {'entire': 'entire', 'toothed(serrated)': 'toothed', 'lobed': 'lobed'}),
       'Simple leaf shape': ('leaf_complexity', {'simple': 'simple', 'pinnately compound': 'compound',
                                                 'palmately compound': 'compound'}),
       'Thorns?': ('spines', {'yes': 'present', 'no': 'absent'}),
       'Fruit Color': ('fruit_colour', COLOUR), 'Primary fruit color': ('fruit_colour', COLOUR)}


def main(folder):
    folder = Path(folder)
    seen, photos, counts = {}, {}, collections.Counter()
    for line in open(folder / 'inat-fields.jsonl'):
        r = json.loads(line)
        trait, mapping = MAP[r['field']]
        cls = mapping.get(r['value'].strip().lower())
        if cls is None or not r.get('taxon') or r.get('rank') not in ('species', 'subspecies', 'variety', 'form'):
            continue
        key = (r['observation'], trait)
        if key in seen and seen[key][0] != cls:
            seen[key] = None                 # two fields disagree: drop
            continue
        ph = r['photos'][:2]
        seen[key] = (cls, ' '.join(r['taxon'].split()[:2]), [p['id'] for p in ph])
        for p in ph:
            photos[p['id']] = p['url'].rsplit('.', 1)[-1].split('?')[0]
    with open(folder / 'field-test.tsv', 'w') as out:
        out.write('observation\ttrait\tclass\ttaxon\tphotos\n')
        for (obs, trait), v in sorted(seen.items()):
            if v:
                out.write(f"{obs}\t{trait}\t{v[0]}\t{v[1]}\t{'|'.join(map(str, v[2]))}\n")
                counts[trait] += 1
    with open(folder / 'field-photos.tsv', 'w') as out:
        out.write('photo_id\textension\n')
        for pid, ext in sorted(photos.items()):
            out.write(f'{pid}\t{ext}\n')
    print(dict(counts), len(photos), 'photos')
    all_photos(folder, set(photos))


def all_photos(folder, first_two):
    """Every photograph of the labelled observations, in order (``field-obs-photos.tsv``), and those beyond the first two."""
    seen, rest = set(), {}
    with open(folder / 'field-obs-photos.tsv', 'w') as out:
        out.write('observation\tphoto_id\tposition\textension\n')
        for line in open(folder / 'inat-fields.jsonl'):
            r = json.loads(line)
            if r['observation'] in seen:
                continue
            seen.add(r['observation'])
            for k, p in enumerate(r['photos']):
                ext = p['url'].rsplit('.', 1)[-1].split('?')[0]
                out.write(f"{r['observation']}\t{p['id']}\t{k}\t{ext}\n")
                if p['id'] not in first_two and 'inaturalist-open-data' in p['url']:
                    rest[p['id']] = ext
    with open(folder / 'field-photos-rest.tsv', 'w') as out:
        out.write('photo_id\textension\n')
        for pid, ext in sorted(rest.items()):
            out.write(f'{pid}\t{ext}\n')
    print(len(seen), 'observations;', len(rest), 'photographs beyond the first two')


if __name__ == '__main__':
    main(sys.argv[1])
