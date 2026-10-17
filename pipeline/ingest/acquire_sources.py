"""Acquire a small, real, provenance-preserving source pack. No synthetic fallback.

Uses the anonymous GCS route published in Google Research's official notebook.
Run with --check for a local inventory; --sources explicitly enables downloads.
All Open Buildings counts are sums of native 0.5 m fractional-count values.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "data" / "raw" / "turkana-real"
GOOGLE_DOC = "https://developers.google.com/earth-engine/datasets/catalog/GOOGLE_Research_open-buildings-temporal_v1"
GOOGLE_NOTEBOOK = "https://github.com/google-research/google-research/blob/master/building_detection/open_buildings_temporal_download_region_geotiffs.ipynb"
# WorldPop Global 2 constrained 2023 100 m items per ISO3 code (verified via STAC).
WORLDPOP_ITEMS = {
    "UGA": "https://api.stac.worldpop.org/collections/UGA/items/uga_pop_2023_CN_100m_R2025A_v1",
    "KEN": "https://api.stac.worldpop.org/collections/KEN/items/ken_pop_2023_CN_100m_R2025A_v1",
}
DEFAULT_COUNTRY = "KEN"
OVERPASS = "https://overpass.private.coffee/api/interpreter"


def resolve_worldpop_item(args: argparse.Namespace) -> str:
    """Country-specific WorldPop item; per-source URLs stay explicit and audited."""
    country = getattr(args, "country", DEFAULT_COUNTRY)
    item = WORLDPOP_ITEMS.get(country)
    if item is None:
        raise ValueError(f"No verified WorldPop 2023 STAC item configured for country {country!r}; add it to WORLDPOP_ITEMS after checking https://hub.worldpop.org/")
    return item


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    compact = path.name in {"osm.json", "roads.geojson", "facilities.geojson", "graph.json"} or path.name.startswith("open-buildings-manifest-")
    options = {"separators": (",", ":")} if compact else {"indent": 2}
    path.write_text(json.dumps(value, allow_nan=False, **options) + "\n")


def request_json(url: str, data: bytes | None = None, timeout: int = 90) -> dict:
    headers = {"User-Agent": "MissingMillionsHackathon/0.1 (offline research source preparation)"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


@contextmanager
def open_population_raster(url: str):
    """Prefer ranged reads; bound and discard a country file if HTTP ranges fail."""
    import rasterio
    with ExitStack() as stack:
        try:
            source = stack.enter_context(rasterio.open(url))
        except rasterio.errors.RasterioIOError as exc:
            if "Range downloading not supported" not in str(exc):
                raise
            folder = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="missing-millions-worldpop-")))
            temporary = folder / "country.tif"
            limit = 80 * 1024 * 1024
            req = urllib.request.Request(url, headers={"User-Agent": "MissingMillionsHackathon/0.1"})
            with urllib.request.urlopen(req, timeout=120) as response, temporary.open("wb") as output:
                if int(response.headers.get("Content-Length", "0")) > limit:
                    raise ValueError("WorldPop server lacks ranges and country raster exceeds the 80 MB safety limit")
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > limit:
                        raise ValueError("WorldPop country raster exceeded the 80 MB bounded-download limit")
                    output.write(chunk)
            print(f"WorldPop server lacks HTTP ranges: downloaded temporary {total / 1024 / 1024:.1f} MB country file; retaining only AOI clip", flush=True)
            source = stack.enter_context(rasterio.open(temporary))
        yield source


def make_grid(args: argparse.Namespace) -> dict:
    from pyproj import Transformer
    transform = Transformer.from_crs(4326, args.crs, always_xy=True)
    x, y = transform.transform(args.center[0], args.center[1])
    west = math.floor((x - args.size_m / 2) / args.cell_m) * args.cell_m
    north = math.ceil((y + args.size_m / 2) / args.cell_m) * args.cell_m
    size = math.ceil(args.size_m / args.cell_m)
    inverse = Transformer.from_crs(args.crs, 4326, always_xy=True)
    a = inverse.transform(west, north - size * args.cell_m)
    b = inverse.transform(west + size * args.cell_m, north)
    return {"crs": args.crs, "west": west, "north": north, "width": size,
            "height": size, "cell_size_m": args.cell_m,
            "bbox": [a[0], a[1], b[0], b[1]], "center": args.center,
            "region_id": getattr(args, "region_id", None) or "turkana-real",
            "region_name": getattr(args, "region_name", None) or "Turkana source sample",
            "country": {"ken": "Kenya", "uga": "Uganda"}.get(
                str(getattr(args, "country", DEFAULT_COUNTRY)).lower(),
                getattr(args, "country", None) or "Kenya"),
            "years": [2016, 2023]}


def intersecting_tiles(manifest: dict, grid: dict) -> list[dict]:
    from pyproj import CRS
    west, north = grid["west"], grid["north"]
    east = west + grid["width"] * grid["cell_size_m"]
    south = north - grid["height"] * grid["cell_size_m"]
    result = []
    for tileset in manifest["tilesets"]:
        if CRS.from_user_input(tileset["crs"]) != CRS.from_user_input(grid["crs"]):
            continue
        for source in tileset["sources"]:
            affine, dims = source["affineTransform"], source["dimensions"]
            if affine["scaleX"] != .5 or affine["scaleY"] != -.5:
                raise ValueError("Refusing undocumented Open Buildings pixel-count scaling: expected native 0.5 m")
            left, top = affine["translateX"], affine["translateY"]
            right, bottom = left + .5 * dims["width"], top - .5 * dims["height"]
            if left < east and right > west and top > south and bottom < north:
                uri = manifest["uriPrefix"] + source["uris"][0]
                result.append({"url": uri.replace("gs://", "https://storage.googleapis.com/", 1),
                               "affine": affine, "dimensions": dims})
    return result


def deduplicate_facilities(features: list[dict], projected_crs: str = "EPSG:32636", maximum_m: float = 100) -> list[dict]:
    """Reconcile same-named nearby node/way records, retaining every OSM ID.

    Anonymous nearby facilities are not assumed identical. Distinct same-name
    campuses over the configured distance stay separate for human review.
    """
    from pyproj import CRS, Transformer
    metric = CRS.from_user_input(projected_crs)
    if not metric.is_projected or any(abs(axis.unit_conversion_factor - 1) > 1e-8 for axis in metric.axis_info[:2]):
        raise ValueError("Facility duplicate reconciliation requires a projected CRS in metres")
    project = Transformer.from_crs(4326, projected_crs, always_xy=True)
    result, positions = [], []
    for feature in sorted(features, key=lambda item: str(item.get("id", ""))):
        properties = feature["properties"]
        name = " ".join("".join(c if c.isalnum() else " " for c in properties.get("name", "").casefold()).split())
        if name == "unnamed mapped facility":
            name = ""
        x, y = project.transform(*feature["geometry"]["coordinates"])
        match = next((index for index, (previous_name, px, py) in enumerate(positions)
                      if name and previous_name == name and math.hypot(x - px, y - py) <= maximum_m), None)
        if match is None:
            copy = json.loads(json.dumps(feature))
            identity = properties.get("osm_id") or feature.get("id") or properties.get("source_id")
            copy["properties"]["merged_source_ids"] = list(properties.get("merged_source_ids", [identity]))
            result.append(copy)
            positions.append((name, x, y))
        else:
            identity = properties.get("osm_id") or feature.get("id") or properties.get("source_id")
            for source_id in properties.get("merged_source_ids", [identity]):
                if source_id not in result[match]["properties"]["merged_source_ids"]:
                    result[match]["properties"]["merged_source_ids"].append(source_id)
            if properties.get("source_records"):
                records = result[match]["properties"].setdefault("source_records", [])
                for record in properties["source_records"]:
                    if record not in records:
                        records.append(record)
    return result


def manifest_tokens_with_coverage(grid: dict, year: int) -> list[str]:
    """Probe official level-2 S2 manifest tokens and return those overlapping the AOI.

    Tokens are unsigned identifiers of the official manifest series; a 404 means
    that token has no published tileset for the CRS/year and is skipped.
    """
    from pyproj import CRS
    epsg = CRS.from_user_input(grid["crs"]).to_epsg()
    if epsg is None:
        raise ValueError("Select an EPSG-coded metric CRS matching the official manifest")
    west, north = grid["west"], grid["north"]
    east = west + grid["width"] * grid["cell_size_m"]
    south = north - grid["height"] * grid["cell_size_m"]
    covered = []
    for token in range(1, 23):
        url = f"https://storage.googleapis.com/open-buildings-temporal-data/v1/manifests/{token}_EPSG_{epsg}_{year}_06_30.json"
        try:
            manifest = request_json(url, timeout=45)
        except Exception:
            continue
        for tileset in manifest["tilesets"]:
            for source in tileset["sources"]:
                affine, dims = source["affineTransform"], source["dimensions"]
                left, top = affine["translateX"], affine["translateY"]
                right, bottom = left + .5 * dims["width"], top - .5 * dims["height"]
                if left < east and right > west and top > south and bottom < north:
                    covered.append(str(token))
                    break
            else:
                continue
            break
    return sorted(set(covered), key=int)


def acquire_buildings(args: argparse.Namespace, grid: dict) -> dict:
    """Read only intersecting native COG windows; never average building counts."""
    import numpy as np
    import rasterio
    from rasterio.windows import Window
    from contextlib import ExitStack
    from pyproj import CRS
    arrays, records = {}, []
    epsg = CRS.from_user_input(grid["crs"]).to_epsg()
    if epsg is None:
        raise ValueError("Select an EPSG-coded metric CRS matching the official manifest")
    for year in [2016, 2023]:
        url = f"https://storage.googleapis.com/open-buildings-temporal-data/v1/manifests/{args.manifest_token}_EPSG_{epsg}_{year}_06_30.json"
        manifest = request_json(url)
        bands = {band["id"]: (band["tilesetId"], band.get("tilesetBandIndex", 0)) for band in manifest["bands"]}
        if bands.get("building_fractional_count") != ("a0", 0) or bands.get("building_presence") != ("a0", 2):
            raise ValueError("Official manifest band layout changed; verify fractional-count and presence indices before reading")
        write_json(args.out / f"open-buildings-manifest-{year}.json", manifest)
        tiles = intersecting_tiles(manifest, grid)
        if not tiles:
            raise ValueError(f"No native Google tiles overlap the grid for {year}; select a matching --manifest-token/CRS")
        counts = np.full((grid["height"], grid["width"]), np.nan)
        presence = np.full_like(counts, np.nan)
        coverage = np.zeros_like(counts)
        native_size = round(grid["cell_size_m"] / .5)
        if native_size * .5 != grid["cell_size_m"]:
            raise ValueError("Analysis cell size must be a multiple of native pixel size")
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif", GDAL_HTTP_TIMEOUT="60"), ExitStack() as stack:
            sources = [stack.enter_context(rasterio.open(t["url"])) for t in tiles]
            for row in range(grid["height"]):
                for col in range(grid["width"]):
                    left = grid["west"] + col * grid["cell_size_m"]
                    top = grid["north"] - row * grid["cell_size_m"]
                    values = np.zeros((native_size, native_size), dtype="float64")
                    signal = np.zeros_like(values)
                    assigned = np.zeros(values.shape, dtype=bool)
                    for src in sources:
                        if abs(src.res[0] - .5) > 1e-8 or abs(src.res[1] - .5) > 1e-8:
                            raise ValueError("Count preservation requires native 0.5 m windows, not COG overviews")
                        source_col = round((left - src.transform.c) / .5)
                        source_row = round((src.transform.f - top) / .5)
                        c0, r0 = max(0, source_col), max(0, source_row)
                        c1, r1 = min(src.width, source_col + native_size), min(src.height, source_row + native_size)
                        if c1 <= c0 or r1 <= r0:
                            continue
                        window = Window(c0, r0, c1 - c0, r1 - r0)
                        block = src.read([1, 3], window=window, masked=True)
                        rr = slice(r0 - source_row, r1 - source_row)
                        cc = slice(c0 - source_col, c1 - source_col)
                        valid = (~np.ma.getmaskarray(block[0])) & (block[0].data >= 0) & (~assigned[rr, cc])
                        values[rr, cc][valid] = block[0].data[valid]
                        signal[rr, cc][valid] = np.maximum(0, block[1].data[valid])
                        assigned[rr, cc][valid] = True
                    coverage[row, col] = assigned.mean()
                    if assigned.all():
                        counts[row, col] = values.sum(dtype="float64")
                        presence[row, col] = signal.mean()
                print(f"Open Buildings {year}: row {row + 1}/{grid['height']}", flush=True)
        arrays[f"counts_{year}"] = counts
        arrays[f"presence_{year}"] = presence
        arrays[f"coverage_{year}"] = coverage
        records.append({"year": year, "manifest_url": url, "tiles": tiles,
                        "manifest_band_indices_zero_based": {key: value[1] for key, value in bands.items()},
                        "finite_cells": int(np.isfinite(counts).sum()),
                        "building_count_sum": float(np.nansum(counts))})
    np.savez_compressed(args.out / "buildings.npz", **arrays)
    return {"status": "acquired", "producer": "Google Research", "name": "Open Buildings 2.5D Temporal v1",
            "source_url": GOOGLE_DOC, "acquisition_reference": GOOGLE_NOTEBOOK,
            "vintage": [2016, 2023], "retrieved_at": timestamp(), "kind": "modelled",
            "license": "CC-BY-4.0 (chosen from producer's dual license offer)",
            "native_resolution_m": .5, "effective_resolution_m": 4,
            "processing": "Native band1 building_fractional_count summed once per non-overlapping 250 m cell; native band3 presence averaged; no overviews, thresholded pixel counts or fabricated outlines.",
            "records": records, "files": ["buildings.npz"],
            "limitations": ["Annual model estimates are not observations of occupancy.", "Temporal misalignment and classification variation can mimic construction.", "Cells with incomplete source coverage remain NaN."]}


def acquire_population(args: argparse.Namespace, grid: dict) -> dict:
    import numpy as np
    import rasterio
    from rasterio.windows import from_bounds
    from pyproj import Transformer
    item_url = resolve_worldpop_item(args)
    item = request_json(item_url)
    write_json(args.out / "worldpop-item.json", item)
    url = item["assets"]["data"]["href"]
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif", GDAL_HTTP_TIMEOUT="60"):
        with open_population_raster(url) as src:
            window = from_bounds(*grid["bbox"], src.transform).round_offsets().round_lengths()
            values = src.read(1, window=window, masked=True)
            clip_transform = src.window_transform(window)
            profile = src.profile.copy()
            profile.update(width=values.shape[1], height=values.shape[0], transform=src.window_transform(window), compress="deflate")
            # Preserve native count pixels, their geographic transform and source NoData.
            with rasterio.open(args.out / "worldpop2023.tif", "w", **profile) as dst:
                dst.write(values.filled(src.nodata), 1)
                dst.update_tags(**src.tags())
                dst.update_tags(source_url=url, quantity="people_per_native_pixel", reference_year="2023")
            # Each native count pixel belongs to exactly one metric analysis cell.
            # Pixel-centroid assignment preserves the selected native pixel total,
            # avoids averaging counts, and never counts a pixel in two cells.
            rr, cc = np.indices(values.shape)
            xx, yy = rasterio.transform.xy(clip_transform, rr, cc, offset="center")
            tx, ty = Transformer.from_crs(src.crs, grid["crs"], always_xy=True).transform(np.asarray(xx), np.asarray(yy))
            target_cols = np.floor((np.asarray(tx) - grid["west"]) / grid["cell_size_m"]).astype(int)
            target_rows = np.floor((grid["north"] - np.asarray(ty)) / grid["cell_size_m"]).astype(int)
            data = np.asarray(values.data).reshape(target_rows.shape)
            valid = (~np.ma.getmaskarray(values)).reshape(target_rows.shape) & (data >= 0)
            valid &= (target_rows >= 0) & (target_rows < grid["height"]) & (target_cols >= 0) & (target_cols < grid["width"])
            population = np.zeros((grid["height"], grid["width"]), dtype="float64")
            assigned_pixels = np.zeros_like(population, dtype=int)
            np.add.at(population, (target_rows[valid], target_cols[valid]), data[valid])
            np.add.at(assigned_pixels, (target_rows[valid], target_cols[valid]), 1)
            population[assigned_pixels == 0] = np.nan
            np.savez_compressed(args.out / "population.npz", population=population)
    country = getattr(args, "country", DEFAULT_COUNTRY)
    return {"status": "acquired", "producer": "WorldPop, University of Southampton", "name": f"WorldPop Global2 {country} R2025A v1 constrained",
            "source_url": item_url, "raster_url": url, "vintage": 2023,
            "release": "R2025A v1", "retrieved_at": timestamp(), "license": "CC-BY-4.0",
            "resolution": "3 arc seconds, approximately 100 m at equator", "kind": "modelled",
            "units": "people_per_pixel", "native_clip_sum": float(values.sum(dtype="float64")),
            "selected_native_pixel_sum": float(data[valid].sum(dtype="float64")),
            "aggregated_grid_sum": float(np.nansum(population)),
            "processing": "Native raster window clip. Each valid native count pixel assigned by projected centroid to exactly one analysis cell; no averaging or density-to-count conversion.",
            "files": ["worldpop2023.tif", "worldpop-item.json", "population.npz"],
            "limitations": ["Modelled spatial redistribution; not a resident census at settlement scale.", "Reference year 2023 is distinct from 2025 release date."]}


def extract_settlement_registry(osm_raw: dict) -> dict:
    """Point registry of mapped settlements (OSM place=* records).

    This is the mapper-community reference layer used for candidate matching.
    It is a volunteer-maintained record, not an authoritative or complete
    settlement census; absence here is never proof a settlement is unknown.
    Ways and relations use their geometry centroid with the original ID kept.
    """
    import json as _json
    PLACE_RANK = {"city": 1, "town": 2, "suburb": 3, "village": 4,
                  "neighbourhood": 5, "hamlet": 6, "isolated_dwelling": 7, "farm": 8}
    features = []
    for item in osm_raw.get("elements", []):
        tags = item.get("tags", {})
        place = tags.get("place")
        if place not in PLACE_RANK:
            continue
        if item["type"] == "node" and item.get("lon") is not None:
            center = [item["lon"], item["lat"]]
        else:
            coords = [(p["lon"], p["lat"]) for p in item.get("geometry", []) if p.get("lon") is not None]
            if not coords:
                continue
            center = [sum(p[0] for p in coords) / len(coords), sum(p[1] for p in coords) / len(coords)]
        identity = f"{item['type']}/{item['id']}"
        features.append({"type": "Feature", "id": identity, "geometry": {"type": "Point", "coordinates": center},
                         "properties": {"id": identity, "osm_id": identity, "source": "OpenStreetMap",
                                        "name": tags.get("name", "Unnamed mapped settlement"), "place": place,
                                        "place_rank": PLACE_RANK[place], "population": tags.get("population"),
                                        "registry_tags": {key: tags[key] for key in sorted(tags) if key != "place"}}})
    features.sort(key=lambda feature: (feature["properties"]["place_rank"], str(feature["properties"]["name"])))
    return {"type": "FeatureCollection", "features": features,
            "provenance": {"dataset": "OSM mapped settlement registry (place=*)", "kind": "mapped",
                           "registry_element_count": len(features),
                           "limitations": ["Volunteer-mapped reference; completeness is not guaranteed or verified.",
                                           "Absence from this registry is not evidence a settlement is unknown or unoccupied."]}}


def extract_registry_features(osm_raw: dict) -> dict:
    """Extract the mapped-settlement registry via the ingest adapter."""
    from pipeline.ingest.settlements import extract_settlements
    return extract_settlements(osm_raw)


def acquire_osm(args: argparse.Namespace, grid: dict) -> dict:
    from pyproj import Transformer
    inverse = Transformer.from_crs(grid["crs"], 4326, always_xy=True)
    west, north = grid["west"], grid["north"]
    east, south = west + grid["width"] * grid["cell_size_m"], north - grid["height"] * grid["cell_size_m"]
    b = args.buffer_m
    lo, hi = inverse.transform(west - b, south - b), inverse.transform(east + b, north + b)
    bbox = f"{lo[1]},{lo[0]},{hi[1]},{hi[0]}"
    query = f'''[out:json][timeout:120];(
way[highway][highway!~"^(motorway|motorway_link|construction|proposed)$"][area!=yes][foot!=no][access!=private]({bbox});
nwr[amenity~"^(hospital|clinic|doctors)$"]({bbox});
nwr[healthcare~"^(hospital|clinic|doctor|health_post)$"]({bbox});
nwr[place~"^(city|town|village|hamlet|isolated_dwelling|suburb|neighbourhood|farm)$"]({bbox});
);out body geom;'''
    raw_path = args.out / "osm.json"
    # Reuse an identical cached query; avoid burdening public Overpass servers.
    previous = json.loads((args.out / "provenance.json").read_text()).get("osm", {}) if (args.out / "provenance.json").exists() else {}
    cached = raw_path.exists() and previous.get("query") == query
    raw = json.loads(raw_path.read_text()) if cached else request_json(args.overpass, urllib.parse.urlencode({"data": query}).encode(), timeout=150)
    if "remark" in raw:
        raise ValueError(f"Overpass reported an incomplete response: {raw['remark']}")
    write_json(args.out / "osm.json", raw)
    facilities, roads, graph_nodes, graph_edges = [], [], {}, []
    forward = Transformer.from_crs(4326, grid["crs"], always_xy=True)
    for item in raw["elements"]:
        tags = item.get("tags", {})
        identity = f"{item['type']}/{item['id']}"
        if "highway" in tags and item.get("geometry"):
            coords = [[p["lon"], p["lat"]] for p in item["geometry"]]
            if len(coords) > 1:
                roads.append({"type": "Feature", "id": identity, "geometry": {"type": "LineString", "coordinates": coords},
                              "properties": {"id": identity, "osm_id": identity, "nodes": item.get("nodes", []), **tags}})
                node_ids = item.get("nodes", [])
                if len(node_ids) == len(coords):
                    for node_id, coord in zip(node_ids, coords):
                        graph_nodes[str(node_id)] = {"id": str(node_id), "coordinates": coord, "lon": coord[0], "lat": coord[1]}
                    for index in range(len(coords) - 1):
                        a, z = coords[index], coords[index + 1]
                        ax, ay = forward.transform(*a)
                        zx, zy = forward.transform(*z)
                        graph_edges.append({"source": str(node_ids[index]), "target": str(node_ids[index + 1]),
                                            "length_m": math.hypot(zx - ax, zy - ay), "osm_way_id": identity,
                                            "geometry": {"type": "LineString", "coordinates": [a, z]}})
        category = tags.get("amenity") if tags.get("amenity") in ["hospital", "clinic", "doctors"] else tags.get("healthcare")
        if category not in ["hospital", "clinic", "doctors", "doctor", "health_post"]:
            continue
        if item["type"] == "node":
            center = [item["lon"], item["lat"]]
        else:
            coords = item.get("geometry", [])
            if not coords:
                coords = [p for member in item.get("members", []) for p in member.get("geometry", [])]
            if not coords:
                continue
            center = [sum(p["lon"] for p in coords) / len(coords), sum(p["lat"] for p in coords) / len(coords)]
        facilities.append({"type": "Feature", "id": identity, "geometry": {"type": "Point", "coordinates": center},
                           "properties": {"id": identity, "osm_id": identity, "name": tags.get("name", "Unnamed mapped facility"),
                                          "category": category, "source": "OpenStreetMap", **tags}})
    raw_facility_count = len(facilities)
    facilities = deduplicate_facilities(facilities, grid["crs"])
    settlements = extract_registry_features(raw)
    for name, collection in [("facilities", {"type": "FeatureCollection", "features": facilities}),
                             ("roads", {"type": "FeatureCollection", "features": roads}),
                             ("settlements", settlements)]:
        write_json(args.out / f"{name}.geojson", collection)
    write_json(args.out / "graph.json", {"directed": False, "nodes": list(graph_nodes.values()), "edges": graph_edges})
    return {"status": "acquired", "producer": "OpenStreetMap contributors", "name": "OSM walkable ways and mapped healthcare",
            "source_url": args.overpass, "license": "ODbL-1.0", "kind": "mapped",
            "retrieved_at": previous.get("retrieved_at", timestamp()) if cached else timestamp(), "vintage": raw.get("osm3s", {}).get("timestamp_osm_base"),
            "attribution": "© OpenStreetMap contributors; https://www.openstreetmap.org/copyright",
            "buffer_m": b, "bbox": [lo[0], lo[1], hi[0], hi[1]], "query": query,
            "road_ways": len(roads), "raw_facility_objects": raw_facility_count, "facility_objects": len(facilities), "graph_nodes": len(graph_nodes), "graph_edges": len(graph_edges),
            "settlement_registry_records": len(settlements["features"]),
            "files": ["osm.json", "facilities.geojson", "roads.geojson", "settlements.geojson", "graph.json"],
            "limitations": ["Mapped facilities are not an authoritative registry or assurance of service availability.", "Walking links, access tags, facility position and road connectivity require local review.", "Physical facility duplicates are reconciled during preprocessing; raw IDs are preserved."]}


def inventory(out: Path) -> dict:
    expected = {"open_buildings": ["buildings.npz"], "worldpop": ["worldpop2023.tif", "population.npz"], "osm": ["osm.json", "roads.geojson", "facilities.geojson", "graph.json", "settlements.geojson"]}
    old = json.loads((out / "provenance.json").read_text()) if (out / "provenance.json").exists() else {}
    sources = {}
    for name, files in expected.items():
        missing = [filename for filename in files if not (out / filename).exists()]
        sources[name] = {**old.get(name, {}), "status": "not_acquired" if missing else "acquired", "missing_files": missing}
        if missing:
            sources[name].setdefault("reason", "Source files have not been acquired. Run with --sources or import authorized local data.")
    return {"schema_version": 1, "checked_at": timestamp(), "source_mode": "real", "output_directory": str(out),
            "complete": all(s["status"] == "acquired" for s in sources.values()), "sources": sources,
            "dependencies": {p: importlib.util.find_spec(p) is not None for p in ["numpy", "rasterio", "pyproj", "ee"]},
            "earth_engine": {"required_for_gcs_route": False, "credentials_status": "not_checked; no credentials read", "reason": "Anonymous official GCS COG access is preferred. EE export alternative requires an authorized project."}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Local source/dependency inventory; performs no downloads")
    parser.add_argument("--sources", nargs="+", choices=["google", "worldpop", "osm", "all"])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--center", nargs=2, type=float, default=[35.72, 3.18], metavar=("LON", "LAT"),
                        help="Pilot AOI in Turkana County, Kenya: rural area south-west of Lodwar")
    parser.add_argument("--size-m", type=int, default=10000)
    parser.add_argument("--cell-m", type=int, default=250)
    parser.add_argument("--crs", default="EPSG:32636")
    parser.add_argument("--manifest-token", help="Official level-2 S2 manifest token; auto-discovered by default")
    parser.add_argument("--country", default=DEFAULT_COUNTRY, help="ISO3 WorldPop registry code (KEN, UGA …)")
    parser.add_argument("--region-id", default="turkana-real")
    parser.add_argument("--region-name", default="Turkana source sample")
    parser.add_argument("--buffer-m", type=int, default=20000)
    parser.add_argument("--overpass", default=OVERPASS)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    report = inventory(args.out)
    if args.check or not args.sources:
        write_json(args.out / "acquisition-report.json", report)
        print(json.dumps(report, indent=2))
        return 0 if report["complete"] else 2
    if args.size_m <= 0 or args.cell_m <= 0 or args.size_m > 30000 or args.buffer_m < 15000:
        parser.error("Require positive sizes, AOI ≤30 km, facility/network buffer ≥15 km")
    grid = make_grid(args)
    write_json(args.out / "grid.json", grid)
    if not args.manifest_token:
        tokens = manifest_tokens_with_coverage(grid, 2023)
        if not tokens:
            parser.error("No official Open Buildings manifest token covers this AOI and CRS; adjust center/CRS")
        args.manifest_token = tokens[0]
        print(f"Manifest token auto-discovered for this AOI: {args.manifest_token}", flush=True)
    selected = set(args.sources)
    operations = [("google", "open_buildings", acquire_buildings), ("worldpop", "worldpop", acquire_population), ("osm", "osm", acquire_osm)]
    provenance_path = args.out / "provenance.json"
    provenance = json.loads(provenance_path.read_text()) if provenance_path.exists() else {}
    failed = False
    for option, name, operation in operations:
        if "all" not in selected and option not in selected:
            continue
        try:
            provenance[name] = operation(args, grid)
            print(f"{name}: acquired", flush=True)
        except Exception as exc:
            failed = True
            provenance[name] = {"status": "not_acquired", "attempted_at": timestamp(), "reason": f"{type(exc).__name__}: {exc}"}
            print(f"{name}: NOT acquired: {exc}", file=sys.stderr, flush=True)
        write_json(provenance_path, provenance)
        report = inventory(args.out)
        for key, value in provenance.items():
            if value.get("status") == "not_acquired":
                report["sources"][key] = value
        report["complete"] = all(s["status"] == "acquired" for s in report["sources"].values())
        write_json(args.out / "acquisition-report.json", report)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
