from datetime import datetime, timedelta

from app.radarr_prune_logic import PruneResult, decide_prune_action


def test_keep_tag():
    now = datetime(2025, 1, 10)
    movie = {
        'tagsIds': [1],
        'genres': [],
        'download_date': datetime(2024, 12, 1),
    }
    config = {
        'tags_keep_ids': [1],
        'unwanted_genres': [],
        'remove_after_days': 30,
        'warn_days_infront': 5,
        'tags_no_exclusion_ids': [],
        'months_no_exclusion': [],
        'is_full': True,
    }

    r = decide_prune_action(movie, config, now)
    assert r == PruneResult(False, False, 'keep-tag', False)


def test_missing_files():
    now = datetime(2025, 1, 10)
    movie = {'tagsIds': [], 'genres': [], 'download_date': None}
    config = {
        'tags_keep_ids': [],
        'unwanted_genres': [],
        'remove_after_days': 30,
        'warn_days_infront': 5,
        'tags_no_exclusion_ids': [],
        'months_no_exclusion': [],
        'is_full': True,
    }

    r = decide_prune_action(movie, config, now)
    assert r == PruneResult(False, False, 'missing-files', False)


def test_unwanted_genre():
    now = datetime(2025, 1, 10)
    movie = {
        'tagsIds': [],
        'genres': ['Horror'],
        'download_date': datetime(2024, 1, 1),
    }
    config = {
        'tags_keep_ids': [],
        'unwanted_genres': ['Horror'],
        'remove_after_days': 30,
        'warn_days_infront': 5,
        'tags_no_exclusion_ids': [],
        'months_no_exclusion': [],
        'is_full': True,
    }

    r = decide_prune_action(movie, config, now)
    assert r == PruneResult(True, False, 'unwanted-genre', False)


def test_warn_window():
    download_date = datetime(2024, 12, 15)
    now = download_date + timedelta(days=25)
    movie = {'tagsIds': [], 'genres': [], 'download_date': download_date}
    config = {
        'tags_keep_ids': [],
        'unwanted_genres': [],
        'remove_after_days': 30,
        'warn_days_infront': 7,
        'tags_no_exclusion_ids': [],
        'months_no_exclusion': [],
        'is_full': True,
    }

    r = decide_prune_action(movie, config, now)
    assert r == PruneResult(False, True, 'will-be-removed', False)


def test_remove_when_full_and_old():
    download_date = datetime(2024, 1, 1)
    now = download_date + timedelta(days=400)
    movie = {'tagsIds': [], 'genres': [], 'download_date': download_date}
    config = {
        'tags_keep_ids': [],
        'unwanted_genres': [],
        'remove_after_days': 30,
        'warn_days_infront': 7,
        'tags_no_exclusion_ids': [],
        'months_no_exclusion': [],
        'is_full': True,
    }

    r = decide_prune_action(movie, config, now)
    assert r == PruneResult(True, False, 'removed', True)


def test_remove_skipped_when_month_exclusion():
    download_date = datetime(2024, 1, 15)
    now = download_date + timedelta(days=400)
    movie = {'tagsIds': [], 'genres': [], 'download_date': download_date}
    config = {
        'tags_keep_ids': [],
        'unwanted_genres': [],
        'remove_after_days': 30,
        'warn_days_infront': 7,
        'tags_no_exclusion_ids': [],
        'months_no_exclusion': [1],
        'is_full': True,
    }

    r = decide_prune_action(movie, config, now)
    assert r.reason == 'active'
    assert r.add_import_exclusion is False
