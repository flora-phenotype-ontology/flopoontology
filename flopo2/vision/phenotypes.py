"""Compile released FLOPO phenotype queries covered by the current visual vocabulary."""
import argparse
from collections import Counter
import json
from pathlib import Path

from .extract import digest
from .logic import Compiler, UnsupportedExpression, OWL, RDFS
from .weak_train import truth_mask


def main():
    import pyoxigraph as ox
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release',type=Path,required=True)
    parser.add_argument('--data',type=Path,required=True)
    args=parser.parse_args()
    release=json.loads((args.release/'release.json').read_text())
    graph=next(g for g in release['graphs'] if g['file'].endswith('-flopo.nq'))
    path=args.release/graph['file']
    if digest(path)!=graph['sha256']:raise ValueError('Changed released ontology graph')
    store=ox.Store();store.bulk_load(path=str(path),format=ox.RdfFormat.N_QUADS)
    compiler=Compiler(store)
    schema=json.loads((args.data/'multi-vocabulary.json').read_text())
    ancestors=json.loads((args.data/'queries.json').read_text())['ancestors']
    classes=sorted({q.subject.value for q in store.quads_for_pattern(None,ox.NamedNode(OWL+'equivalentClass'),None,None)
                    if isinstance(q.subject,ox.NamedNode) and q.subject.value.startswith('http://purl.obolibrary.org/obo/FLOPO_')})
    supported={};counts=Counter()
    for iri in classes:
        if any(getattr(v,'value','') in ('true','1') for v in compiler.objects(ox.NamedNode(iri),OWL+'deprecated')):
            counts['deprecated']+=1;continue
        try:expr=compiler.compile(iri)
        except UnsupportedExpression:counts['unsupported_OWL']+=1;continue
        matches=[]
        for name,v in schema['groups'].items():
            try:mask=list(truth_mask(expr,v,ancestors))
            except ValueError:continue
            n=len(v['colours'])
            for i,o in enumerate(v['organs']):
                if o['name'] not in v['organs_in_scope']:mask[i*n:(i+1)*n]=[0.0]*n
            if any(mask):matches.append((name,mask))
        if len(matches)!=1:
            counts['ambiguous_attribute' if matches else 'outside_visual_vocabulary']+=1;continue
        labels=compiler.objects(ox.NamedNode(iri),RDFS+'label')
        name,mask=matches[0]
        supported[iri]={'label':labels[0].value if labels else iri,'attribute':name,'mask':mask}
    result={'ontology_graph_sha256':graph['sha256'],'schema_sha256':digest(args.data/'multi-vocabulary.json'),
        'defined_FLOPO_classes':len(classes),'supported':supported,'excluded':dict(counts),
        'note':'Probabilities of observed support under the scoped visual model, not independently validated trait accuracy.'}
    (args.data/'phenotype-queries.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'defined_FLOPO_classes':len(classes),'supported':len(supported),'excluded':dict(counts)}))


if __name__=='__main__':main()
