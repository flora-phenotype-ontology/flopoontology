"""Create an offline review packet without exposing taxon traits as image labels."""
import argparse
import hashlib
import json
from pathlib import Path


def build(data):
    profiles = json.loads((data / 'profiles.json').read_text())
    records = [r for p in profiles for r in p['records']]
    organs = {r['bl']: r['b'] for r in records}
    colours = {r['ql']: r['q'] for r in records if r.get('attribute', '').endswith('PATO_0000014')}
    vocabulary = {'organs': [{'name': name, 'iri': organs[name]} for name in ('leaf', 'petal', 'fruit')]
                    + [{'name': 'other', 'iri': ''}],
        'colours': [{'name': name, 'iri': colours[name]} for name in
                    ('green', 'yellow', 'white', 'pink', 'red', 'purple', 'orange', 'brown')]
                    + [{'name': 'unknown', 'iri': ''}],
        'scope': 'Single-colour focal regions only. Mixed colour or unresolved scale is unassessable for this pilot.'}
    (data / 'vocabulary.json').write_text(json.dumps(vocabulary, indent=2) + '\n')
    proposals = {r['photo_id']: r for r in map(json.loads, (data / 'extraction/regions.jsonl').read_text().splitlines())}
    unique = {r['photo_id']: r for r in map(json.loads, (data / 'images.jsonl').read_text().splitlines())}
    images = []
    for photo, row in unique.items():
        regions = [{'box': p['box'], 'organ': p['organ'] if p['organ'] in ('leaf', 'petal', 'fruit') else 'other',
                    'proposal_label': p['organ'], 'colour': 'unknown', 'assessable': False, 'confirmed': False}
                   for p in proposals[photo]['regions']]
        images.append({key: row[key] for key in ('photo_id', 'sha256', 'image_path', 'width', 'height', 'attribution', 'license', 'photo_url')} |
                      {'regions': regions, 'review_status': 'unreviewed', 'split': 'development_audit'})
    packet_id = hashlib.sha256(json.dumps(images, sort_keys=True).encode()).hexdigest()
    payload = json.dumps({'packet_id': packet_id, 'images': images, 'vocabulary': vocabulary}, ensure_ascii=False).replace('<', '\\u003c')
    template = Path(__file__).with_name('review.html').read_text()
    (data / 'review.html').write_text(template.replace('__PAYLOAD__', payload))
    print(f'Wrote {data / "review.html"}: {len(images)} images, no gold labels')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('local-corpora/visual-pilot'))
    build(parser.parse_args().data)
