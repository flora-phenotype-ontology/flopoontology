"""Human trait labels from iNaturalist observation fields, as an independent test set.

iNaturalist users fill in observation fields such as "Primary flower color" or "Leaf arrangement"
for single observations. These are labels of the photographed plant, entered by people who are
not us, so they test trait recognition without any labelling on our side. They are used for
evaluation only, never for training.

    python -m flopo2.traitvision.inat_fields local-corpora/trait-vision/inat-fields.jsonl
"""
import json
import sys
import time
import urllib.parse
import urllib.request

API = 'https://api.inaturalist.org/v1/observations'
FIELDS = ['Primary flower color', 'Flower Color', 'Plant Growth Form [IUCN Red List]', 'Growth Form (Type)',
          'Growth Form (habit)', 'Leaf arrangement [Plant Identification]', 'leaf arrangement',
          'Simple leaf margin', 'Simple leaf shape', 'Thorns?', 'Fruit Color', 'Primary fruit color']


def get(params):
    url = API + '?' + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'research-client/1.0'})
            return json.load(urllib.request.urlopen(req, timeout=60))
        except Exception as exc:
            print('retry', attempt, exc, flush=True)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(url)


def main(out):
    with open(out, 'w') as fh:
        for field in FIELDS:
            above, n = 0, 0
            while True:
                d = get({f'field:{field}': '', 'taxon_id': 47126, 'quality_grade': 'research', 'photos': 'true',
                         'per_page': 200, 'order_by': 'id', 'order': 'asc', 'id_above': above})
                rows = d.get('results', [])
                if not rows:
                    break
                for r in rows:
                    above = r['id']
                    value = [o['value'] for o in r.get('ofvs', []) if o.get('name') == field]
                    photos = [{'id': p['id'], 'license': p['license_code'], 'url': p['url']}
                              for p in r.get('photos', []) if p.get('license_code')]
                    taxon = r.get('taxon') or {}
                    if not value or not photos:
                        continue
                    fh.write(json.dumps({'field': field, 'value': value[0], 'observation': r['id'], 'uuid': r['uuid'],
                                         'taxon': taxon.get('name'), 'rank': taxon.get('rank'),
                                         'inat_taxon_id': taxon.get('id'), 'ancestors': taxon.get('ancestor_ids'),
                                         'observer': (r.get('user') or {}).get('id'), 'photos': photos}) + '\n')
                    n += 1
                fh.flush()
                time.sleep(1.1)
            print(field, n, flush=True)


if __name__ == '__main__':
    main(sys.argv[1])
