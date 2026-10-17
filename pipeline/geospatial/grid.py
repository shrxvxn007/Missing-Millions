"""Count-preserving metric grids and DBSCAN clustering.

Settlement boundaries are unions of analysis cells, never building footprints.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from typing import Any

import numpy as np
from pyproj import Transformer
from rasterio.transform import Affine
import shapely
from shapely.geometry import box, mapping, shape
from shapely.ops import unary_union
from sklearn.cluster import DBSCAN


def local_metric_crs(lon: float, lat: float) -> str:
    """Choose local UTM metres for an AOI smaller than a zone."""
    if not (-180 <= lon <= 180 and -80 <= lat <= 84):
        raise ValueError("Coordinates outside supported UTM range")
    zone = min(60, int((lon + 180) // 6) + 1)
    return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"


def project_geometry(geometry: Any, source: str, target: str):
    geom = shape(geometry) if isinstance(geometry, dict) else geometry
    transformer = Transformer.from_crs(source, target, always_xy=True)
    def transform_coordinates(coordinates):
        x, y = transformer.transform(coordinates[:, 0], coordinates[:, 1])
        return np.column_stack((x, y))
    return shapely.transform(geom, transform_coordinates)


@dataclass(frozen=True)
class AnalysisGrid:
    crs: str
    west: float
    north: float
    width: int
    height: int
    cell_size_m: float = 250.0

    @property
    def transform(self) -> Affine:
        return Affine(self.cell_size_m, 0, self.west, 0, -self.cell_size_m, self.north)

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height, self.width)

    def cell(self, row: int, col: int):
        left = self.west + col * self.cell_size_m
        top = self.north - row * self.cell_size_m
        return box(left, top - self.cell_size_m, left + self.cell_size_m, top)

    def center(self, row: int, col: int) -> tuple[float, float]:
        return (self.west + (col + 0.5) * self.cell_size_m,
                self.north - (row + 0.5) * self.cell_size_m)

    @classmethod
    def from_aoi(cls, aoi_geojson: dict, cell_size_m: float = 250.0):
        if not (25 <= cell_size_m <= 2000):
            raise ValueError("Analysis cell size must be 25–2000 metres")
        aoi = shape(aoi_geojson)
        crs = local_metric_crs(aoi.centroid.x, aoi.centroid.y)
        xmin, ymin, xmax, ymax = project_geometry(aoi, "EPSG:4326", crs).bounds
        west = math.floor(xmin / cell_size_m) * cell_size_m
        north = math.ceil(ymax / cell_size_m) * cell_size_m
        return cls(crs, west, north, math.ceil((xmax - west) / cell_size_m),
                   math.ceil((north - ymin) / cell_size_m), cell_size_m)


def cluster_count_grid(
    grid: AnalysisGrid,
    count_by_year: dict[int, np.ndarray],
    *,
    minimum_cell_count: float = 8,
    eps_m: float = 360,
    min_samples: int = 2,
    minimum_cluster_buildings: float = 30,
    sparse_minimum_buildings: float = 12,
    region_id: str = "region",
) -> tuple[list[dict], list[dict]]:
    """Cluster latest occupied-looking cells; sum same nonoverlapping cells each year.

    Missing observations remain null. This routine deliberately does not interpolate
    annual observations. IDs are reproducible hashes of grid cell membership.
    Below `minimum_cluster_buildings` but above `sparse_minimum_buildings`, a
    cluster is RETAINED as a low-strength signal for human review rather than
    discarded; sparse and dispersed settlements stay visible to investigators.
    """
    if not count_by_year:
        raise ValueError("At least one annual count grid is required")
    for values in count_by_year.values():
        if values.shape != grid.shape:
            raise ValueError("All annual grids must share the analysis grid")
    years = sorted(count_by_year)
    latest = count_by_year[years[-1]]
    positions = np.argwhere(np.isfinite(latest) & (latest >= minimum_cell_count))
    if len(positions) == 0:
        return [], []
    coordinates = np.array([grid.center(int(r), int(c)) for r, c in positions])
    labels = DBSCAN(eps=eps_m, min_samples=min_samples).fit_predict(coordinates)
    settlements, cells = [], []
    for label in sorted(set(labels) - {-1}):
        members = positions[labels == label]
        newest_total = float(sum(latest[r, c] for r, c in members))
        if newest_total < sparse_minimum_buildings:
            continue
        sparse_signal = newest_total < minimum_cluster_buildings
        cell_keys = ";".join(f"{r},{c}" for r, c in members)
        digest = hashlib.sha1(f"{grid.crs}:{grid.west}:{grid.north}:{cell_keys}".encode()).hexdigest()[:10]
        candidate_id = f"{region_id}-{digest}"
        geometry_m = unary_union([grid.cell(int(r), int(c)) for r, c in members])
        geometry_wgs = project_geometry(geometry_m, grid.crs, "EPSG:4326")
        centroid_wgs = project_geometry(geometry_m.centroid, grid.crs, "EPSG:4326")
        series = {}
        for year in years:
            values = np.array([count_by_year[year][r, c] for r, c in members])
            series[str(year)] = round(float(values.sum()), 2) if np.all(np.isfinite(values)) else None
        settlements.append({
            "id": candidate_id, "region_id": region_id,
            "geometry": mapping(geometry_wgs),
            "centroid": [round(centroid_wgs.x, 7), round(centroid_wgs.y, 7)],
            "area_km2": round(geometry_m.area / 1e6, 6),
            "building_count_by_year": series,
            "building_presence": {"meaning": "count-supported analysis cells", "cell_count": len(members)},
            "cell_indices": [[int(r), int(c)] for r, c in members],
            "building_density": newest_total / (geometry_m.area / 1e6),
            "building_signal_strength": "sparse_retained_for_review" if sparse_signal else "supported",
            "data_quality_flags": (["sparse_signal_retained_for_review"] if sparse_signal else []),
        })
        for r, c in members:
            counts = {str(y): round(float(count_by_year[y][r, c]), 2)
                      if np.isfinite(count_by_year[y][r, c]) else None for y in years}
            cells.append({"type": "Feature", "id": f"cell-{r}-{c}",
                          "geometry": mapping(project_geometry(grid.cell(int(r), int(c)), grid.crs, "EPSG:4326")),
                          "properties": {"cluster_id": candidate_id, "cell_size_m": grid.cell_size_m,
                                         "building_count_by_year": counts}})
    settlements.sort(key=lambda s: (s["centroid"][1], s["centroid"][0]))
    return settlements, cells


def allocate_population_nonoverlapping(
    cell_population: np.ndarray, settlements: list[dict]
) -> list[float | None]:
    """Assign each population grid cell once, in stable-ID order.

    Count grids are already on the common 250 m grid. For arbitrary overlapping
    input candidates, first stable ID owns a cell; this policy is deterministic
    and exposed by the function, rather than double-counting people.
    """
    totals: dict[str, float | None] = {}
    assigned: set[tuple[int, int]] = set()
    for settlement in sorted(settlements, key=lambda item: item["id"]):
        available = [tuple(rc) for rc in settlement["cell_indices"] if tuple(rc) not in assigned]
        assigned.update(available)
        values = [cell_population[r, c] for r, c in available]
        totals[settlement["id"]] = round(float(sum(values)), 1) if values and all(np.isfinite(values)) else None
    return [totals[s["id"]] for s in settlements]
