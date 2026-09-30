"""
Phase 2 — Load the station cache once and keep it in memory.

Why a singleton (loaded once):
    Reading data/stations.parquet and building numpy arrays costs a few
    milliseconds. We pay that cost ONE time and reuse the result for every
    incoming request, so the API stays fast. The station data never changes
    while the server runs, so caching it is safe.

The fuel-stop algorithm (Phase 4) does math over *all* stations at once, so we
expose the columns as parallel numpy arrays (lat, lng, price) in addition to the
pandas DataFrame — numpy makes that "all at once" math very fast.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
from django.conf import settings

# data/stations.parquet sits in the project's data/ folder (next to manage.py).
STATIONS_PATH = Path(settings.BASE_DIR) / "data" / "stations.parquet"


class StationStore:
    """All fuel stations, held in memory as a DataFrame + fast numpy arrays."""

    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df.reset_index(drop=True)
        # Parallel arrays: row i in each array is the same station.
        self.lat = self.df["lat"].to_numpy(dtype=float)
        self.lng = self.df["lng"].to_numpy(dtype=float)
        self.price = self.df["price"].to_numpy(dtype=float)
        self.name = self.df["name"].to_numpy(dtype=object)
        self.city = self.df["city"].to_numpy(dtype=object)
        self.state = self.df["state"].to_numpy(dtype=object)

    def __len__(self) -> int:
        return len(self.df)


@lru_cache(maxsize=1)
def get_station_store() -> StationStore:
    """
    Load stations.parquet once and cache the StationStore for the whole process.

    @lru_cache(maxsize=1) is the singleton trick: the first call runs the body
    and remembers the result; every later call returns that same object instantly
    without touching the disk again.
    """
    if not STATIONS_PATH.exists():
        raise FileNotFoundError(
            f"{STATIONS_PATH} not found. "
            f"Build it first with: python scripts/build_station_cache.py"
        )
    df = pd.read_parquet(STATIONS_PATH)
    return StationStore(df)
