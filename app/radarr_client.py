"""Minimal Radarr HTTP API v3 client (no arrapi)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
import httpx


class RadarrApiError(Exception):
    """Raised when the Radarr API returns an error response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RadarrClient:
    """
    Thin wrapper around Radarr REST API v3.
    Base URL should be like http://host:7878 (no trailing slash required).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 60.0,
    ) -> None:
        self._base = base_url.rstrip().rstrip('/')
        self._headers = {
            'X-Api-Key': api_key,
            'Accept': 'application/json',
        }
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=self._base,
            headers=self._headers,
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> RadarrClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _raise_for_status(self, response: httpx.Response, context: str) -> None:
        if response.is_success:
            return
        msg = (
            f"{context}: HTTP {response.status_code} "
            f"{response.text[:500]!r}"
        )
        raise RadarrApiError(msg, status_code=response.status_code)

    def ping(self) -> None:
        """Verify URL and API key (GET /api/v3/system/status)."""
        r = self._client.get('/api/v3/system/status')
        self._raise_for_status(r, 'Radarr system/status')

    def get_movies(self) -> list[dict[str, Any]]:
        r = self._client.get('/api/v3/movie')
        self._raise_for_status(r, 'Radarr movie list')
        data = r.json()
        if not isinstance(data, list):
            raise RadarrApiError('Radarr movie list: expected JSON array')
        return data

    def get_tags(self) -> list[dict[str, Any]]:
        r = self._client.get('/api/v3/tag')
        self._raise_for_status(r, 'Radarr tags')
        data = r.json()
        if not isinstance(data, list):
            raise RadarrApiError('Radarr tags: expected JSON array')
        return data

    def get_root_folders(self) -> list[dict[str, Any]]:
        r = self._client.get('/api/v3/rootfolder')
        self._raise_for_status(r, 'Radarr rootfolder')
        data = r.json()
        if not isinstance(data, list):
            raise RadarrApiError('Radarr rootfolder: expected JSON array')
        return data

    def delete_movie(
        self,
        movie_id: int,
        *,
        delete_files: bool,
        add_import_exclusion: bool,
    ) -> None:
        r = self._client.delete(
            f'/api/v3/movie/{movie_id}',
            params={
                'deleteFiles': delete_files,
                'addImportExclusion': add_import_exclusion,
            },
        )
        if r.status_code == 404:
            logging.warning(
                'Radarr DELETE movie/%s: not found (404); may already be '
                'removed.',
                movie_id,
            )
            return
        self._raise_for_status(r, f'Radarr delete movie {movie_id}')


@dataclass
class MovieRecord:
    """Normalized movie fields from GET /api/v3/movie (camelCase JSON)."""

    id: int
    title: str
    year: int
    path: str
    genres: list[str]
    tagsIds: list[int]
    sortTitle: str

    @classmethod
    def from_api(cls, row: dict[str, Any]) -> MovieRecord:
        tags = row.get('tags')
        if isinstance(tags, list):
            tag_ids = [int(t) for t in tags if t is not None]
        else:
            tag_ids = []
        genres = row.get('genres') or []
        if not isinstance(genres, list):
            genres = []
        title = row.get('title') or ''
        st = row.get('sortTitle') or title
        return cls(
            id=int(row['id']),
            title=title,
            year=int(row.get('year') or 0),
            path=str(row.get('path') or ''),
            genres=[str(g) for g in genres],
            tagsIds=tag_ids,
            sortTitle=str(st),
        )
