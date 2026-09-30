"""
Unit tests for the routing app.

These test the PURE logic (the fuel algorithm, the near-route filter, input
validation) with hand-made inputs — no network calls — so they run fast and
reliably every time.
"""
import numpy as np
import pandas as pd
from django.test import TestCase
from rest_framework.test import APIClient

from routing.services.fuel import (
    InfeasibleRoute,
    plan_fuel_stops,
    stations_near_route,
)
from routing.services.geo import haversine_miles
from routing.services.routing_osrm import Route
from routing.services.stations import StationStore

RANGE = 500.0   # miles per tank
MPG = 10.0      # miles per gallon


def _station(position, price, name="S"):
    """Build one candidate station dict at a given mile-position and price."""
    return {
        "name": name, "city": name, "state": "TX",
        "lat": 0.0, "lng": 0.0, "price": price, "position": position,
    }


class FuelAlgorithmTests(TestCase):
    def test_short_trip_needs_no_stops(self):
        """A trip shorter than the tank range needs no refuel (starts full)."""
        stops, cost = plan_fuel_stops(
            [_station(100, 3.0)], total_miles=300, range_miles=RANGE, mpg=MPG
        )
        self.assertEqual(stops, [])
        self.assertEqual(cost, 0.0)

    def test_long_trip_picks_the_cheaper_station(self):
        """When a refuel is required, the cheaper reachable station wins."""
        candidates = [_station(450, 3.0, "CHEAP"), _station(480, 5.0, "PRICEY")]
        stops, cost = plan_fuel_stops(
            candidates, total_miles=800, range_miles=RANGE, mpg=MPG
        )
        self.assertEqual(len(stops), 1)
        self.assertEqual(stops[0].name, "CHEAP")
        # Needs 800 mi total; first 500 free; remaining 300 mi = 30 gal @ $3.0 = $90.
        self.assertAlmostEqual(cost, 90.0, places=2)

    def test_impossible_gap_raises(self):
        """If no station is reachable before the tank runs dry, it's infeasible."""
        with self.assertRaises(InfeasibleRoute):
            plan_fuel_stops(
                [_station(100, 3.0)], total_miles=1200, range_miles=RANGE, mpg=MPG
            )


class NearRouteFilterTests(TestCase):
    def test_keeps_near_station_drops_far_one(self):
        """Only stations within the buffer of the route survive the filter."""
        # Route: a straight north line along longitude -96, from lat 32 to 34.
        lats = np.linspace(32.0, 34.0, 50)
        coords = [(float(la), -96.0) for la in lats]
        lat_arr = np.array([c[0] for c in coords])
        lng_arr = np.array([c[1] for c in coords])
        seg = haversine_miles(lat_arr[:-1], lng_arr[:-1], lat_arr[1:], lng_arr[1:])
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        route = Route(coords=coords, cum_miles=cum, total_miles=float(cum[-1]))

        store = StationStore(pd.DataFrame({
            "name": ["ON_ROUTE", "FAR_AWAY"],
            "city": ["a", "b"], "state": ["TX", "TX"],
            "lat": [33.0, 33.0], "lng": [-96.02, -90.0],  # -96.02 ~1mi off; -90 far
            "price": [3.0, 3.0],
        }))

        found = [c["name"] for c in stations_near_route(store, route, buffer_miles=10.0)]
        self.assertIn("ON_ROUTE", found)
        self.assertNotIn("FAR_AWAY", found)


class EndpointValidationTests(TestCase):
    def test_missing_field_returns_400(self):
        """Missing `finish` is rejected before any external call (fast 400)."""
        response = APIClient().post(
            "/api/route/", {"start": "Dallas, TX"}, format="json"
        )
        self.assertEqual(response.status_code, 400)
