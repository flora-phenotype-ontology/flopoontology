"""Freeze a scoped multi-attribute vocabulary and leakage-aware v2 split before fitting."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from .extract import digest

OBO = 'http://purl.obolibrary.org/obo/'
# Explicit ontology IDs avoid conflating identically labelled 2-D/3-D qualities.
GROUPS = {
    'colour': [('green','FLOPO_0988006'),('yellow','FLOPO_0988004'),('white','FLOPO_0988009'),
        ('pink','FLOPO_0988000'),('red','FLOPO_0988001'),('purple','FLOPO_0988008'),
        ('orange','FLOPO_0988002'),('brown','FLOPO_0988003')],
    'outline': [('ovate','FLOPO_0991024'),('elliptic','PATO_0000947'),('oblong','PATO_0000946'),
        ('lanceolate','PATO_0001877'),('obovate','PATO_0001936'),('oblanceolate','PATO_0002330'),
        ('linear','PATO_0001199'),('orbicular','PATO_0001934'),('spatulate','PATO_0001937'),
        ('heart shaped','PATO_0000948'),('triangular','PATO_0001875')],
    'volume': [('spherical','PATO_0001499'),('ovoid','PATO_0001891'),('obovoid','FLOPO_0991025'),
        ('fusiform','PATO_0002400')],
    'hairiness': [('glabrous','PATO_0000453'),('hairy','PATO_0000454'),
        ('pubescent','PATO_0001320'),('tomentose','PATO_0002341')],
    'margin': [('serrated','PATO_0001206'),('dentated','PATO_0001205')],
}
SCOPES = {'colour':['leaf','petal','fruit'], 'outline':['leaf','petal'], 'volume':['fruit'],
          'hairiness':['leaf','fruit'], 'margin':['leaf']}


def make_vocabulary(data):
    profiles = json.loads((data / 'profiles.json').read_text())
    queries = json.loads((data / 'queries.json').read_text())
    records = [r for t in profiles for r in t['records']]
    known = {r['q'] for r in records}
    labels = defaultdict(set)
    for r in records:
        labels[r['ql']].add(r['q'])
    organs = [{'name': name, 'iri': next(r['b'] for r in records if r['bl']==name)} for name in ('leaf','petal','fruit')]
    organs.append({'name':'other','iri':''})
    groups = {}
    for name, states in GROUPS.items():
        values = [{'name': label, 'iri': OBO + iri} for label, iri in states if OBO + iri in known]
        if name == 'colour':
            for label in ('blue','black','gray','cream'):
                if len(labels[label]) == 1:
                    values.append({'name':label,'iri':next(iter(labels[label]))})
        if len(values) < 2:
            continue
        # Every state is checked against the frozen ontology-derived ancestor index.
        if any(v['iri'] not in queries['ancestors'] for v in values):
            raise ValueError('Vocabulary state missing from the pinned ontology')
        values.append({'name':'unknown','iri':''})
        group = {'organs':organs,'colours':values,'attribute_name':name,'organs_in_scope':SCOPES[name]}
        groups[name] = group
        (data / f'vocabulary-{name}.json').write_text(json.dumps(group,indent=2)+'\n')
    schema = {'groups':groups,'scope':'Single focal organ; categorical appearance states with unknown. Subtype states share ontology ancestors, not independent positive labels.',
              'profiles_sha256':digest(data/'profiles.json'),'queries_sha256':digest(data/'queries.json')}
    (data/'multi-vocabulary.json').write_text(json.dumps(schema,indent=2)+'\n')
    return schema


def split_rows(rows, prior_genera, prior_observers=(), prior_hashes=(), prior_dhashes=()):
    """Reserve novel genera; quarantine cross-split observers and perceptual duplicates.

    Original development genera stay in training. Test wins, then validation, then train;
    records leaking across boundaries are discarded rather than relabelled as independent.
    """
    by_genus = defaultdict(list)
    for row in rows:
        by_genus[row['genus']].append(row)
    novel = sorted(set(by_genus)-set(prior_genera), key=lambda g: hashlib.sha256(('flopo-v2:'+g).encode()).hexdigest())
    n = max(1, len(novel)//4)
    assignment = {g:'test' for g in novel[:n]} | {g:'validation' for g in novel[n:2*n]}
    used = defaultdict(set)
    output, excluded = [], Counter()
    priorities = ('test','validation','train')
    dhashes = []
    prior_observers, prior_hashes = set(prior_observers), set(prior_hashes)
    for split in priorities:
        current = []
        for row in rows:
            if assignment.get(row['genus'],'train') != split:
                continue
            keys = {'observation':row['observation_id'],'observer':row['observer_id'],
                    'photo':row['photo_id'],'sha256':row['sha256']}
            if keys['observer'] is None:
                excluded['missing_observer'] += 1; continue
            if split != 'train' and (keys['observer'] in prior_observers or keys['sha256'] in prior_hashes or
                    any((int(row['dhash'],16)^int(h,16)).bit_count()<=3 for h in prior_dhashes)):
                excluded['overlap_with_previous_pilot'] += 1; continue
            if any(value in used[k] for k,value in keys.items()) or any(
                    (int(row['dhash'],16)^h).bit_count()<=3 for h in dhashes):
                excluded['cross_split_identity_or_duplicate'] += 1; continue
            current.append({**row,'split':split})
        output.extend(current)
        for row in current:
            for k,v in [('observation',row['observation_id']),('observer',row['observer_id']),('photo',row['photo_id']),('sha256',row['sha256'])]:
                used[k].add(v)
            dhashes.append(int(row['dhash'],16))
    return output, dict(excluded)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--prior',type=Path,required=True)
    args=parser.parse_args(); schema=make_vocabulary(args.data)
    rows=[json.loads(x) for x in (args.data/'images.jsonl').read_text().splitlines()]
    prior=[json.loads(x) for x in (args.prior/'images.jsonl').read_text().splitlines()]
    previous=json.loads((args.prior/'profiles.json').read_text())
    split, excluded=split_rows(rows,{p['genus'] for p in previous},
        {r['observer_id'] for r in prior},{r['sha256'] for r in prior},{r['dhash'] for r in prior})
    path=args.data/'splits.jsonl';path.write_text(''.join(json.dumps(r)+'\n' for r in split))
    report={'schema_sha256':digest(args.data/'multi-vocabulary.json'),'split_sha256':digest(path),
        'previous_images_sha256':digest(args.prior/'images.jsonl'),'excluded':excluded,
        'groups':{k:len(v['colours'])-1 for k,v in schema['groups'].items()},
        'splits':{s:{'images':len([r for r in split if r['split']==s]),
                    'observations':len({r['observation_id'] for r in split if r['split']==s}),
                    'genera':len({r['genus'] for r in split if r['split']==s})} for s in ('train','validation','test')},
        'evaluation':'Exploratory novel-genus species ranking; test images excluded from fitting and prior regularization. Known candidate flora profiles are available for zero-shot ranking.'}
    (args.data/'protocol.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))


if __name__=='__main__':main()
