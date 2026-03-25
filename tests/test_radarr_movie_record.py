"""Sanity checks for Radarr JSON → MovieRecord mapping."""

from app.radarr_client import MovieRecord


def test_movie_record_from_api_camelcase():
    row = {
        'id': 42,
        'title': 'Test Film',
        'sortTitle': 'test film',
        'year': 2020,
        'path': '/movies/Test Film (2020)',
        'genres': ['Action', 'Drama'],
        'tags': [1, 2, 3],
    }
    m = MovieRecord.from_api(row)
    assert m.id == 42
    assert m.title == 'Test Film'
    assert m.sortTitle == 'test film'
    assert m.year == 2020
    assert m.path == '/movies/Test Film (2020)'
    assert m.genres == ['Action', 'Drama']
    assert m.tagsIds == [1, 2, 3]


def test_movie_record_sort_title_fallback():
    row = {
        'id': 1,
        'title': 'Only Title',
        'year': 2019,
        'path': '/x',
        'genres': [],
        'tags': [],
    }
    m = MovieRecord.from_api(row)
    assert m.sortTitle == 'Only Title'
