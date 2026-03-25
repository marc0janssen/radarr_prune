from datetime import datetime, timedelta
from typing import List, Dict, Any, NamedTuple


def is_on(val: str) -> bool:
    return str(val).strip().upper() == 'ON'


class PruneResult(NamedTuple):
    """Outcome of prune decision. add_import_exclusion is meaningful for reason 'removed'."""

    is_removed: bool
    is_planned: bool
    reason: str
    add_import_exclusion: bool


def decide_prune_action(
    movie: Dict[str, Any],
    config: Dict[str, Any],
    now: datetime | None = None,
) -> PruneResult:
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

    Returns: PruneResult; add_import_exclusion is True when Radarr should add
    an import exclusion on removal (only applies when reason == 'removed').
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
        return PruneResult(False, False, 'keep-tag', False)

    # Missing download date => not downloaded yet
    if not download_date:
        return PruneResult(False, False, 'missing-files', False)

    # Unwanted genres => remove immediately
    if genres & set(unwanted_genres):
        return PruneResult(True, False, 'unwanted-genre', False)

    removal_date = download_date + timedelta(days=remove_after_days)
    time_to_removal = removal_date - now

    # Planned removal if within warning window
    # (0 < time_to_removal <= warn_days_infront)
    if timedelta(0) < time_to_removal <= timedelta(days=warn_days_infront):
        return PruneResult(False, True, 'will-be-removed', False)

    # Removal: older than configured days and disk is full
    # and not excluded by tag/month
    if now - download_date >= timedelta(days=remove_after_days) and is_full:
        monthfound = download_date.month in months_no_exclusion
        exclusiontagsfound = bool(tagsIds & set(tags_no_exclusion_ids))
        add_import_exclusion = not (monthfound or exclusiontagsfound)
        if not (monthfound or exclusiontagsfound):
            return PruneResult(True, False, 'removed', add_import_exclusion)

    return PruneResult(False, False, 'active', False)
