from flopo2.vision.pilot import observation_rows


def test_collection_requires_exact_species_research_grade_and_photo_license():
    profile = {'inat_id': 12, 'taxon': 'taxon', 'name': 'Example plant', 'genus': 'Example', 'family': 'Exampleaceae'}
    row = {'id': 1, 'quality_grade': 'research', 'taxon': {'id': 12},
           'photos': [{'id': 5, 'url': 'https://example.org/square.jpg', 'license_code': 'cc-by'},
                      {'id': 6, 'url': 'https://example.org/square.jpg', 'license_code': None}]}
    assert len(observation_rows(row, profile, 3)) == 1
    assert observation_rows({**row, 'quality_grade': 'needs_id'}, profile, 3) == []
    assert observation_rows({**row, 'taxon': {'id': 13}}, profile, 3) == []
    assert observation_rows(row, profile, 3)[0]['review_status'] == 'unreviewed'
