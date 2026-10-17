"""Projected, network-based accessibility and greedy outreach coverage.

External geometries are WGS84; distances are calculated in the region's UTM CRS.
Both settlement and facility connectors are included in route distances. A missing
path is unknown accessibility, never an infinite travel-time or evidence of need.
"""

from __future__ import annotations

from copy import deepcopy
from math import floor, hypot, isfinite
from typing import Any

import networkx as nx
from pyproj import Transformer
from scipy.spatial import cKDTree


def feature_collection(features: list[dict]) -> dict:
    return {"type": "FeatureCollection", "features": features}


def coordinates(record: dict) -> list[float]:
    value = record.get("centroid") or record.get("coordinates")
    if isinstance(value, dict):
        value = value.get("coordinates")
    if value is None and record.get("geometry", {}).get("type") == "Point":
        value = record["geometry"]["coordinates"]
    if value is None:
        value = [record["lon"], record["lat"]]
    return [float(value[0]), float(value[1])]


class RoutingEngine:
    def __init__(
        self,
        graph_data: dict,
        facilities: list[dict] | dict,
        walking_speed_kmh: float = 4.2,
        max_snap_distance_m: float = 1500,
        projected_crs: str | None = None,
    ) -> None:
        self.speed = walking_speed_kmh
        self.max_snap = max_snap_distance_m
        self.graph: nx.Graph = nx.DiGraph() if graph_data.get("directed", False) else nx.Graph()
        self.node_coordinates = {
            str(node["id"]): coordinates(node) for node in graph_data.get("nodes", [])
        }
        midpoint = next(iter(self.node_coordinates.values()), [33.0, 1.0])
        zone = min(60, max(1, floor((midpoint[0] + 180) / 6) + 1))
        self.projected_crs = projected_crs or f"EPSG:{32600 + zone if midpoint[1] >= 0 else 32700 + zone}"
        self.project = Transformer.from_crs("EPSG:4326", self.projected_crs, always_xy=True)
        self.unproject = Transformer.from_crs(self.projected_crs, "EPSG:4326", always_xy=True)
        self.xy = {node: self.project.transform(*point) for node, point in self.node_coordinates.items()}
        self.node_ids = list(self.xy)
        self.spatial_index = cKDTree([self.xy[node] for node in self.node_ids]) if self.node_ids else None
        self.graph.add_nodes_from(self.xy)
        for edge in graph_data.get("edges", []):
            source, target = str(edge["source"]), str(edge["target"])
            if source not in self.xy or target not in self.xy:
                continue
            geometry = edge.get("geometry") or {
                "type": "LineString",
                "coordinates": [self.node_coordinates[source], self.node_coordinates[target]],
            }
            length = edge.get("length_m")
            if length is None:
                points = [self.project.transform(*p) for p in geometry["coordinates"]]
                length = sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(points, points[1:]))
            if not isfinite(float(length)) or float(length) < 0:
                raise ValueError("Road-edge length must be a finite non-negative number")
            existing = self.graph.get_edge_data(source, target)
            if existing is None or float(length) < existing["length_m"]:
                self.graph.add_edge(source, target, length_m=float(length), geometry=geometry)
        # Reverse views share edge/node storage. A large buffered OSM network
        # must not become several complete graph copies in a request process.
        self.reverse = self.graph.reverse(copy=False) if self.graph.is_directed() else self.graph
        if isinstance(facilities, dict):
            facilities = [dict(item.get("properties", {}), coordinates=item["geometry"]["coordinates"])
                          for item in facilities.get("features", [])]
        self.facilities = facilities
        self.facility_at_node: dict[str, dict] = {}
        self.facility_snap: dict[str, float] = {}
        for facility in facilities:
            node, distance = self.snap(coordinates(facility))
            if node is not None and distance <= max_snap_distance_m:
                if node not in self.facility_snap or distance < self.facility_snap[node]:
                    self.facility_at_node[node] = facility
                    self.facility_snap[node] = distance
        # A virtual source gives each facility its actual off-network connection
        # cost. Reversing directed roads computes travel TO facilities correctly.
        virtual = "__mapped_facilities__"
        while virtual in self.reverse:
            virtual += "_"
        self.virtual_source = virtual
        self.graph.add_node(virtual)
        for node, distance in self.facility_snap.items():
            if self.graph.is_directed():
                self.graph.add_edge(node, virtual, length_m=distance)
            else:
                self.graph.add_edge(virtual, node, length_m=distance)
        try:
            # Full path lists to every buffered road node can be quadratic on
            # long paths. Retain predecessors and reconstruct only candidate
            # settlement routes that are actually requested.
            self.baseline_predecessors, self.baseline_distances = nx.dijkstra_predecessor_and_distance(
                self.reverse, virtual, weight="length_m"
            )
        finally:
            self.graph.remove_node(virtual)
        self.candidate_distances: dict[str, dict[str, float]] = {}
        self.settlement_distances: dict[tuple[str, float], dict[str, float]] = {}

    def snap(self, point: list[float]) -> tuple[str | None, float]:
        if not self.xy:
            return None, float("inf")
        x, y = self.project.transform(*point)
        distance, index = self.spatial_index.query([x, y])
        return self.node_ids[index], float(distance)

    @staticmethod
    def minutes(distance: float, speed: float) -> float:
        return distance / (speed * 1000 / 60)

    def route(self, settlement: dict, walking_speed_kmh: float | None = None) -> dict:
        speed = walking_speed_kmh or self.speed
        center = coordinates(settlement)
        node, snap_distance = self.snap(center)
        result: dict[str, Any] = {
            "nearest_mapped_facility_id": None,
            "nearest_mapped_facility_name": None,
            "nearest_mapped_facility_distance_m": None,
            "walking_route_distance_m": None,
            "walking_time_minutes": None,
            "road_snap_distance": round(snap_distance, 1) if isfinite(snap_distance) else None,
            "road_network_connection_quality": "unknown",
            "routing_status": "insufficient_network",
            "route_geometry": None,
            "walking_speed_kmh": speed,
            "travel_time_band": "unknown",
            "walking_time_sensitivity": {"slow_3_kmh": None, "baseline_4_2_kmh": None, "fast_5_kmh": None},
        }
        if node is None or snap_distance > self.max_snap:
            return result
        result["road_network_connection_quality"] = "good" if snap_distance <= 250 else "long_off_network_connection"
        if node not in self.baseline_distances:
            result["routing_status"] = "disconnected_network" if self.facilities else "no_mapped_facilities"
            return result
        route_nodes = [node]
        while self.virtual_source not in self.baseline_predecessors[route_nodes[-1]]:
            route_nodes.append(self.baseline_predecessors[route_nodes[-1]][0])
        facility = self.facility_at_node[route_nodes[-1]]
        facility_coordinates = coordinates(facility)
        facility_xy = self.project.transform(*facility_coordinates)
        center_xy = self.project.transform(*center)
        distance = self.baseline_distances[node] + snap_distance
        minutes = self.minutes(distance, speed)
        points = [center, self.node_coordinates[route_nodes[0]]]
        for source, target in zip(route_nodes, route_nodes[1:]):
            segment = deepcopy(self.graph[source][target]["geometry"]["coordinates"])
            if segment[0] != self.node_coordinates[source]:
                segment.reverse()
            points.extend(segment[1:])
        points.append(facility_coordinates)
        clean = [points[0]]
        clean.extend(p for i, p in enumerate(points[1:], 1) if p != points[i - 1])
        if len(clean) == 1:
            clean.append(clean[0])
        result.update({
            "nearest_mapped_facility_id": facility["id"],
            "nearest_mapped_facility_name": facility.get("name", "Mapped healthcare facility"),
            "nearest_mapped_facility_distance_m": round(hypot(center_xy[0] - facility_xy[0], center_xy[1] - facility_xy[1]), 1),
            "walking_route_distance_m": round(distance, 1),
            "walking_time_minutes": round(minutes, 1),
            "routing_status": "routable",
            "route_geometry": {"type": "LineString", "coordinates": clean},
            "travel_time_band": "under_30" if minutes < 30 else "30_60" if minutes < 60 else "60_120" if minutes < 120 else "over_120",
            "walking_time_sensitivity": {
                "slow_3_kmh": round(self.minutes(distance, 3), 1),
                "baseline_4_2_kmh": round(self.minutes(distance, 4.2), 1),
                "fast_5_kmh": round(self.minutes(distance, 5), 1),
            },
        })
        return result

    def access_profile(self, cell_centroids: list[list[float]]) -> dict:
        """Per-cell walk times for one candidate's analysis cells.

        Distances remain snap-to-network + network-to-facility for every cell, so
        a large candidate reports how WORSE the worst-tenth of residents sit,
        not just its centroid. Unknown cells (off-network, disconnected) stay
        unknown and are counted, never imputed.
        """
        if not cell_centroids:
            return {"cells_measured": 0, "cells_unknown": 0,
                    "median_minutes": None, "p90_minutes": None, "max_minutes": None,
                    "note": "No analysis cells recorded for this candidate."}
        times, unknown = [], 0
        for centroid in cell_centroids:
            node, snap_distance = self.snap(centroid)
            if node is None or snap_distance > self.max_snap:
                unknown += 1
                continue
            network_distance = self.baseline_distances.get(node)
            if network_distance is None:
                unknown += 1
                continue
            times.append(self.minutes(network_distance + snap_distance, self.speed))
        if not times:
            return {"cells_measured": 0, "cells_unknown": len(cell_centroids),
                    "unknown_reason": "No analysis cell reaches the mapped network or a facility route; access across this candidate remains unknown."}
        from math import isfinite
        import numpy as np
        values = np.array([t for t in times if isfinite(t)])
        profile = {
            "cells_measured": int(len(values)),
            "cells_unknown": int(unknown),
            "median_minutes": round(float(np.percentile(values, 50)), 1),
            "p90_minutes": round(float(np.percentile(values, 90)), 1),
            "max_minutes": round(float(values.max()), 1),
            "histogram_minutes": np.histogram(values, bins=min(8, max(2, int(len(values) // 6))))[0].astype(int).tolist(),
            "walking_speed_kmh": self.speed,
        }
        return profile

    def enrich(self, settlements: list[dict]) -> list[dict]:
        for settlement in settlements:
            settlement.update(self.route(settlement))
            if settlement["routing_status"] != "routable":
                flags = settlement.setdefault("data_quality_flags", [])
                if "Mapped-network accessibility unknown" not in flags:
                    flags.append("Mapped-network accessibility unknown")
        return settlements

    def _distances_to(self, node: str) -> dict[str, float]:
        if node not in self.candidate_distances:
            self.candidate_distances[node] = nx.single_source_dijkstra_path_length(
                self.reverse, node, weight="length_m"
            )
        return self.candidate_distances[node]

    def _distances_from(self, node: str, cutoff: float) -> dict[str, float]:
        key = (node, cutoff)
        if key not in self.settlement_distances:
            self.settlement_distances[key] = nx.single_source_dijkstra_path_length(
                self.graph, node, cutoff=cutoff, weight="length_m"
            )
        return self.settlement_distances[key]

    def simulate(self, settlements: list[dict], target_ids: list[str], coverage_minutes: float = 30,
                 locations: int = 1, walking_speed_kmh: float = 4.2,
                 fixed_location: list[float] | tuple[float, float] | None = None) -> dict:
        threshold_m = coverage_minutes * walking_speed_kmh * 1000 / 60
        manual_node, manual_snap = None, None
        if fixed_location is not None:
            manual_node, manual_snap = self.snap(fixed_location)
            if manual_node is None:
                raise ValueError("No mapped walking network is available for a fixed outreach location")
            if manual_snap > self.max_snap:
                raise ValueError(f"Fixed location is too far from the mapped walking network; maximum connection is {self.max_snap:g} metres")
        target_set = set(target_ids) if target_ids else {s["id"] for s in settlements}
        snaps = {s["id"]: self.snap(coordinates(s)) for s in settlements}
        # Distances FROM each settlement TO every candidate are sufficient for
        # evaluating all stops. This needs O(settlements) graph traversals rather
        # than O(road nodes), and respects directed networks.
        source_distances = {node: self._distances_from(node, threshold_m) for node, connector in snaps.values()
                            if node is not None and connector <= self.max_snap}
        populations = {s["id"]: max(0, float(s.get("population_estimate") or 0)) for s in settlements}
        before: dict[str, float | None] = {}
        for item in settlements:
            node, connector = snaps[item["id"]]
            distance = self.baseline_distances.get(node) if node is not None and connector <= self.max_snap else None
            before[item["id"]] = distance + connector if distance is not None else None
        covered = {sid for sid, d in before.items() if d is not None and d <= threshold_m}
        initial_covered = set(covered)
        candidate_nodes = set()
        for sid in target_set - covered:
            node, connector = snaps[sid]
            if populations[sid] > 0 and node in source_distances:
                candidate_nodes.update(candidate for candidate, distance in source_distances[node].items()
                                       if distance + connector <= threshold_m)
        if manual_node is not None:
            candidate_nodes = {manual_node}
        selected: list[str] = []
        stops = []
        for index in range(1 if manual_node is not None else locations):
            best: tuple[float, float, str, set[str]] | None = None
            for node in sorted(candidate_nodes):
                if node in selected:
                    continue
                reach = {sid for sid, (snap_node, connector) in snaps.items()
                         if snap_node is not None and connector <= self.max_snap
                         and node in source_distances[snap_node]
                         and source_distances[snap_node][node] + connector <= threshold_m}
                gain = sum(populations[sid] for sid in reach - covered if sid in target_set)
                total_gain = sum(populations[sid] for sid in reach - covered)
                if best is None or (gain, total_gain) > (best[0], best[1]):
                    best = (gain, total_gain, node, reach)
            if best is None or (best[0] <= 0 and manual_node is None):
                break
            gain, total_gain, node, reach = best
            selected.append(node)
            stops.append({
                "id": f"hypothetical-outreach-{index + 1}", "node_id": node,
                "coordinates": self.node_coordinates[node],
                "name": f"Hypothetical outreach point {index + 1}",
                "incremental_target_population": round(gain),
                "incremental_covered_population": round(total_gain),
                "covered_settlement_ids": sorted(reach), "simulated": True,
                **({"manual": True, "snap_distance_m": round(manual_snap, 1),
                    "requested_coordinates": list(fixed_location)} if manual_node is not None else {}),
            })
            covered.update(reach)
        changes = []
        outreach_covered = set()
        for item in settlements:
            sid = item["id"]
            node, connector = snaps[sid]
            outreach_distances = [self._distances_to(stop).get(node) for stop in selected]
            distances = [d + connector for d in outreach_distances
                         if d is not None and connector <= self.max_snap]
            outreach_distance = min(distances) if distances else None
            alternatives = [d for d in [before[sid], outreach_distance] if d is not None]
            after = min(alternatives) if alternatives else None
            if outreach_distance is not None and outreach_distance <= threshold_m:
                outreach_covered.add(sid)
            changes.append({
                "id": sid, "before_minutes": round(self.minutes(before[sid], walking_speed_kmh), 1) if before[sid] is not None else None,
                "after_minutes": round(self.minutes(after, walking_speed_kmh), 1) if after is not None else None,
                "outreach_minutes": round(self.minutes(outreach_distance, walking_speed_kmh), 1) if outreach_distance is not None else None,
                "newly_covered": sid in covered - initial_covered,
                "population_estimate": item.get("population_estimate"),
            })
        network = []
        # Reachable road segments, clipped to the threshold. No buffer is presented
        # as a walk-time polygon; off-network travel is only a connector estimate.
        for stop in selected:
            distances = nx.single_source_dijkstra_path_length(self.reverse, stop, cutoff=threshold_m, weight="length_m")
            for source, target, edge in self.graph.edges(data=True):
                if self.graph.is_directed():
                    from_node, to_node = target, source
                else:
                    from_node, to_node = (source, target) if distances.get(source, float("inf")) <= distances.get(target, float("inf")) else (target, source)
                start_distance = distances.get(from_node)
                if start_distance is None or start_distance >= threshold_m:
                    continue
                fraction = min(1.0, (threshold_m - start_distance) / max(edge["length_m"], 1e-9))
                shape = deepcopy(edge["geometry"])
                if shape["coordinates"][0] != self.node_coordinates[from_node]:
                    shape["coordinates"].reverse()
                if fraction < 1:
                    from shapely.geometry import LineString, mapping
                    from shapely.ops import substring
                    line = LineString([self.project.transform(*p) for p in shape["coordinates"]])
                    clipped = substring(line, 0, line.length * fraction)
                    if clipped.geom_type != "LineString":
                        continue
                    shape = {"type": "LineString", "coordinates": [list(self.unproject.transform(*p)) for p in clipped.coords]}
                network.append({"type": "Feature", "geometry": shape,
                                "properties": {"outreach_node_id": stop, "coverage_minutes": coverage_minutes, "simulated": True}})
        total = lambda ids: round(sum(populations[sid] for sid in ids))
        return {
            "locations": stops,
            "summary": {
                "baseline_covered_population": total(initial_covered),
                "scenario_covered_population": total(covered),
                "incremental_covered_population": total(covered - initial_covered),
                "outreach_covered_population": total(outreach_covered),
                "target_incremental_population": total((covered - initial_covered) & target_set),
                "newly_covered_settlements": len(covered - initial_covered),
                "coverage_minutes": coverage_minutes, "walking_speed_kmh": walking_speed_kmh,
                "requested_locations": locations, "proposed_locations": len(stops),
                "unknown_population_settlements": sum(s.get("population_estimate") is None for s in settlements),
                "target_settlement_ids": sorted(target_set),
            },
            "settlements": changes,
            "coverage_network": feature_collection(network),
            "assumptions": [
                "Hypothetical geographic planning scenario; no operational feasibility has been verified.",
                f"Walking speed {walking_speed_kmh:g} km/h; coverage threshold {coverage_minutes:g} minutes; includes settlement-to-road connections.",
                "Population-weighted greedy maximum coverage over mapped road nodes; baseline includes mapped facilities and their road connections.",
                "Coverage geometry shows reachable road segments, not an isochrone polygon or proven off-road accessibility.",
                "Unknown population contributes no numerical weight; unknown accessibility remains unknown unless a network path to an outreach point exists.",
                "Review road usability, clinical capacity, safe stopping space, local consent, staffing, permissions and existing outreach before any action.",
            ] + ([f"Manually selected location snapped {manual_snap:.1f} metres to the nearest mapped road node; zero incremental coverage is retained honestly."] if manual_node is not None else []),
        }
