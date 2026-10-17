"""Read the precomputed package; perform only small cached graph calculations."""

from __future__ import annotations

import json
from pathlib import Path
from threading import RLock

from .routing import RoutingEngine, feature_collection


class DataRepository:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._stamp: int | None = None
        self._package: dict | None = None
        self._layers: dict | None = None
        self.engine: RoutingEngine | None = None
        self._extra_engine: RoutingEngine | None = None
        self._extra_engine_signature: tuple | None = None
        self._lock = RLock()

    def load(self) -> dict:
        with self._lock:
            return self._load()

    def _make_engine(self, package: dict, extra_facilities: list[dict] | None = None) -> RoutingEngine:
        facilities = package.get("facility_records") or package.get("facilities", [])
        if extra_facilities:
            from copy import deepcopy
            facilities = deepcopy(list(facilities)) + list(extra_facilities)
        return RoutingEngine(package.get("graph", {}), facilities,
                             max_snap_distance_m=package.get("configuration", {}).get("max_snap_distance_m", 1500))

    def engine_with(self, extra_facilities: list[dict]) -> RoutingEngine:
        """Routing engine including confirmed facilities, cached per facility set."""
        with self._lock:
            package = self._load()
            signature = tuple(sorted(
                (str(f["id"]), round(f["coordinates"][0], 6), round(f["coordinates"][1], 6))
                for f in extra_facilities))
            if self._extra_engine is None or self._extra_engine_signature != signature:
                self._extra_engine = self._make_engine(package, extra_facilities)
                self._extra_engine_signature = signature
                self._extra_engine_routes = None
            return self._extra_engine

    def get_engine(self) -> RoutingEngine:
        """Build the large routing graph only when an interactive scenario needs it."""
        with self._lock:
            package = self._load()
            if self.engine is None:
                self.engine = self._make_engine(package)
            return self.engine

    def _load(self) -> dict:
        stamp = self.path.stat().st_mtime_ns
        if self._package is not None and stamp == self._stamp:
            return self._package
        package = json.loads(self.path.read_text())
        if not isinstance(package, dict) or not isinstance(package.get("settlements"), list):
            raise ValueError("A processed package must contain a settlement list")
        self.engine, self._layers = None, None
        self._extra_engine, self._extra_engine_signature = None, None
        settlements = package["settlements"]
        ready = all(s.get("routing_status") not in (None, "not_computed")
                    and all(key in s for key in ("walking_time_minutes", "priority_score", "priority_components", "anomaly_score", "anomaly_status"))
                    for s in settlements)
        if not ready:
            # Small development fixtures can omit precomputation. Genuine
            # processed packages already carry these scientific outputs and
            # should never train models or load 240k road nodes for an overview.
            self.engine = self._make_engine(package)
            self.engine.enrich(settlements)
            from pipeline.ml.analysis import recompute_analysis
            result = recompute_analysis(settlements)
            if isinstance(result, list):
                settlements = result
            elif isinstance(result, dict):
                package["model_metadata"] = result
                package.setdefault("manifest", {}).update(result)
        package["settlements"] = settlements
        for settlement in settlements:
            settlement.setdefault("verification_status", "unverified")
            settlement.setdefault("route_geometry", None)
            settlement.setdefault("walking_speed_kmh", 4.2)
            time = settlement.get("walking_time_minutes")
            settlement.setdefault("travel_time_band", "unknown" if time is None else "under_30" if time < 30 else "30_60" if time < 60 else "60_120" if time < 120 else "over_120")
            distance = settlement.get("walking_route_distance_m")
            settlement.setdefault("walking_time_sensitivity", {
                "slow_3_kmh": round(RoutingEngine.minutes(distance, 3), 1) if distance is not None else None,
                "baseline_4_2_kmh": round(RoutingEngine.minutes(distance, 4.2), 1) if distance is not None else None,
                "fast_5_kmh": round(RoutingEngine.minutes(distance, 5), 1) if distance is not None else None,
            })
        package.setdefault("manifest", {})
        self._package, self._stamp = package, stamp
        return package

    def access_profile(self, settlement: dict) -> dict:
        """Walk-time distribution across one candidate's analysis cells.

        Prepared packages carry the profile precomputed at package build time,
        so the evidence panel is served instantly and the large routing engine
        is never built for read-only views. Small development fixtures without
        a precomputed profile fall back to a live engine computation.
        """
        precomputed = settlement.get("access_profile")
        if isinstance(precomputed, dict):
            profile = dict(precomputed)
            profile["walking_time_minutes_centroid"] = settlement.get("walking_time_minutes")
            profile["method"] = "Snap-to-network + network-to-nearest-mapped-facility walk time for every analysis cell; 4.2 km/h baseline. Precomputed at package build time. Representative distributions, not occupancy evidence."
            return profile
        package = self._load()
        centroids, seen = [], set()
        for feature in package.get("cells", {}).get("features", []):
            if feature.get("properties", {}).get("cluster_id") != settlement["id"]:
                continue
            key = feature.get("id")
            if key in seen:
                continue
            seen.add(key)
            geometry = feature.get("geometry") or {}
            if geometry.get("type") == "Polygon":
                centroid = self._polygon_centroid(geometry["coordinates"][0])
                if centroid:
                    centroids.append(centroid)
        engine = self.get_engine()
        profile = engine.access_profile(centroids)
        profile["walking_time_minutes_centroid"] = settlement.get("walking_time_minutes")
        profile["method"] = "Snap-to-network + network-to-nearest-mapped-facility walk time for every analysis cell; 4.2 km/h baseline. Representative distributions, not occupancy evidence."
        return profile

    @staticmethod
    def _polygon_centroid(ring: list) -> list[float] | None:
        if not ring:
            return None
        count = len(ring)
        closed = count > 1 and ring[0] == ring[-1]
        points = ring[:-1] if closed else ring
        if not points:
            return None
        lon = sum(p[0] for p in points) / len(points)
        lat = sum(p[1] for p in points) / len(points)
        return [lon, lat]

    @staticmethod
    def region(package: dict) -> dict:
        return package.get("region", {"id": "mbale-demo", "name": "Mbale demonstration region"})

    def invalidate_layers(self) -> None:
        """Drop the cached layer snapshot so review overlays appear on the map."""
        self._layers = None

    def overview(self, package: dict) -> dict:
        settlements = package["settlements"]
        facilities = package.get("facility_records")
        if facilities is None:
            fc = package.get("facilities", [])
            facilities = fc.get("features", []) if isinstance(fc, dict) else fc
        populations = [s.get("population_estimate") for s in settlements if s.get("population_estimate") is not None]
        priority = [s for s in settlements if (s.get("priority_score") or 0) >= 65]
        routable = [s for s in settlements if s.get("walking_time_minutes") is not None]
        gap_counts: dict[str, int] = {}
        for settlement in settlements:
            gap = settlement.get("candidate_gap_type", "undetermined")
            gap_counts[gap] = gap_counts.get(gap, 0) + 1
        registry = package.get("registry") or {}
        registry_count = len(registry.get("features", [])) if isinstance(registry, dict) else 0
        registry_section = package.get("manifest", {}).get("settlement_registry", {})
        recall = package.get("manifest", {}).get("settlement_registry_recall", {})
        matching = registry_section.get("matching", {})
        years = sorted({str(year) for s in settlements for year in s.get("building_count_by_year", {})})
        totals = {year: round(sum(float(s.get("building_count_by_year", {}).get(year) or 0) for s in settlements), 1) for year in years}
        return {
            "region": self.region(package),
            "summary": {
                **package.get("summary", {}),
                "candidate_count": len(settlements),
                "population_estimate": round(sum(populations)) if populations else None,
                "facility_count": len(facilities), "priority_count": len(priority),
                "priority_population": round(sum(s.get("population_estimate") or 0 for s in priority)),
                "routable_count": len(routable), "unknown_access_count": len(settlements) - len(routable),
                "gap_type_counts": gap_counts, "registry_record_count": registry_count,
                "registry_in_extent_recall": recall.get("recall"),
                "registry_recall_points": recall.get("registry_points"),
                "registry_match_statuses": matching.get("distances", {}),
                "sparse_signal_count": sum(1 for s in settlements if s.get("building_signal_strength") == "sparse_retained_for_review"),
                "reviewed_count": sum(1 for s in settlements if s.get("review_label")),
                "population_over_60_minutes": round(sum(s.get("population_estimate") or 0 for s in routable if s["walking_time_minutes"] > 60)),
                "building_count_by_year": totals,
                "building_count_change": round(totals[years[-1]] - totals[years[0]], 1) if len(years) > 1 else None,
                "priority_threshold": 65,
            },
            "manifest": package["manifest"],
        }

    def layers(self, package: dict) -> dict:
        if package is self._package and self._layers is not None:
            return self._layers
        # Prepared layers are immutable in request handling. Sharing geometry
        # objects avoids copying a whole buffered OSM extract per request.
        layers = dict(package.get("layers", {}))
        registry = package.get("registry")
        if isinstance(registry, dict) and registry.get("type") == "FeatureCollection":
            layers["registry"] = registry
        else:
            layers["registry"] = feature_collection([])
        layers["settlements"] = feature_collection([
            {"type": "Feature", "id": s["id"], "geometry": s["geometry"],
             "properties": {k: v for k, v in s.items() if k not in {"geometry", "route_geometry"}}}
            for s in package["settlements"]
        ])
        for key in ("facilities", "roads", "cells"):
            value = layers.get(key, package.get(key))
            if isinstance(value, dict) and value.get("type") == "FeatureCollection":
                layers[key] = value
            elif key == "facilities":
                records = package.get("facility_records", value if isinstance(value, list) else [])
                layers[key] = feature_collection([
                    {"type": "Feature", "geometry": {"type": "Point", "coordinates": f["coordinates"]},
                     "properties": {k: v for k, v in f.items() if k != "coordinates"}} for f in records
                ])
            elif key == "roads":
                layers[key] = feature_collection([
                    {"type": "Feature", "geometry": edge["geometry"],
                     "properties": {"length_m": edge.get("length_m")}} for edge in package.get("graph", {}).get("edges", [])
                    if edge.get("geometry")
                ])
            else:
                layers[key] = feature_collection([])
        layers["routes"] = feature_collection([
            {"type": "Feature", "geometry": s["route_geometry"], "properties": {"settlement_id": s["id"]}}
            for s in package["settlements"] if s.get("route_geometry")
        ])
        if package is self._package:
            self._layers = layers
        return layers
