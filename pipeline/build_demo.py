"""Prepare explicit synthetic fixtures or a separately acquired real source pack.

    python -m pipeline.build_demo --mode synthetic
    python -m pipeline.build_demo --mode real --source data/raw/mbale-real

There is no automatic synthetic fallback for a failed real-source request.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import heapq
import json
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree
from shapely.geometry import LineString, Point, box, mapping, shape
from shapely.ops import unary_union

from pipeline.geospatial.grid import (AnalysisGrid, allocate_population_nonoverlapping,
                                     cluster_count_grid, project_geometry)
from pipeline.ml.analysis import recompute_analysis
from pipeline.models import validate_package

ROOT = Path(__file__).resolve().parents[1]
YEARS = list(range(2016, 2024))
REGION_ID = "turkana-demo"
SYNTHETIC_LABEL = "Synthetic demonstration data"


def feature_collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def initialise_settlements(settlements: list[dict], *, data_mode: str, years: list[int],
                           source_metadata: dict, population: list[float | None]):
    for index, (settlement, people) in enumerate(zip(settlements, population)):
        settlement.update({
            "display_name": f"Demo candidate {index + 1:02d}" if data_mode == "synthetic" else f"Settlement candidate {index + 1:02d}",
            "data_mode": data_mode, "population_estimate": people,
            "population_reference_year": 2023 if people is not None else None,
            "osm_building_discrepancy": None, "mapped_osm_building_count": None,
            "road_density": None, "road_snap_distance": None,
            "nearest_mapped_facility_id": None, "nearest_mapped_facility_name": None,
            "nearest_mapped_facility_distance_m": None, "walking_route_distance_m": None,
            "walking_time_minutes": None, "routing_status": "not_computed",
            "source_metadata": source_metadata,
            "data_quality_flags": settlement.get("data_quality_flags", []) +
                                  (["synthetic_demonstration_not_evidence"] if data_mode == "synthetic" else []) +
                                  ["occupancy_not_verified", "facility_completeness_not_evaluated", "building_signal_is_not_population",
                                   "representative_point_access_not_all_residents"],
            "accessibility_measurement": {"origin": "geometric centroid of candidate cell union",
                                          "represents": "One representative analysis point; not access for every resident"},
            "verification_status": "unverified",
            "history": [{"year": y, "buildings": settlement["building_count_by_year"].get(str(y))} for y in years],
        })
        if people is None:
            settlement["data_quality_flags"].append("population_unavailable")


def synthetic_transport(grid: AnalysisGrid):
    """An invented graph with exact GeoJSON edge geometry and metric weights."""
    to_wgs = Transformer.from_crs(grid.crs, "EPSG:4326", always_xy=True)
    center_x = grid.west + grid.width * grid.cell_size_m / 2
    center_y = grid.north - grid.height * grid.cell_size_m / 2
    nodes, edges, roads = [], [], []
    positions = {}
    for row in range(23):
        for col in range(23):
            # Shared vertices create genuine topology; bend whole grid gently.
            x = center_x + (col - 11) * 1000 + 95 * np.sin(row / 3)
            y = center_y + (row - 11) * 1000 + 130 * np.sin(col / 4)
            lon, lat = to_wgs.transform(x, y)
            node_id = f"road-{row}-{col}"
            positions[node_id] = (float(x), float(y))
            nodes.append({"id": node_id, "lon": round(lon, 7), "lat": round(lat, 7),
                          "coordinates": [round(lon, 7), round(lat, 7)]})
    lookup = {node["id"]: node for node in nodes}
    for row in range(23):
        for col in range(23):
            here = f"road-{row}-{col}"
            neighbours = []
            if col < 22 and (row % 3 == 0 or col < 12 or row % 5 == 0):
                neighbours.append(f"road-{row}-{col + 1}")
            if row < 22 and (col % 5 == 0 or col == 22 or (row < 9 and col % 3 == 0)):
                neighbours.append(f"road-{row + 1}-{col}")
            for there in neighbours:
                line = LineString([positions[here], positions[there]])
                coordinates = [lookup[here]["coordinates"], lookup[there]["coordinates"]]
                geometry = {"type": "LineString", "coordinates": coordinates}
                length = round(line.length, 2)
                edges.append({"source": here, "target": there, "length_m": length,
                              "geometry": geometry, "walking_allowed": True, "directed": False})
                roads.append({"type": "Feature", "geometry": geometry,
                              "properties": {"id": f"edge-{here}-{there}", "highway": "synthetic_path",
                                             "data_mode": "synthetic", "length_m": length}})
    connected = {edge["source"] for edge in edges} | {edge["target"] for edge in edges}
    nodes = [node for node in nodes if node["id"] in connected]
    records, facilities = [], []
    for index, (row, col) in enumerate([(4, 3), (15, 5), (8, 10), (19, 11), (0, 17)]):
        coordinates = lookup[f"road-{row}-{col}"]["coordinates"]
        record = {"id": f"demo-facility-{index + 1}", "name": f"Demo mapped clinic {chr(65 + index)}",
                  "coordinates": coordinates, "category": "clinic", "data_mode": "synthetic"}
        records.append(record)
        facilities.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": coordinates},
                           "properties": {key: value for key, value in record.items() if key != "coordinates"}})
    return {"nodes": nodes, "edges": edges, "directed": False}, feature_collection(roads), feature_collection(facilities), records


def enrich_spatial_fields(package: dict):
    """Offline accessibility before ML, with metric edge and connection distances.

    The API owns interactive routing and sensitivity scenarios. This precompute
    uses the same 4.2 km/h baseline and includes both off-network connectors.
    """
    grid_crs = package["region"]["metric_crs"]
    to_metric = Transformer.from_crs("EPSG:4326", grid_crs, always_xy=True)
    graph = nx.DiGraph() if package["graph"].get("directed") else nx.Graph()
    positions = {}
    node_coordinates = {}
    for node in package["graph"]["nodes"]:
        coordinates = node.get("coordinates", [node.get("lon"), node.get("lat")])
        positions[node["id"]] = np.array(to_metric.transform(*coordinates))
        node_coordinates[node["id"]] = coordinates
        graph.add_node(node["id"])
    for edge in package["graph"]["edges"]:
        if not edge.get("walking_allowed", True):
            continue
        existing = graph.get_edge_data(edge["source"], edge["target"])
        if existing is None or edge["length_m"] < existing["weight"]:
            graph.add_edge(edge["source"], edge["target"], weight=edge["length_m"], geometry=edge.get("geometry"))
    roads_m = [project_geometry(feature["geometry"], "EPSG:4326", grid_crs)
               for feature in package["roads"]["features"]]
    if not positions:
        for settlement in package["settlements"]:
            settlement["routing_status"] = "insufficient_road_data"
        return
    node_ids = list(positions)
    xy = np.stack([positions[node_id] for node_id in node_ids])
    # Propagate all mapped facilities at once, including individual facility
    # connectors. Store only distances and source IDs, not a full path list for
    # each of hundreds of thousands of buffered OSM vertices.
    tree = cKDTree(xy)
    facility_at_node, baseline_distances, owners, next_to_facility, heap = {}, {}, {}, {}, []
    for facility in package.get("facility_records", []):
        point = np.array(to_metric.transform(*facility["coordinates"]))
        distance, nearest = tree.query(point)
        node = node_ids[int(nearest)]
        if distance <= 1500 and (node not in baseline_distances or distance < baseline_distances[node]):
            baseline_distances[node] = float(distance)
            facility_at_node[node] = (facility, point)
            owners[node] = node
            next_to_facility[node] = None
            heapq.heappush(heap, (float(distance), node))
    reverse_graph = graph.reverse(copy=False) if graph.is_directed() else graph
    while heap:
        distance, node = heapq.heappop(heap)
        if distance != baseline_distances[node]:
            continue
        for neighbour, edge in reverse_graph[node].items():
            candidate = distance + edge["weight"]
            if candidate < baseline_distances.get(neighbour, float("inf")):
                baseline_distances[neighbour] = candidate
                owners[neighbour] = owners[node]
                next_to_facility[neighbour] = node
                heapq.heappush(heap, (candidate, neighbour))
    # Precompute each candidate's per-cell access profile once, offline, so the
    # interactive evidence panel never has to build the large routing engine.
    # Mirror of RoutingEngine.access_profile: same snap + network + 70 m/min
    # (4.2 km/h) semantics; unknown cells are counted, never imputed.
    cell_centroids: dict[str, list[tuple[float, float]]] = {}
    for feature in package.get("cells", {}).get("features", []):
        if not isinstance(feature, dict):
            continue
        cluster_id = feature.get("properties", {}).get("cluster_id")
        ring = (feature.get("geometry") or {}).get("coordinates", [[]])[0]
        if not cluster_id or len(ring) < 3:
            continue
        lon = sum(p[0] for p in ring[:-1]) / (len(ring) - 1)
        lat = sum(p[1] for p in ring[:-1]) / (len(ring) - 1)
        cell_centroids.setdefault(cluster_id, []).append((lon, lat))
    for cluster_id, centroids in cell_centroids.items():
        owner = next((s for s in package["settlements"] if s["id"] == cluster_id), None)
        if owner is None:
            continue
        times, unknown = [], 0
        for lon, lat in centroids:
            cell_point = np.array(to_metric.transform(float(lon), float(lat)))
            snap_distance, nearest = tree.query(cell_point)
            if snap_distance > 1500:
                unknown += 1
                continue
            network_distance = baseline_distances.get(node_ids[int(nearest)])
            if network_distance is None:
                unknown += 1
                continue
            times.append((float(network_distance) + float(snap_distance)) / 70)
        profile: dict[str, Any] = {"cells_measured": len(times), "cells_unknown": unknown,
                                   "walking_speed_kmh": 4.2}
        if times:
            values = np.array(times)
            profile.update({
                "median_minutes": round(float(np.percentile(values, 50)), 1),
                "p90_minutes": round(float(np.percentile(values, 90)), 1),
                "max_minutes": round(float(values.max()), 1),
                "histogram_minutes": np.histogram(values, bins=min(8, max(2, len(values) // 6)))[0].astype(int).tolist(),
            })
        else:
            profile["unknown_reason"] = ("No analysis cell reaches the mapped network or a facility route; access across this candidate remains unknown.")
        owner["access_profile"] = profile
    for settlement in package["settlements"]:
        point = np.array(to_metric.transform(*settlement["centroid"]))
        snap, nearest = tree.query(point)
        snap = float(snap)
        nearest = int(nearest)
        settlement["road_snap_distance"] = round(snap, 1)
        search_area = Point(*point).buffer(2000)
        settlement["road_density"] = round(sum(road.intersection(search_area).length for road in roads_m) / 1000 / (search_area.area / 1e6), 3)
        if snap > 1500:
            settlement["routing_status"] = "insufficient_road_connection"
            settlement["data_quality_flags"].append("road_connection_exceeds_1500m")
            continue
        node = node_ids[nearest]
        if node not in baseline_distances:
            settlement["routing_status"] = "disconnected_or_no_mapped_facility"
            settlement["data_quality_flags"].append("mapped_walking_route_unavailable")
            continue
        length = baseline_distances[node] + snap
        facility, facility_point = facility_at_node[owners[node]]
        points = [settlement["centroid"], node_coordinates[node]]
        current = node
        while next_to_facility[current] is not None:
            following = next_to_facility[current]
            geometry = graph[current][following].get("geometry")
            segment = list(geometry["coordinates"]) if geometry else [node_coordinates[current], node_coordinates[following]]
            if segment[0] != node_coordinates[current]:
                segment.reverse()
            points.extend(segment[1:])
            current = following
        points.append(facility["coordinates"])
        clean = [points[0]] + [point for i, point in enumerate(points[1:], 1) if point != points[i - 1]]
        if len(clean) == 1:
            clean.append(clean[0])
        walk = length / 70
        settlement.update(nearest_mapped_facility_id=facility["id"], nearest_mapped_facility_name=facility["name"],
                          nearest_mapped_facility_distance_m=round(float(np.linalg.norm(point - facility_point)), 1),
                          walking_route_distance_m=round(float(length), 1), walking_time_minutes=round(float(walk), 1),
                          route_geometry={"type": "LineString", "coordinates": clean},
                          walking_speed_kmh=4.2,
                          road_network_connection_quality="good" if snap <= 250 else "long_off_network_connection",
                          travel_time_band="under_30" if walk < 30 else "30_60" if walk < 60 else "60_120" if walk < 120 else "over_120",
                          walking_time_sensitivity={"slow_3_kmh": round(float(length / 50), 1),
                                                    "baseline_4_2_kmh": round(float(walk), 1),
                                                    "fast_5_kmh": round(float(length / (5000 / 60)), 1)},
                          routing_status="routable")


def clip_render_roads(roads: dict, grid: AnalysisGrid, buffer_m: float = 1000, tolerance_m: float = 5) -> dict:
    """Compact display layer; routing keeps the full independently buffered graph."""
    area = box(grid.west - buffer_m, grid.north - grid.height * grid.cell_size_m - buffer_m,
               grid.west + grid.width * grid.cell_size_m + buffer_m, grid.north + buffer_m)
    features = []
    for feature in roads["features"]:
        line = project_geometry(feature["geometry"], "EPSG:4326", grid.crs)
        if not line.intersects(area):
            continue
        clipped = line.intersection(area).simplify(tolerance_m, preserve_topology=True)
        if clipped.is_empty or clipped.geom_type not in ("LineString", "MultiLineString"):
            continue
        features.append({**feature, "geometry": mapping(project_geometry(clipped, grid.crs, "EPSG:4326"))})
    return feature_collection(features)


def synthetic_registry(settlements: list[dict], rng: np.random.Generator) -> list[dict]:
    """Explicitly invented invented registry, exercising all match outcomes.

    Roughly matched, ambiguous and unmatched coverage so the demonstration
    shows mapping gaps, access gaps and combined gaps side by side. All
    registry names are invented and labelled as fixture data.
    """
    places = ["village", "hamlet", "isolated_dwelling", "village", "hamlet"]
    registers = []
    for index, settlement in enumerate(settlements):
        remainder = index % 5
        if remainder == 2:
            continue  # leave every fifth cluster unmatched on purpose
        offset = 120 if remainder in (0, 1) else 700
        angle = float(rng.uniform(0, 2 * np.pi))
        lon = settlement["centroid"][0] + offset * np.cos(angle) / 111320
        lat = settlement["centroid"][1] + offset * np.sin(angle) / 111320
        registers.append({
            "type": "Feature", "id": f"demo-registry-{index + 1:02d}",
            "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]},
            "properties": {"id": f"demo-registry-{index + 1:02d}", "source": "Synthetic demonstration registry",
                           "name": f"Invented settlement {chr(65 + index % 26)}{index + 1}",
                           "place": places[index % len(places)], "place_rank": index % 6 + 1,
                           "verification_status": "invented_fixture_record"},
        })
    return registers


def attach_registry_evidence(package: dict, *, invented_registry: bool = False) -> dict:
    """Match candidates to the settlement registry and classify candidate gaps."""
    from pipeline.geospatial.gaps import classify_candidate_gaps, match_settlements_to_registry, registry_recall
    crs = package["region"]["metric_crs"]
    matching = match_settlements_to_registry(package["settlements"], package.get("registry") or {"features": []}, crs)
    classification = classify_candidate_gaps(package["settlements"])
    manifest = package.setdefault("manifest", {})
    manifest["settlement_registry"] = {
        "record_count": len((package.get("registry") or {}).get("features", [])),
        "invented_fixture": invented_registry,
        "matching": matching, "gap_classification": classification,
    }
    if not invented_registry:
        manifest["settlement_registry_recall"] = registry_recall(package)
    for settlement in package["settlements"]:
        gap = settlement.get("candidate_gap_type")
        if gap and gap not in ("none",):
            settlement["data_quality_flags"].append(f"candidate_gap_{gap}")
        if invented_registry:
            settlement["registry_matches"] = [
                {**record, "source": "Synthetic demonstration registry"} for record in settlement.get("registry_matches", [])]
    return manifest["settlement_registry"]


def build_synthetic() -> dict:
    rng = np.random.default_rng(20261017)
    center = (35.70, 3.05)  # Turkana County, Kenya (invented fixture data at a real geographic reference)
    to_metric = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True)
    center_x, center_y = to_metric.transform(*center)
    grid = AnalysisGrid("EPSG:32636", round((center_x - 12500) / 250) * 250,
                        round((center_y + 12500) / 250) * 250, 100, 100)
    counts = {year: np.zeros(grid.shape) for year in YEARS}
    population = np.zeros(grid.shape)
    # Synthetic population fields are generated independently of building counts.
    # They are illustrative simulated raster counts, never attributed to WorldPop.
    for cluster_row in range(6):
        for cluster_col in range(7):
            row = 10 + cluster_row * 15 + int(rng.integers(-1, 2))
            col = 10 + cluster_col * 13 + int(rng.integers(-1, 2))
            height, width = int(rng.integers(2, 4)), int(rng.integers(2, 4))
            baseline = float(rng.uniform(14, 70))
            growth = float(rng.uniform(-.08, 2.6))
            if cluster_row > 3 and cluster_col > 4:
                growth += .8
            cell_weights = rng.uniform(.65, 1.4, size=(height, width))
            for year in YEARS:
                progress = (year - 2016) / 7
                noise = rng.normal(0, .025, size=(height, width))
                counts[year][row:row + height, col:col + width] = np.maximum(8.1, baseline * cell_weights * (1 + growth * progress + noise))
            population[row:row + height, col:col + width] = rng.uniform(45, 380, size=(height, width)) * rng.uniform(.6, 1.5)
    settlements, cells = cluster_count_grid(grid, counts, region_id=REGION_ID)
    for cell in cells:
        cell["properties"].update(data_mode="synthetic", evidence_type="simulated_analysis_count_grid")
    source = {"data_mode": "synthetic", "building_source": "Simulated count-grid fixture; Google data not used",
              "population_source": "Independently simulated population-count raster; WorldPop not used",
              "facility_source": "Invented mapped clinics", "road_source": "Invented walkable graph",
              "years": YEARS, "attribution": "Missing Millions deterministic fixture generator"}
    initialise_settlements(settlements, data_mode="synthetic", years=YEARS,
                           source_metadata=source, population=allocate_population_nonoverlapping(population, settlements))
    for settlement in settlements:
        # Simulated mapped-building observations, clearly labelled with all fixture data.
        latest = settlement["building_count_by_year"]["2023"]
        mapped = int(round(latest * rng.uniform(.08, .95)))
        settlement["mapped_osm_building_count"] = mapped
        settlement["osm_building_discrepancy"] = round(max(0, 1 - mapped / latest), 3)
    graph, roads, facilities, records = synthetic_transport(grid)
    registry_records = synthetic_registry(settlements, rng)
    bbox_metric = box(grid.west, grid.north - 25000, grid.west + 25000, grid.north)
    bbox = list(project_geometry(bbox_metric, grid.crs, "EPSG:4326").bounds)
    package = {"region": {"id": REGION_ID, "name": "Turkana hinterland", "country": "Kenya",
                           "bbox": bbox, "center": list(center), "data_mode": "synthetic", "years": YEARS,
                           "metric_crs": grid.crs, "label": SYNTHETIC_LABEL,
                           "description": "Invented settlements near a real geographic reference. No real discovery or service-gap claim."},
               "settlements": settlements, "facilities": facilities, "facility_records": records,
               "registry": feature_collection(registry_records),
               "roads": roads, "cells": feature_collection(cells), "graph": graph,
               "manifest": {"data_mode": "synthetic", "label": SYNTHETIC_LABEL,
                            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
                            "generator_seed": 20261017,
                            "datasets": [{"name": "Deterministic synthetic count grids", "producer": "Missing Millions fixture generator",
                                          "source_url": None, "vintage": "Simulated 2016–2023 observations",
                                          "retrieval_timestamp": None, "license": "Project demonstration fixture",
                                          "resolution_m": 250, "coverage": bbox, "value_type": "simulated",
                                          "limitations": ["No real satellite, WorldPop or OSM observations are represented.",
                                                          "No medical need, occupancy or intervention effect can be inferred."]}],
                            "processing_steps": ["Simulate eight annual independent count-grid observations", "DBSCAN on 250m occupied-looking cells",
                                                 "Union nonoverlapping cells; sum count grids; retain sparse clusters for review",
                                                 "Aggregate independently simulated population cells",
                                                 "Shortest paths over invented walking graph incl connectors", "Match candidates to the invented registry and classify mapping/access/combined gaps",
                                                 "Five seeded Isolation Forests", "Fixed-weight regional priority"],
                            "parameters": {"grid_size_m": 250, "dbscan_eps_m": 360, "dbscan_min_samples": 2,
                                           "min_buildings_per_cell": 8, "min_buildings_per_cluster": 30,
                                           "sparse_minimum_cluster_buildings": 12,
                                           "walking_speed_kmh": 4.2, "maximum_snap_distance_m": 1500,
                                           "registry_match_radius_m": 400, "registry_confidence_radius_m": 900,
                                           "gap_access_threshold_minutes": 60},
                            "limitations": ["Synthetic demonstration data; no real discovery.", "Rank stability is not calibrated predictive confidence.",
                                            "Priorities are planning assumptions for human investigation.", "Local organisations and communities must validate findings."]}}
    enrich_spatial_fields(package)
    attach_registry_evidence(package, invented_registry=True)
    package["manifest"].update(recompute_analysis(settlements))
    package["settlements"].sort(key=lambda s: s.get("priority_score") if s.get("priority_score") is not None else -1, reverse=True)
    return package


def build_real(source_dir: Path) -> dict:
    """Consume only explicit acquired real aggregates; missing sources stay null."""
    grid_info = json.loads((source_dir / "grid.json").read_text())
    grid = AnalysisGrid(**{key: grid_info[key] for key in ("crs", "west", "north", "width", "height", "cell_size_m")})
    region_id = grid_info.get("region_id", "mbale-real")
    raster_pack = np.load(source_dir / "buildings.npz")
    count_by_year = {int(key.removeprefix("counts_")): raster_pack[key] for key in raster_pack.files if key.startswith("counts_")}
    years = sorted(count_by_year)
    settlements, cells = cluster_count_grid(grid, count_by_year, region_id=region_id,
                                           minimum_cell_count=8, eps_m=360, min_samples=2)
    for settlement in settlements:
        presence = {}
        for year in years:
            key = f"presence_{year}"
            if key in raster_pack.files:
                values = np.array([raster_pack[key][r, c] for r, c in settlement["cell_indices"]])
                presence[str(year)] = round(float(np.nanmean(values)), 4) if np.any(np.isfinite(values)) else None
        settlement["building_presence"]["mean_uncalibrated_score_by_year"] = presence
        settlement["building_presence"]["limitation"] = "Relative satellite-model signal; not calibrated probability or occupancy evidence"
    for cell in cells:
        cell["properties"].update(data_mode="real", evidence_type="aggregated_satellite_fractional_count_grid")
    pop_path = source_dir / "population.npz"
    pop = np.load(pop_path)["population"] if pop_path.exists() else np.full(grid.shape, np.nan)
    provenance = json.loads((source_dir / "provenance.json").read_text())
    source_metadata = {"data_mode": "real", "building_source": "Google Open Buildings 2.5D Temporal v1",
                       "population_source": "WorldPop 2023" if pop_path.exists() else "Unavailable", "years": years,
                       "population_aggregation": "Sum of WorldPop count pixels assigned once to nonoverlapping candidate analysis cells; not a resident census"}
    initialise_settlements(settlements, data_mode="real", years=years, source_metadata=source_metadata,
                           population=allocate_population_nonoverlapping(pop, settlements))
    facility_path, roads_path = source_dir / "facilities.geojson", source_dir / "roads.geojson"
    facilities = json.loads(facility_path.read_text()) if facility_path.exists() else feature_collection([])
    roads = json.loads(roads_path.read_text()) if roads_path.exists() else feature_collection([])
    registry_path = source_dir / "settlements.geojson"
    # A missing or empty registry is recorded honestly; mapping-gap comparison
    # then reports 'no_registry' instead of silently claiming a mapping gap.
    registry = json.loads(registry_path.read_text()) if registry_path.exists() else {"type": "FeatureCollection", "features": []}
    records = [{**feature["properties"], "coordinates": feature["geometry"]["coordinates"]} for feature in facilities["features"]]
    # Acquisition emits a topology-preserving OSM graph when available. Rendering
    # road lines alone must never be treated as a routable connected graph.
    graph_path = source_dir / "graph.json"
    graph = json.loads(graph_path.read_text()) if graph_path.exists() else {"nodes": [], "edges": [], "directed": False}
    bbox = list(project_geometry(box(grid.west, grid.north - grid.height * grid.cell_size_m,
                                     grid.west + grid.width * grid.cell_size_m, grid.north), grid.crs, "EPSG:4326").bounds)
    manifest = {"data_mode": "real", "label": "Model-derived geographic evidence; unverified",
                "analysis_timestamp": datetime.now(timezone.utc).isoformat(), "sources": provenance,
                "datasets": list(provenance.values()),
                "parameters": {"grid_size_m": grid.cell_size_m, "dbscan_eps_m": 360, "dbscan_min_samples": 2,
                               "min_buildings_per_cell": 8, "sparse_minimum_cluster_buildings": 12, "walking_speed_kmh": 4.2},
                "aggregation_audit": {"aoi_building_count_by_year": {str(year): round(float(np.nansum(values)), 4) for year, values in count_by_year.items()},
                                      "candidate_building_count_by_year": {str(year): round(sum(s["building_count_by_year"][str(year)] or 0 for s in settlements), 2) for year in years},
                                      "aoi_population_grid_sum": round(float(np.nansum(pop)), 4) if np.any(np.isfinite(pop)) else None,
                                      "candidate_population_sum": round(sum(s["population_estimate"] or 0 for s in settlements), 1),
                                      "source_grid_cell_count": grid.width * grid.height,
                                      "candidate_grid_cell_count": len(cells),
                                      "explanation": "Candidate totals include only supported DBSCAN cell unions. Remaining AOI count signal is not assigned to a candidate."},
                "limitations": ["Buildings do not establish occupancy.", "Mapped facilities and paths may be incomplete.",
                                "Travel time describes a candidate centroid, not within-settlement travel or every resident's access.",
                                "The broad connected urban candidate can contain substantial differences in access within its boundary.",
                                "Endpoint changes may include temporal model noise.",
                                "The settlement registry is a mapped reference layer only; its completeness was not verified and unmatched does not mean unknown.",
                                "Human verification is required."]}
    package = {"region": {"id": region_id, "name": grid_info.get("region_name", "Turkana source sample"),
                           "country": grid_info.get("country", "Kenya"), "bbox": bbox,
                           "center": [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2], "data_mode": "real",
                           "years": years, "metric_crs": grid.crs, "label": "Real source sample — unverified"},
               "settlements": settlements, "cells": feature_collection(cells), "roads": roads,
               "facilities": facilities, "facility_records": records, "registry": registry, "graph": graph, "manifest": manifest}
    enrich_spatial_fields(package)
    attach_registry_evidence(package, invented_registry=False)
    manifest["parameters"].update({"registry_match_radius_m": 400, "registry_confidence_radius_m": 900,
                                   "gap_access_threshold_minutes": 60})
    facility_lookup = {facility["id"]: facility for facility in records}
    for settlement in settlements:
        if len(settlements) < 30:
            settlement["data_quality_flags"].append("small_regional_comparison_sample")
        nearest = facility_lookup.get(settlement["nearest_mapped_facility_id"], {})
        # Retain the source's clinic tag, while exposing contradictory descriptive
        # evidence rather than treating the name as assurance of general care.
        description = f"{nearest.get('name', '')} {nearest.get('description', '')}".lower()
        if any(term in description for term in ("drug shop", "drugshop", "pharmacy", "dental", "dentist")):
            settlement["data_quality_flags"].append("mapped_facility_category_requires_verification")
        settlement["nearest_mapped_facility_category"] = nearest.get("category")
        settlement["nearest_mapped_facility_source_tags"] = {key: nearest[key] for key in ("amenity", "healthcare", "description") if key in nearest}
    package["manifest"].update(recompute_analysis(settlements))
    package["roads"] = clip_render_roads(roads, grid)
    package["manifest"]["rendering"] = {"road_clip_buffer_m": 1000, "road_simplification_m": 5,
                                           "routing_graph_preserves_full_buffer": True}
    return package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["synthetic", "real"], default="synthetic")
    parser.add_argument("--source", type=Path, default=ROOT / "data/raw/mbale-real")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    package = build_synthetic() if args.mode == "synthetic" else build_real(args.source)
    validate_package(package)
    output = args.output or ROOT / "data/processed" / ("demo.json" if args.mode == "synthetic" else "real.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(package, separators=(",", ":"), allow_nan=False))
    print(f"Prepared {len(package['settlements'])} {args.mode} candidates → {output}")


if __name__ == "__main__":
    main()
