"""Thin client for the base app's REST API (/api/v1). Only documented endpoints are used."""
from __future__ import annotations

import os

import httpx

DEFAULT_BASE = os.environ.get("BASE_API", "http://127.0.0.1:8000/api/v1")


class BaseAPIError(Exception):
    """The base app could not give us what we asked for."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class NotReady(BaseAPIError):
    """The recording is still being transcribed."""


class BaseClient:
    def __init__(self, base_url: str = DEFAULT_BASE, http: httpx.Client | None = None, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.http = http or httpx.Client(timeout=timeout)

    def _get(self, path: str):
        try:
            # base_url may be relative ("/api/v1") when `http` carries its own base_url (tests)
            r = self.http.get(f"{self.base_url}{path}")
        except httpx.HTTPError as e:
            raise BaseAPIError(f"Cannot reach the base app at {self.base_url} ({e.__class__.__name__}). "
                               "Is its backend running?") from e
        if r.status_code == 202:
            detail = _detail(r) or "Processing in progress."
            raise NotReady(detail, 409)
        if r.status_code == 404:
            raise BaseAPIError(_detail(r) or "Not found.", 404)
        if r.status_code >= 400:
            raise BaseAPIError(f"Base app returned {r.status_code}: {_detail(r)}", 502)
        return r.json()

    def health(self) -> dict:
        return self._get("/health")

    def recordings(self) -> list[dict]:
        return self._get("/media")

    def transcript(self, recording_id: str) -> dict:
        return self._get(f"/transcriptions/{recording_id}")

    def analytics(self, recording_id: str) -> dict | None:
        """Optional: the report works without it."""
        try:
            return self._get(f"/analytics/{recording_id}")
        except BaseAPIError:
            return None


def _detail(r: httpx.Response) -> str:
    try:
        d = r.json()
        return str(d.get("detail", d)) if isinstance(d, dict) else str(d)
    except ValueError:
        return r.text[:200]
