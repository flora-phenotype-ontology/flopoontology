"""Pilot weak labels for trait recognition from photographs.

Turns the flora statements written by ``flopo2.traitvision.extract`` into one row per
(taxon, trait): the set of classes the floras allow for that taxon. Rules:

* a class is allowed when any flora states it, alone or as a member of "X or Y";
* a value said to occur "rarely"/"sometimes"/"occasionally" goes to ``rare`` and is not a positive;
* a trait a flora does not mention is unknown: there is no row, never a negative;
* colour values are mapped to basic colours through the FLOPO colour hierarchy;
* a compound leaf is also inferred from any statement about a leaflet (part-of);
* spines: stated present / spiny against stated absent (negation).

    python -m flopo2.traitvision.labels local-corpora/trait-vision/pilot-assertions.tsv local-corpora/trait-vision
"""
import collections
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RARE = {'rarely', 'sometimes', 'occasionally', 'seldom', 'rare'}
FLOWER = {'flower', 'corolla', 'petal', 'tepal', 'perianth', 'corolla lobe'}
LEAF = {'leaf', 'leaf lamina'}
BASIC = {'FLOPO_0988009': 'white', 'FLOPO_0988004': 'yellow', 'FLOPO_0988001': 'red', 'FLOPO_0988000': 'pink',
         'FLOPO_0988008': 'purple', 'FLOPO_0988007': 'blue', 'FLOPO_0988002': 'orange', 'FLOPO_0988006': 'green',
         'FLOPO_0988003': 'brown', 'FLOPO_0988011': 'black'}
HABIT = {'PATO_0002352': 'herb', 'FLOPO_0987002': 'shrub', 'FLOPO_0987001': 'tree', 'FLOPO_0991108': 'climber'}
ARRANGEMENT = {'PATO_0001932': 'alternate', 'PATO_0001933': 'opposite', 'PATO_0001951': 'whorled'}
MARGIN = {'PATO_0104359': 'entire', 'PATO_0001205': 'toothed', 'PATO_0001206': 'toothed', 'FLOPO_0991081': 'toothed',
          'PATO_0001979': 'lobed'}
COMPOUND = {'PATO_0000410': 'compound', 'FLOPO_0991014': 'compound', 'FLOPO_0980424': 'compound',
            'FLOPO_0991161': 'compound', 'PATO_0001503': 'simple'}
INFLORESCENCE = ('raceme', 'panicle', 'cyme', 'spike', 'umbel', 'corymb', 'capitulum')
SPINE_PARTS = {'thorn', 'spine', 'prickle', 'leaf spine'}
PRESENT, SPINY = 'PATO_0000467', 'PATO_0001365'


def ontology():
    """Superclass map of FLOPO/PATO value classes, read from the release file."""
    text = (ROOT / 'ontology/flopo.owl').read_text()
    sup = collections.defaultdict(set)
    pat = r'<(?:rdf:Description|owl:Class) rdf:about="http://purl.obolibrary.org/obo/(\w+)">(.*?)</(?:rdf:Description|owl:Class)>'
    for m in re.finditer(pat, text, re.S):
        for s in re.findall(r'<rdfs:subClassOf rdf:resource="http://purl.obolibrary.org/obo/(\w+)"/>', m.group(2)):
            sup[m.group(1)].add(s)
    return sup


def basic_colours(value, sup, cache={}):
    """Basic colours a colour value falls under (most specific basic ancestors only)."""
    if value not in cache:
        found, todo, seen = set(), [value], set()
        while todo:
            v = todo.pop()
            if v in seen:
                continue
            seen.add(v)
            if v in BASIC:
                found.add(BASIC[v])      # stop here: do not climb above a basic colour
            else:
                todo.extend(sup.get(v, ()))
        cache[value] = found
    return cache[value]


def classes(row, sup):
    """(trait, class) pairs one statement supports."""
    ent, attr, text = row['entity'], row['attr'], row['text'].lower()
    values = row['values'].split('|')
    out = []
    if ent in SPINE_PARTS:
        if attr == PRESENT or row['negated'] == '0':
            out.append(('spines', 'absent' if row['negated'] == '1' else 'present'))
        return out
    if SPINY in values and ent in ('whole plant', 'stem'):
        return [('spines', 'absent' if row['negated'] == '1' else 'present')]
    if row['negated'] == '1' or ':ctx' in row['operator']:
        return out                       # other negations and stage/position statements are not used in the pilot
    if ent == 'leaflet':
        out.append(('leaf_complexity', 'compound'))
    for v in values:
        if ent == 'whole plant' and v in HABIT:
            out.append(('habit', HABIT[v]))
        elif attr == 'PATO_0000014' and (ent in FLOWER or ent.endswith('fruit')):
            trait = 'flower_colour' if ent in FLOWER else 'fruit_colour'
            out.extend((trait, c) for c in basic_colours(v, sup))
        elif ent in LEAF and v in ARRANGEMENT:
            out.append(('leaf_arrangement', ARRANGEMENT[v]))
        elif ent in LEAF and v in COMPOUND and not re.search(r'hair|stellate|vein|nerv', text):
            out.append(('leaf_complexity', COMPOUND[v]))
        if ent in LEAF | {'leaf margin', 'leaflet'} and v in MARGIN:
            out.append(('leaf_margin', MARGIN[v]))
    if attr == PRESENT and ent.endswith(' inflorescence') and ent.split()[0] in INFLORESCENCE:
        out.append(('inflorescence', ent.split()[0]))
    return out


def main(src, outdir):
    sup = ontology()
    allowed = collections.defaultdict(set)
    rare = collections.defaultdict(set)
    sources = collections.defaultdict(set)
    family = {}
    for row in csv.DictReader(open(src), delimiter='\t', quoting=csv.QUOTE_NONE):
        if row['rank'] != 'species' or not re.match(r'[A-Z][a-z-]+ [a-z-]+( |$)', row['taxon']):   # authors may follow
            continue
        family.setdefault(row['taxon'], row['family'])
        for trait, cls in classes(row, sup):
            key = (row['taxon'], trait)
            (rare if row['frequency'] in RARE else allowed)[key].add(cls)
            sources[key].add(row['source'])
    outdir = Path(outdir)
    summary = collections.defaultdict(collections.Counter)
    with open(outdir / 'pilot-labels.tsv', 'w') as out:
        out.write('taxon\tgenus\tfamily\ttrait\tallowed\trare\tsources\n')
        for (taxon, trait), cls in sorted(allowed.items()):
            if trait == 'spines' and cls == {'present', 'absent'}:
                continue                 # floras disagree: unknown
            r = rare.get((taxon, trait), set()) - cls
            out.write(f"{taxon}\t{taxon.split()[0]}\t{family[taxon]}\t{trait}\t{'|'.join(sorted(cls))}\t"
                      f"{'|'.join(sorted(r))}\t{'|'.join(sorted(sources[(taxon, trait)]))}\n")
            summary[trait]['taxa'] += 1
            summary[trait]['single_value' if len(cls) == 1 else 'several_values'] += 1
            for c in cls:
                summary[trait]['class:' + c] += 1
    (outdir / 'pilot-labels-summary.json').write_text(json.dumps(summary, indent=1, sort_keys=True) + '\n')
    for trait, c in sorted(summary.items()):
        print(trait, dict(c))
    print('taxa with any pilot label:', len({t for t, _ in allowed}))


if __name__ == '__main__':
    main(*sys.argv[1:3])
