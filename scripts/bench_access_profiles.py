"""Measure access-profile latency after in-package precomputation.

Copy each processed package to a scratch directory, load it the way the API
does, serve the first candidate's profile, and report latency + engine state.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import time

from services.api.data import DataRepository

ROOT = Path(__file__).resolve().parents[1]


def main():
    scratch = Path(tempfile.mkdtemp(prefix="mm-profile-bench-"))
    for name in ("turkana", "mbale", "demo"):
        shutil.copy(ROOT / f"data/processed/{name}.json", scratch / f"{name}.json")
        repository = DataRepository(scratch / f"{name}.json")
        package = repository.load()
        first = package["settlements"][0]
        start = time.perf_counter()
        profile = repository.access_profile(first)
        elapsed_ms = (time.perf_counter() - start) * 1000
        engine_built = repository.engine is not None
        print(f"{name}: first access-profile call {elapsed_ms:.1f} ms | "
              f"engine built: {engine_built} | measured cells {profile.get('cells_measured')} | "
              f"median {profile.get('median_minutes')} | p90 {profile.get('p90_minutes')}")
        (scratch / f"{name}.json").unlink()


if __name__ == "__main__":
    main()
