"""
Phase 5 — Orchestration: tie every service together into one response.

This is the single function the API view calls. It runs the whole flow and
returns a plain dict (ready to be sent as JSON):

    geocode start + finish  (2 calls)
        -> OSRM route        (1 call)      == 3 external calls total
        -> filter stations near the route  (0 calls, local)
        -> plan the cheapest fuel stops    (0 calls, local)
        -> build a GeoJSON map + summary

GeoJSON note: coordinates in GeoJSON are ordered [longitude, latitude] (x, y),
which is the opposite of how we usually say "lat, lng" — so we swap when building it.
"""
from __future__ import annotations

from django.conf import settings

from .fuel import plan_fuel_stops, stations_near_route
from .geocoding import geocode
from .routing_osrm import get_route
from .stations import get_station_store


def _point_feature(lat: float, lng: float, props: dict) -> dict:
    """A GeoJSON point (marker) at lat/lng with some properties."""
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [lng, lat]},  # [x, y] = [lng, lat]
        "properties": props,
    }


def _build_geojson(start, finish, route, stops, start_name, finish_name) -> dict:
    """Build a GeoJSON FeatureCollection: the route line + start/finish/fuel markers."""
    # The route can be 9,000+ points. Downsample to keep the response small and fast
    # while still drawing a smooth line on a map.
    coords = route.coords
    step = max(1, len(coords) // 800)
    line = [[lng, lat] for (lat, lng) in coords[::step]]
    last = [coords[-1][1], coords[-1][0]]
    if line[-1] != last:
        line.append(last)  # always include the true endpoint

    features = [
        {
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": line},
            "properties": {"type": "route"},
        },
        _point_feature(start[0], start[1], {"type": "start", "label": start_name}),
        _point_feature(finish[0], finish[1], {"type": "finish", "label": finish_name}),
    ]
    for order, s in enumerate(stops, start=1):
        features.append(
            _point_feature(
                s.lat, s.lng,
                {
                    "type": "fuel_stop",
                    "order": order,
                    "name": s.name,
                    "city": s.city,
                    "state": s.state,
                    "price_per_gallon": round(s.price, 3),
                    "gallons": round(s.gallons, 2),
                    "cost": round(s.cost, 2),
                    "mile_from_start": round(s.distance_from_start_miles),
                },
            )
        )
    return {"type": "FeatureCollection", "features": features}


def build_route_plan(start_name: str, finish_name: str) -> dict:
    """Run the full pipeline and return the response dict."""
    start = geocode(start_name)     # (lat, lng)  — external call 1
    finish = geocode(finish_name)   # (lat, lng)  — external call 2
    route = get_route(start, finish)  #            — external call 3

    store = get_station_store()
    candidates = stations_near_route(store, route, settings.ROUTE_BUFFER_MILES)
    stops, total_cost = plan_fuel_stops(
        candidates,
        route.total_miles,
        settings.VEHICLE_RANGE_MILES,
        settings.VEHICLE_MPG,
    )

    return {
        "start": {"query": start_name, "lat": start[0], "lng": start[1]},
        "finish": {"query": finish_name, "lat": finish[0], "lng": finish[1]},
        "total_distance_miles": round(route.total_miles, 1),
        "vehicle": {
            "range_miles": settings.VEHICLE_RANGE_MILES,
            "mpg": settings.VEHICLE_MPG,
        },
        "fuel_stops": [
            {
                "order": i,
                "name": s.name,
                "city": s.city,
                "state": s.state,
                "lat": s.lat,
                "lng": s.lng,
                "mile_from_start": round(s.distance_from_start_miles),
                "price_per_gallon": round(s.price, 3),
                "gallons": round(s.gallons, 2),
                "cost": round(s.cost, 2),
            }
            for i, s in enumerate(stops, start=1)
        ],
        "total_fuel_cost": round(total_cost, 2),
        "route_geojson": _build_geojson(start, finish, route, stops, start_name, finish_name),
    }
