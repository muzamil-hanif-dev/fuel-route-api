"""
Phase 3b — Routing via OSRM (free, no API key).

We make exactly ONE call to OSRM per request. In that single response we get:
  - the route's shape (an encoded "polyline" — a compact string of the road path)
  - the total driving distance (in meters)

From that we build everything else locally (zero extra calls):
  - decode the polyline into a list of (lat, lng) points along the road
  - compute how many miles from the start each of those points is ("cum_miles"),
    which Phase 4 uses to place fuel stops at the right spot along the route.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import polyline
import requests
from django.conf import settings

from .geo import haversine_miles

METERS_PER_MILE = 1609.344


class RoutingError(Exception):
    """Raised when OSRM can't return a route."""


@dataclass
class Route:
    coords: list[tuple[float, float]]  # (lat, lng) points along the road
    cum_miles: np.ndarray              # miles-from-start at each point (same length)
    total_miles: float                 # total driving distance of the trip


def get_route(start: tuple[float, float], finish: tuple[float, float]) -> Route:
    """
    Ask OSRM for the driving route from start to finish (both are (lat, lng)).
    Makes ONE HTTP call. Returns a Route with geometry + distance measurements.
    """
    # OSRM wants coordinates as "lng,lat" (longitude first) and pairs separated by ";".
    coords_param = f"{start[1]},{start[0]};{finish[1]},{finish[0]}"
    url = f"{settings.OSRM_URL}/{coords_param}"
    params = {
        "overview": "full",       # give us the full detailed geometry
        "geometries": "polyline",  # as a compact encoded polyline string
    }

    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise RoutingError(f"Routing service error: {exc}") from exc

    if data.get("code") != "Ok" or not data.get("routes"):
        raise RoutingError("No route found between the given locations.")

    route = data["routes"][0]

    # OSRM's own reported total distance (meters -> miles). This is the authoritative
    # trip distance we report to the user.
    total_miles = route["distance"] / METERS_PER_MILE

    # Decode the polyline string into [(lat, lng), (lat, lng), ...] road points.
    points = polyline.decode(route["geometry"])
    lat = np.array([p[0] for p in points], dtype=float)
    lng = np.array([p[1] for p in points], dtype=float)

    # Distance of each hop between consecutive points, then a running total.
    # cum_miles[i] = miles from the start to point i (cum_miles[0] = 0).
    seg_miles = haversine_miles(lat[:-1], lng[:-1], lat[1:], lng[1:])
    cum_miles = np.concatenate([[0.0], np.cumsum(seg_miles)])

    # The polyline is slightly simplified, so its summed length can differ a hair
    # from OSRM's exact road distance. Scale our running totals so the final point
    # equals OSRM's total — keeps positions and the reported distance consistent.
    if cum_miles[-1] > 0:
        cum_miles = cum_miles * (total_miles / cum_miles[-1])

    return Route(coords=points, cum_miles=cum_miles, total_miles=total_miles)
