"""
Phase 1 — Build the station coordinate cache (run OFFLINE, once).

Why this exists:
    The provided fuel-price file has ~8,000 stations with prices but NO coordinates,
    and only highway-exit addresses ("I-44, EXIT 283 & US-69") that geocoders can't
    resolve well. Geocoding them per request would be slow and cost thousands of API
    calls. Instead we resolve each station's location ONCE here, offline, by joining
    on (city, state) to a free local US-cities dataset, and save the result. At
    request time the API just loads this cache -> zero geocoding calls, fast responses.

Output:
    data/stations.parquet  -> columns: name, city, state, lat, lng, price

Run:
    python scripts/build_station_cache.py
"""
from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pandas as pd
import requests

# --- paths -------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
FUEL_MD = DATA / "fuel-prices.md"
OUT = DATA / "stations.parquet"
CITIES_CACHE = DATA / "us_cities.csv"

# Free, directly-downloadable US-cities dataset (~30k cities, incl. small towns).
# Columns: ID, STATE_CODE, STATE_NAME, CITY, COUNTY, LATITUDE, LONGITUDE
US_CITIES_URL = (
    "https://raw.githubusercontent.com/kelvins/US-Cities-Database/main/csv/us_cities.csv"
)

# US Postal state codes. Anything outside this set (e.g. AB, ON, BC) is non-USA
# and is dropped, because the assessment routes are USA-only.
US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL",
    "IN", "IA", "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC",
}


def parse_fuel_markdown(path: Path) -> pd.DataFrame:
    """Parse the pipe-delimited markdown table into a clean DataFrame."""
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 7:
            continue
        # skip header row and the |---|---| separator row
        if cells[0] in ("OPIS Truckstop ID", "") or set(cells[0]) <= {"-"}:
            continue
        rows.append(cells)

    df = pd.DataFrame(
        rows,
        columns=["opis_id", "name", "address", "city", "state", "rack_id", "price"],
    )
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    df = df.dropna(subset=["price"])
    df["state"] = df["state"].str.upper().str.strip()
    df["city_key"] = df["city"].map(_norm_city)
    return df


def _norm_city(name: str) -> str:
    """Normalize a city name for joining: lowercase, strip punctuation/whitespace."""
    name = name.lower().strip()
    name = re.sub(r"[.\-']", " ", name)
    name = re.sub(r"\s+", " ", name)
    return name


def load_us_cities() -> pd.DataFrame:
    """Load the US-cities lat/lng dataset (download + cache locally on first run)."""
    if CITIES_CACHE.exists():
        raw = pd.read_csv(CITIES_CACHE)
    else:
        print(f"Downloading US-cities dataset -> {CITIES_CACHE.name} ...")
        resp = requests.get(US_CITIES_URL, timeout=60)
        resp.raise_for_status()
        CITIES_CACHE.write_bytes(resp.content)
        raw = pd.read_csv(io.BytesIO(resp.content))

    raw.columns = [c.upper() for c in raw.columns]
    cities = raw.rename(
        columns={
            "STATE_CODE": "state",
            "CITY": "city",
            "LATITUDE": "lat",
            "LONGITUDE": "lng",
        }
    )[["state", "city", "lat", "lng"]].copy()
    cities["state"] = cities["state"].str.upper().str.strip()
    cities["city_key"] = cities["city"].map(_norm_city)
    # A city name can repeat within a state; keep the first (largest by dataset order).
    cities = cities.drop_duplicates(subset=["state", "city_key"], keep="first")
    return cities[["state", "city_key", "lat", "lng"]]


def build() -> None:
    if not FUEL_MD.exists():
        sys.exit(f"ERROR: {FUEL_MD} not found. Put the fuel-prices file there first.")

    stations = parse_fuel_markdown(FUEL_MD)
    print(f"Parsed rows:            {len(stations)}")

    stations = stations[stations["state"].isin(US_STATES)].copy()
    print(f"After USA-only filter:  {len(stations)}")

    # Deduplicate: same physical stop appears multiple times (e.g. 'PILOT #1243'
    # and 'PILOT TRAVEL CENTER #1243'). Collapse to one row per (city, state,
    # address), keeping the lowest price seen there.
    stations = (
        stations.sort_values("price")
        .drop_duplicates(subset=["state", "city_key", "address"], keep="first")
        .reset_index(drop=True)
    )
    print(f"After dedupe:           {len(stations)}")

    cities = load_us_cities()
    merged = stations.merge(cities, on=["state", "city_key"], how="left")

    matched = merged["lat"].notna()
    print(f"Coordinate match:       {matched.sum()} / {len(merged)} "
          f"({matched.mean() * 100:.1f}%)")

    unmatched = merged[~matched][["name", "city", "state"]].drop_duplicates()
    if len(unmatched):
        print(f"Unmatched cities:       {len(unmatched)} (dropped) — sample:")
        print(unmatched.head(8).to_string(index=False))

    out = (
        merged[matched][["name", "city", "state", "lat", "lng", "price"]]
        .reset_index(drop=True)
    )
    out.to_parquet(OUT, index=False)
    print(f"\nWrote {len(out)} stations -> {OUT}")


if __name__ == "__main__":
    build()
