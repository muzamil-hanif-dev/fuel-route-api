"""
Phase 3a — Geocoding: turn a place name into coordinates.

"Geocoding" means converting text like "Dallas, TX" into a (latitude, longitude)
point. We use OpenStreetMap's free Nominatim service (no API key needed).

We call this exactly TWICE per request (start + finish). Results are cached, so
identical lookups don't hit the network again — which also respects Nominatim's
fair-use policy.
"""
from __future__ import annotations

from functools import lru_cache

import requests
from django.conf import settings


class GeocodingError(Exception):
    """Raised when a place name cannot be turned into coordinates."""


@lru_cache(maxsize=512)
def geocode(place: str) -> tuple[float, float]:
    """
    Return (lat, lng) for a USA place name like "Dallas, TX".

    Cached with @lru_cache so repeated identical lookups are free (no network).
    Raises GeocodingError if the place can't be found or the service fails.
    """
    place = place.strip()
    if not place:
        raise GeocodingError("Location cannot be empty.")

    params = {
        "q": place,
        "format": "json",
        "limit": 1,             # we only want the single best match
        "countrycodes": "us",   # keep results inside the USA (per the brief)
    }
    # Nominatim's usage policy REQUIRES a descriptive User-Agent identifying the app.
    headers = {"User-Agent": settings.HTTP_USER_AGENT}

    try:
        resp = requests.get(
            settings.NOMINATIM_URL, params=params, headers=headers, timeout=10
        )
        resp.raise_for_status()
        results = resp.json()
    except requests.RequestException as exc:
        raise GeocodingError(f"Geocoding service error for '{place}': {exc}") from exc

    if not results:
        raise GeocodingError(f"Could not find a US location for '{place}'.")

    top = results[0]
    return float(top["lat"]), float(top["lon"])
