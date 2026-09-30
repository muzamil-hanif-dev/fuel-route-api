"""
Phase 4 — The fuel-stop algorithm (no API calls; pure local math).

Two steps:
  1. stations_near_route(): out of all 6,249 stations, keep only the ones within a
     few miles of the actual road, and work out how far along the trip each one sits
     ("position" = miles from start). This uses vectorized numpy — every station is
     measured against the route in one shot.
  2. plan_fuel_stops(): a greedy strategy that picks WHERE to buy fuel so the total
     cost is as low as possible, while never driving more than the tank's range
     between fill-ups.

Assumption (documented for the interview): the vehicle departs with a FULL tank.
The origin isn't a priced fuel station, so we can't charge for that first tank —
we only charge for fuel actually bought at stations along the route. For long
trips (the interesting case) this means real stops and real costs.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass, field

import numpy as np

from .geo import haversine_miles
from .routing_osrm import Route
from .stations import StationStore


class InfeasibleRoute(Exception):
    """Raised when the route can't be fueled within the vehicle's range."""


@dataclass
class FuelStop:
    name: str
    city: str
    state: str
    lat: float
    lng: float
    price: float                 # $/gallon at this station
    distance_from_start_miles: float
    gallons: float = 0.0         # how much we buy here
    cost: float = 0.0            # gallons * price


# ---------------------------------------------------------------------------
# Step 1 — narrow 6,249 stations down to the ones near this route
# ---------------------------------------------------------------------------
def stations_near_route(store: StationStore, route: Route, buffer_miles: float) -> list[dict]:
    """
    Return the stations within `buffer_miles` of the route, each tagged with its
    `position` (miles from start), sorted by position.
    """
    rlat = np.array([c[0] for c in route.coords], dtype=float)
    rlng = np.array([c[1] for c in route.coords], dtype=float)
    rcum = route.cum_miles

    # The route can have thousands of points; we only need a sample to test
    # "is this station near the road?" at 10-mile granularity. Downsample for speed.
    step = max(1, len(rlat) // 1500)
    slat, slng, scum = rlat[::step], rlng[::step], rcum[::step]

    # Cheap pre-filter: ignore stations outside the route's bounding box (+ padding).
    # ~69 miles per degree of latitude; longitude degrees are shorter, so pad more.
    lat_pad = buffer_miles / 69.0
    lng_pad = buffer_miles / 40.0
    in_box = (
        (store.lat >= rlat.min() - lat_pad) & (store.lat <= rlat.max() + lat_pad)
        & (store.lng >= rlng.min() - lng_pad) & (store.lng <= rlng.max() + lng_pad)
    )
    idx = np.where(in_box)[0]
    if idx.size == 0:
        return []

    # Precise step: distance from each boxed station to every sampled route point,
    # computed all at once. Shape = (num_stations, num_sample_points).
    clat = store.lat[idx][:, None]
    clng = store.lng[idx][:, None]
    dist = haversine_miles(clat, clng, slat[None, :], slng[None, :])

    min_dist = dist.min(axis=1)       # closest the station gets to the road
    nearest = dist.argmin(axis=1)     # which route point it's closest to
    near = min_dist <= buffer_miles   # keep only genuinely near-route stations

    sel = idx[near]
    positions = scum[nearest[near]]   # that route point's miles-from-start

    candidates = [
        {
            "name": str(store.name[i]),
            "city": str(store.city[i]),
            "state": str(store.state[i]),
            "lat": float(store.lat[i]),
            "lng": float(store.lng[i]),
            "price": float(store.price[i]),
            "position": float(pos),
        }
        for i, pos in zip(sel, positions)
    ]
    candidates.sort(key=lambda c: c["position"])
    return candidates


# ---------------------------------------------------------------------------
# Step 2 — greedy: choose the cheapest legal set of fill-ups
# ---------------------------------------------------------------------------
def plan_fuel_stops(
    candidates: list[dict],
    total_miles: float,
    range_miles: float,
    mpg: float,
) -> tuple[list[FuelStop], float]:
    """
    Decide where to refuel to minimize cost, never exceeding `range_miles` between
    stops. Returns (list of FuelStops where we actually buy, total_cost).

    The rule at each station (classic optimal refueling):
      - If a cheaper station is reachable on a full tank, buy JUST ENOUGH to get
        there (don't overpay at the pricey station).
      - Otherwise, FILL UP here and drive to the cheapest station within range.
    The start is treated as a free full tank (see module docstring).
    """
    positions = [c["position"] for c in candidates]

    pos = 0.0
    tank = range_miles     # start full & free
    price_here = 0.0       # starting fuel is free (no station at the origin)
    here_stop: FuelStop | None = None
    stops: list[FuelStop] = []
    total_cost = 0.0
    eps = 1e-6

    def buy(miles_of_fuel: float) -> None:
        nonlocal tank, total_cost
        if miles_of_fuel <= eps:
            return
        gallons = miles_of_fuel / mpg
        cost = gallons * price_here
        tank += miles_of_fuel
        total_cost += cost
        if here_stop is not None:        # not the free start
            here_stop.gallons += gallons
            here_stop.cost += cost

    while True:
        remaining = total_miles - pos
        if tank >= remaining - eps:
            break  # enough fuel to coast to the destination

        # Stations reachable on a FULL tank from here: position in (pos, pos+range].
        lo = bisect.bisect_right(positions, pos)
        hi = bisect.bisect_right(positions, pos + range_miles)
        window = candidates[lo:hi]
        if not window:
            raise InfeasibleRoute(
                f"No fuel station within {range_miles:.0f} miles after mile {pos:.0f}."
            )

        if remaining <= range_miles:
            # Destination is reachable on a full tank — buy just enough here to finish.
            buy((remaining - tank))
            break

        cheaper = [c for c in window if c["price"] < price_here]
        if cheaper:
            target = cheaper[0]                       # nearest cheaper station
            need = (target["position"] - pos) - tank  # just enough to reach it
            buy(need)
        else:
            # Nothing cheaper ahead within range: fill up fully, head to the cheapest.
            target = min(window, key=lambda c: (c["price"], -c["position"]))
            buy(range_miles - tank)

        # Drive to the chosen target station.
        dist = target["position"] - pos
        tank -= dist
        pos = target["position"]
        price_here = target["price"]
        here_stop = FuelStop(
            name=target["name"], city=target["city"], state=target["state"],
            lat=target["lat"], lng=target["lng"], price=target["price"],
            distance_from_start_miles=pos,
        )
        stops.append(here_stop)

    # Keep only stations where we actually bought fuel (drop pass-throughs).
    real_stops = [s for s in stops if s.gallons > eps]
    return real_stops, total_cost
