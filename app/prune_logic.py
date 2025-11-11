from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any


def is_on(val: str) -> bool:
    return str(val).strip().upper() == 'ON'


def decide_prune_action(
    movie: Dict[str, Any],
    config: Dict[str, Any],
    now: datetime | None = None,
) -> Tuple[bool, bool, str]:
    """
    Decide whether a movie should be removed or planned for removal.

    movie: {
        'tagsIds': List[int],
        'genres': List[str],
        'download_date': datetime | None,
    }

    config: {
        'tags_keep_ids': List[int],
        'unwanted_genres': List[str],
        'remove_after_days': int,
        'warn_days_infront': int,
        'tags_no_exclusion_ids': List[int],
        'months_no_exclusion': List[int],
        'is_full': bool,
    }

    Returns: (isRemoved, isPlanned, reason)
    """
    now = now or datetime.now()

    tags_keep_ids: List[int] = config.get('tags_keep_ids', [])
    unwanted_genres: List[str] = config.get('unwanted_genres', [])
    remove_after_days: int = int(config.get('remove_after_days', 0))
    warn_days_infront: int = int(config.get('warn_days_infront', 0))
    tags_no_exclusion_ids: List[int] = config.get('tags_no_exclusion_ids', [])
    months_no_exclusion: List[int] = config.get('months_no_exclusion', [])
    is_full: bool = bool(config.get('is_full', False))

    tagsIds = set(movie.get('tagsIds') or [])
    genres = set(movie.get('genres') or [])
    download_date = movie.get('download_date')

    # Keep if any keep-tag present
    if tagsIds & set(tags_keep_ids):
        return False, False, 'keep-tag'

    # Missing download date => not downloaded yet
    if not download_date:
        return False, False, 'missing-files'

    # Unwanted genres => remove immediately
    if genres & set(unwanted_genres):
        return True, False, 'unwanted-genre'

    removal_date = download_date + timedelta(days=remove_after_days)
    time_to_removal = removal_date - now

    # Planned removal if within warning window
    # (0 < time_to_removal <= warn_days_infront)
    if timedelta(0) < time_to_removal <= timedelta(days=warn_days_infront):
        return False, True, 'will-be-removed'

    # Removal: older than configured days and disk is full
    # and not excluded by tag/month
    if now - download_date >= timedelta(days=remove_after_days) and is_full:
        monthfound = download_date.month in months_no_exclusion
        exclusiontagsfound = bool(tagsIds & set(tags_no_exclusion_ids))
        if not (monthfound or exclusiontagsfound):
            return True, False, 'removed'

    return False, False, 'active'
