"""Audit representable queries and prepare unreviewed source-event candidates."""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from .logic import Expr
from .model import localized_scene, ungrounded_atoms


def audit(data):
    vocabulary = json.loads((data / 'vocabulary.json').read_text())
    queries = json.loads((data / 'queries.json').read_text())
    profiles = json.loads((data / 'profiles.json').read_text())
    photos = [json.loads(line) for line in (data / 'images.jsonl').read_text().splitlines()]
    scene = localized_scene(vocabulary, ['r0'], {'r0': True}, queries['ancestors'])
    complete, partial, impossible = [], {}, []
    for iri, definition in queries['supported'].items():
        expr = Expr.from_json(definition)
        missing = ungrounded_atoms(expr, vocabulary, queries['ancestors'])
        formula = scene.ground(expr, 'plant')
        if formula is False:
            impossible.append(iri)
        elif missing:
            partial[iri] = sorted(missing)
        else:
            complete.append(iri)
    sources = defaultdict(list)
    for profile in profiles:
        for record in profile['records']:
            if record.get('pc') in complete and not record.get('qualifier'):
                sources[(profile['taxon'], record['pc'])].append(record)
    source_hash = hashlib.sha256((data / 'profiles.json').read_bytes()).hexdigest()
    events, seen = [], set()
    for photo in photos:
        for (taxon, query), records in sources.items():
            if taxon != photo['taxon'] or (photo['photo_id'], query) in seen:
                continue
            seen.add((photo['photo_id'], query))
            events.append({'photo_id': photo['photo_id'], 'query_iri': query, 'regions': [],
                'source_record_ids': sorted({r['r'] for r in records}), 'source_snapshot_sha256': source_hash,
                'source_text': sorted({r['text'] for r in records}), 'taxon': taxon,
                'review_status': 'unreviewed', 'reviewer': '', 'scope_compatible': False,
                'epsilon': None, 'reliability': None})
    report = {'compiled_queries': len(queries['supported']), 'fully_grounded_queries': len(complete),
        'fully_grounded_query_ids': sorted(complete), 'partially_grounded_queries': partial,
        'no_proof_with_this_vocabulary': impossible, 'unreviewed_candidate_events': len(events),
        'candidate_images': len({e['photo_id'] for e in events}),
        'candidate_taxa': len({e['taxon'] for e in events}),
        'interpretation': 'Vocabulary/compiler coverage only; no image truth or source stability verified.'}
    for filename, content in [('coverage.json', report), ('weak-event-candidates.json', events)]:
        (data / filename).write_text(json.dumps(content, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if isinstance(v, int)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('local-corpora/visual-pilot'))
    audit(parser.parse_args().data)
