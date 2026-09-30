"""
Shared geo math.

The Earth is round, so the straight-line distance between two latitude/longitude
points isn't simple subtraction — we use the standard "haversine" formula.

This function is written with numpy so it works BOTH on single numbers and on whole
arrays of points at once (broadcasting). Phase 4 relies on the array form to measure
thousands of stations against the route in one fast operation.
"""
from __future__ import annotations

import numpy as np

# Earth's mean radius in miles (the brief works in miles).
EARTH_RADIUS_MILES = 3958.7613


def haversine_miles(lat1, lng1, lat2, lng2):
    """
    Great-circle distance in miles between point 1 and point 2.

    Each argument may be a single number or a numpy array; if you pass arrays,
    the result is an array of distances (computed all at once).
    """
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlng / 2) ** 2
    return EARTH_RADIUS_MILES * 2 * np.arcsin(np.sqrt(a))
