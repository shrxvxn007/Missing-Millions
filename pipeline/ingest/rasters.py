"""Local source-raster adapters with explicit count semantics.

Google fractional pixels refer to the native 0.5 m (0.25 m²) raster support.
For mean-resampled fractional values the conversion is pixel_area / 0.25;
at native resolution that is simply a sum, NOT a count of nonzero pixels.
WorldPop persons-per-pixel count rasters are summed without that conversion.
Do not use this adapter for population-density rasters.
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
import rasterio
from pyproj import CRS
from rasterio.mask import mask
from rasterio.warp import reproject, Resampling

from pipeline.geospatial.grid import AnalysisGrid, project_geometry


def fractional_values_to_counts(values: np.ndarray, pixel_area_m2: float, *,
                                native_pixel_area_m2: float = 0.25) -> np.ndarray:
    """Convert native or mean-resampled fractional support to extensive counts."""
    if pixel_area_m2 <= 0 or native_pixel_area_m2 <= 0:
        raise ValueError("Pixel areas must be positive")
    return np.asarray(values, dtype=np.float64) * (pixel_area_m2 / native_pixel_area_m2)


def aggregate_count_raster(
    path: str | Path,
    aoi_wgs84: dict,
    grid: AnalysisGrid,
    *,
    kind: Literal["google_fractional", "population_count", "building_count"] = "population_count",
    band: int = 1,
    fractional_resampling: Literal["native_or_mean", "sum"] = "native_or_mean",
) -> np.ndarray:
    """Clip source pixel centres to AOI and conservatively sum into metric cells.

    Resampling.sum preserves extensive totals. Never bilinear-average a count
    raster. Boundary pixels use the documented centre-in-polygon approximation;
    use a sufficiently fine source grid or quantify boundary uncertainty.
    Native Google downloads are projected in metre UTM coordinates. Coarsened
    files must document whether values were mean- or sum-resampled. A sum export
    is already extensive and must pass fractional_resampling='sum'.
    """
    with rasterio.open(path) as source:
        if not source.crs:
            raise ValueError("Source raster needs a CRS")
        clipped_geometry = project_geometry(aoi_wgs84, "EPSG:4326", source.crs.to_string())
        raw, clipped_transform = mask(source, [clipped_geometry], indexes=band,
                                      crop=True, filled=False)
        values = raw.astype("float64").filled(np.nan)
        values[values < 0] = np.nan
        if kind == "google_fractional" and fractional_resampling == "native_or_mean":
            if not source.crs.is_projected or not CRS(source.crs).axis_info[0].unit_name.lower().startswith("met"):
                raise ValueError("Google fractional raster conversion requires projected metres")
            pixel_area = abs(clipped_transform.a * clipped_transform.e - clipped_transform.b * clipped_transform.d)
            values = fractional_values_to_counts(values, pixel_area)
        destination = np.full(grid.shape, np.nan, dtype="float64")
        reproject(values, destination, src_transform=clipped_transform,
                  src_crs=source.crs, src_nodata=np.nan, dst_transform=grid.transform,
                  dst_crs=grid.crs, dst_nodata=np.nan, resampling=Resampling.sum,
                  init_dest_nodata=True)
        # Coordinate round trips can leave ~1e-13-pixel slivers at a clipped
        # boundary. Distinguish those from genuine observed zero-valued cells.
        coverage = np.zeros(grid.shape, dtype="float64")
        reproject(np.isfinite(values).astype("float64"), coverage,
                  src_transform=clipped_transform, src_crs=source.crs,
                  dst_transform=grid.transform, dst_crs=grid.crs,
                  src_nodata=0, dst_nodata=0, resampling=Resampling.sum)
        destination[coverage <= 1e-8] = np.nan
        return destination


def aggregate_worldpop(path: str | Path, aoi_wgs84: dict, grid: AnalysisGrid, *, band: int = 1):
    """WorldPop persons per pixel → nonoverlapping analysis-grid person counts."""
    return aggregate_count_raster(path, aoi_wgs84, grid, kind="population_count", band=band)
