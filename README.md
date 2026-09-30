# Fuel Route API

A Django REST API that, given a **start** and **finish** in the USA, returns:

- the **driving route** as GeoJSON (ready to render on any map),
- the **cost-optimal fuel stops** along the way (500-mile tank, 10 mpg), and
- the **total fuel cost** for the trip,

using the provided fuel-price dataset and only free, no-key external services.

---

## Design in one paragraph

The provided price file has ~8,000 stations with **prices but no coordinates**, and
only highway-exit addresses that geocoders resolve poorly. Geocoding them per request
would mean thousands of slow API calls. Instead, station coordinates are **precomputed
once, offline** by joining each station's `(city, state)` to a free US-cities dataset,
and saved to `data/stations.parquet`. At request time the API loads that cache and makes
just **three external calls** (2 geocodes + 1 route), then does all fuel-stop math locally.

**External calls per request: 2 geocode (start + finish) + 1 routing = 3.**
Station coordinates cost **zero** calls.

---

## Tech stack

| Concern | Choice |
|---|---|
| Framework | Django 5.2 + Django REST Framework |
| Geocoding (start/finish) | Nominatim (OpenStreetMap) — free, no key |
| Routing | OSRM demo server — free, no key; geometry + distance in one call |
| Station coordinates | Local US-cities CSV joined on `(city, state)` — zero API calls |
| In-memory data | pandas / numpy, loaded once at startup |
| Map output | GeoJSON FeatureCollection (route line + start/finish/fuel markers) |

---

## Setup

Requires **Python 3.10+** (Django 5.x).

```bash
# 1. Virtual environment + dependencies
python3.12 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Config
cp .env.example .env                 # sensible defaults; no keys required

# 3. Build the station cache (offline, one time)
python scripts/build_station_cache.py    # -> data/stations.parquet

# 4. Run
python manage.py migrate             # creates Django's default tables (unused by the API)
python manage.py runserver           # http://127.0.0.1:8000/
```

---

## Usage

### `POST /api/route/`

Request:

```json
{ "start": "Dallas, TX", "finish": "Chicago, IL" }
```

Response (abridged):

```json
{
  "start":  { "query": "Dallas, TX",  "lat": 32.776, "lng": -96.797 },
  "finish": { "query": "Chicago, IL", "lat": 41.876, "lng": -87.624 },
  "total_distance_miles": 966.7,
  "vehicle": { "range_miles": 500.0, "mpg": 10.0 },
  "fuel_stops": [
    {
      "order": 1, "name": "…", "city": "Caddo Mills", "state": "TX",
      "lat": 33.07, "lng": -96.24, "mile_from_start": 42,
      "price_per_gallon": 2.801, "gallons": 4.16, "cost": 11.64
    }
  ],
  "total_fuel_cost": 134.72,
  "route_geojson": { "type": "FeatureCollection", "features": [ … ] }
}
```

Example (browser): open `http://127.0.0.1:8000/api/route/`, paste the JSON body into the
DRF form, and POST. Or with curl:

```bash
curl -s -X POST http://127.0.0.1:8000/api/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Dallas, TX", "finish": "Chicago, IL"}'
```

### Error responses

| Status | Meaning |
|---|---|
| `400` | Missing/blank field, or a location that can't be geocoded |
| `422` | Route found, but no station is reachable within range (can't be fueled) |
| `502` | The upstream routing service (OSRM) failed |

---

## Fuel-stop algorithm

1. **Near-route filter** — of 6,249 cached stations, keep those within `ROUTE_BUFFER_MILES`
   (default 10) of the route, measured with vectorized haversine over a downsampled route.
   Each kept station is projected to its **position** (miles from start).
2. **Greedy refueling** — walking along the route: if a cheaper station is reachable on a
   full tank, buy just enough to reach it; otherwise fill up and drive to the cheapest
   reachable station. Cost accrues at the price of the station where fuel is purchased.

**Assumption:** the vehicle departs with a **full tank**. The origin is not a priced
station, so the first tank isn't charged; the API charges only for fuel purchased at
stations along the route. Trips within one tank (≤ 500 mi) therefore require no stop.

---

## Performance

- **1 routing call + 2 geocode calls** per request (geocode results are cached).
- Station coordinates are precomputed offline → **0** calls, and loaded once into memory
  at startup (`routing/apps.py` warms the cache), so requests are served in milliseconds
  after the two external lookups return.
- The route geometry is downsampled before serialization to keep responses small.

---

## Tests

```bash
python manage.py test
```

Covers the fuel algorithm (no-stop, cheapest-choice, infeasible), the near-route filter,
and endpoint validation — all offline (no network).

---

## Project layout

```
config/                 Django project (settings, urls)
routing/
  services/
    stations.py         load stations.parquet once (singleton)
    geocoding.py        Nominatim geocoding (cached)
    routing_osrm.py     one OSRM call -> geometry + distance
    geo.py              haversine distance (vectorized)
    fuel.py             near-route filter + greedy fuel-stop planner
    pipeline.py         orchestration + GeoJSON assembly
  serializers.py        request validation
  views.py              POST /api/route/
  tests.py
scripts/
  build_station_cache.py   offline: price file -> data/stations.parquet
data/
  fuel-prices.md        provided price dataset
  stations.parquet      generated cache (git-ignored)
```
