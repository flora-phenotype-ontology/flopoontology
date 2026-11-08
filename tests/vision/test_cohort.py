from flopo2.vision.cohort import inventory, partition, hash_bucket


def record(quality, iri='q1'):
    return {'r': 'assertion', 'b': 'leaf', 'bl': 'leaf', 'q': iri, 'ql': quality,
            'status': 'accepted', 'text': quality, 'src': 'flora'}


def test_unrepresented_alternative_is_not_narrowed():
    p = [{'taxon': 'a', 'records': [record('ovate'), record('unrepresented shape', 'q2')]}]
    assert inventory(p, minimum_taxa=1)['events'] == []


def test_positive_disjunction_does_not_invent_negatives():
    p = [{'taxon': 'a', 'records': [record('ovate'), record('oblong', 'q2')]}]
    result = inventory(p, minimum_taxa=1)
    assert len(result['events']) == 1
    assert len(result['events'][0]['any_of']) == 2
    assert result['events'][0]['image_truth'] == 'unknown'


def test_scope_cannot_reenter_through_another_taxon():
    a = record('ovate'); a['text'] = 'young leaves ovate'
    result = inventory([{'taxon': 'a', 'records': [a]}, {'taxon': 'b', 'records': [record('ovate')]}], minimum_taxa=1)
    assert {e['taxon'] for e in result['events']} == {'b'}


def test_surface_specific_hair_absence_is_not_whole_leaf_absence():
    a = record('glabrous'); a['text'] = 'glabrous above, pubescent beneath'
    assert inventory([{'taxon': 'a', 'records': [a]}], minimum_taxa=1)['events'] == []


def test_split_removes_shared_observers_and_keeps_heldout_taxa_out():
    genera = [str(i) for i in range(100)]
    train = next(g for g in genera if hash_bucket(g) < 70)
    test = next(g for g in genera if hash_bucket(g) >= 85)
    def row(i, genus, observer):
        return {'observation_id': i, 'photo_id': i, 'sha256': str(i),
                'genus': genus, 'taxon': genus, 'observer_id': observer}
    rows, excluded = partition([row(1, train, 7), row(2, test, 7), row(3, train, 8)], heldout_taxa=[train])
    assert all(r['split'] != 'train' for r in rows)
    rows, excluded = partition([row(1, train, 7), row(2, test, 7), row(3, train, 8)])
    assert [r['photo_id'] for r in rows] == [3]
    assert excluded['cross_split_observer'] == 2
