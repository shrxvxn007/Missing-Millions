"""Settlement-registry matching and candidate-gap classification.

A candidate's gap type is a descriptive, evidence-linked category, never proof
of actual unmet healthcare need:

    mapping_gap   — habitation signal not confidently represented in the
                    selected settlement registry.
    access_gap    — a potentially long journey to a mapped facility offering
                    the selected service.
    combined_gap  — both mapping and access gaps may be present.
    none          — matched, and within the demonstrated travel-time band.

Match ambiguity is preserved as evidence rather than hidden.
"""
from __future__ import annotations

from typing import Any

import numpy as np
from pyproj import Transformer
from scipy.spatial import cKDTree

MATCH_RADIUS_M_DEFAULT = 400        # confident registered-settlement match
CONFIDENCE_RADIUS_M_DEFAULT = 900   # partial/equivocal representation band

GAP_TYPES = ("mapping_gap", "access_gap", "combined_gap", "none", "undetermined")
MATCH_STATUSES = ("matched", "unmatched", "ambiguous", "no_registry")


def _package_crs(package: dict) -> str:
    """The package metric CRS, or a local UTM guess for lightweight fixtures.

    Prepared packages always carry `region.metric_crs`; API test fixtures may
    not, so the fallback derives a UTM zone from the AOI or first record.
    """
    region = package.get("region", {})
    if region.get("metric_crs"):
        return region["metric_crs"]
    from pipeline.geospatial.grid import local_metric_crs
    point = (region.get("center") or package.get("region", {}).get("bbox"))
    if not point and package.get("settlements"):
        point = package["settlements"][0].get("centroid")
    if point and len(point) >= 2 and isinstance(point[0], (int, float)):
        return local_metric_crs(float(point[0]), float(point[1]))
    raise ValueError("Package provides no metric CRS and no coordinates to derive one")


def registry_xy(registry_features: list[dict], target_crs: str) -> tuple[np.ndarray, np.ndarray, Transformer]:
    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    if not registry_features:
        return np.empty((0, 2)), np.empty(0, dtype=int), transformer
    points = np.array([transformer.transform(*feature["geometry"]["coordinates"]) for feature in registry_features])
    return points, np.arange(len(registry_features)), transformer


def match_settlements_to_registry(
    settlements: list[dict],
    registry: dict,
    target_crs: str,
    *,
    match_radius_m: float = MATCH_RADIUS_M_DEFAULT,
    confidence_radius_m: float = CONFIDENCE_RADIUS_M_DEFAULT,
) -> dict:
    """Attach registry-representation evidence to every candidate.

    status:
        matched    — a mapped settlement lies within match_radius_m.
        ambiguous  — the nearest mapped settlement sits between the radii;
                     representation is equivocal, not excluded.
        unmatched  — no mapped settlement within confidence_radius_m.
        no_registry— the registry layer is unavailable or empty.

    Matching uses the registry nearest to the candidate's centroid and retains
    all mapped settlements inside the confidence radius for transparency.
    """
    features = registry.get("features", []) if isinstance(registry, dict) else []
    xy, indices, _ = registry_xy(features, target_crs)
    statistics: dict[str, int] = {status: 0 for status in MATCH_STATUSES}
    if len(xy) == 0:
        for settlement in settlements:
            settlement["record_match_status"] = "no_registry"
            settlement["nearest_registry_name"] = None
            settlement["nearest_registry_place"] = None
            settlement["nearest_registry_distance_m"] = None
            settlement["registry_record_ids"] = []
            statistics["no_registry"] += 1
        return {"status": "no_registry", "distances": statistics,
                "match_radius_m": match_radius_m, "confidence_radius_m": confidence_radius_m,
                "registry_record_count": 0,
                "interpretation": "The chosen settlement registry is unavailable or contains no records for this AOI; mapping-gap classification cannot be performed and travel-time evidence alone is reported."}
    tree = cKDTree(xy)
    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    for settlement in settlements:
        point = np.array(transformer.transform(*settlement["centroid"]))
        distance, index = tree.query(point)
        near = tree.query_ball_point(point, confidence_radius_m)
        matches = sorted(
            (_registry_record(features[i], float(np.linalg.norm(xy[i] - point))) for i in near),
            key=lambda record: record["distance_m"],
        )
        nearest_distance = float(distance)
        if nearest_distance <= match_radius_m:
            status = "matched"
        elif nearest_distance <= confidence_radius_m:
            status = "ambiguous"
        else:
            status = "unmatched"
        settlement["record_match_status"] = status
        settlement["nearest_registry_name"] = features[int(index)]["properties"].get("name")
        settlement["nearest_registry_place"] = features[int(index)]["properties"].get("place")
        settlement["nearest_registry_distance_m"] = round(nearest_distance, 1)
        settlement["registry_record_ids"] = [record["id"] for record in matches]
        settlement["registry_matches"] = matches
        statistics[status] += 1
    return {"status": "available", "distances": statistics,
            "match_radius_m": match_radius_m, "confidence_radius_m": confidence_radius_m,
            "registry_record_count": len(features),
            "interpretation": "Recorded-settlement proximity in the selected registry only; registry completeness was not verified and an unmatched candidate is not proof of an unknown settlement."}


def _registry_record(feature: dict, distance_m: float | None = None) -> dict:
    if isinstance(feature, str):
        raise TypeError("registry feature must be a dict, not a string")
    properties = feature.get("properties", {})
    return {"id": feature.get("id"), "name": properties.get("name"), "place": properties.get("place"),
            "distance_m": distance_m, "source": properties.get("source", "OpenStreetMap")}


def classify_candidate_gaps(settlements: list[dict], *, access_threshold_minutes: float = 60) -> dict:
    """Classify mapping/access/combined candidate gaps from computed evidence.

    Access classification is deliberately slow to accuse: unknown routing stays
    unknown rather than counting as an access gap.
    """
    statistics: dict[str, int] = {gap: 0 for gap in GAP_TYPES}
    for settlement in settlements:
        match_status = settlement.get("record_match_status", "no_registry")
        walking_time = settlement.get("walking_time_minutes")
        poor_access = walking_time is not None and walking_time > access_threshold_minutes
        unknown_access = walking_time is None or settlement.get("routing_status") != "routable"
        if match_status == "no_registry":
            gap = "undetermined"
        elif match_status in ("unmatched", "ambiguous") and poor_access:
            gap = "combined_gap"
        elif match_status in ("unmatched", "ambiguous"):
            gap = "mapping_gap"
        elif poor_access:
            gap = "access_gap"
        elif unknown_access:
            gap = "mapping_gap" if match_status in ("unmatched", "ambiguous") else "none"
        else:
            gap = "none"
        settlement["candidate_gap_type"] = gap
        settlement["gap_classification"] = {
            "access_threshold_minutes": access_threshold_minutes,
            "match_status": match_status,
            "access_state": ("unknown" if unknown_access else "over_threshold" if poor_access else "within_threshold"),
            "note": "Candidate gap categories structure investigation, not proven healthcare deprivation.",
        }
        statistics[gap] += 1
    return {"threshold_minutes": access_threshold_minutes, "classification_counts": statistics,
            "definitions": {
                "mapping_gap": "Habitation signal not confidently represented in the selected registry",
                "access_gap": "Represented settlement with a modelled journey beyond the demonstrated threshold",
                "combined_gap": "Both conditions may be present; priority for local verification",
                "none": "Registered and within the demonstrated travel-time band",
                "undetermined": "Registry unavailable; only access evidence is reported"},
            "note": "Thresholds are demonstration parameters, not health standards. Unknown access remains unknown."}


def registry_recall(package: dict, *, radius_m: float = 500) -> dict:
    """Evaluation metric: share of registry settlements recovered by detection.

    Withholding support: pass a registry with some recorded settlements removed
    to measure whether the satellite pipeline rediscovers intentionally
    omitted reference settlements. Only registry points inside the analysis
    extent count — the detection pipeline never evaluated the wider buffer.
    """
    settlements = package["settlements"]
    bbox = package.get("region", {}).get("bbox")
    features = package.get("registry", {}).get("features", [])
    if bbox:
        pad = .003  # roughly one analysis-cell diagonal in degrees at the equator
        inside = [feature for feature in features
                  if bbox[0] - pad <= feature["geometry"]["coordinates"][0] <= bbox[2] + pad
                  and bbox[1] - pad <= feature["geometry"]["coordinates"][1] <= bbox[3] + pad]
        features = inside
    if not features:
        return {"status": "no_registry", "recall": None, "recovered": 0, "registry_points": 0,
                "note": "No settlement registry available; recall evaluation requires a reference layer."}
    crs = _package_crs(package)
    xy, _, _ = registry_xy(features, crs)
    candidate_points = np.array([Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform(*s["centroid"]) for s in settlements])
    tree = cKDTree(candidate_points) if len(candidate_points) else None
    recovered, missed = [], []
    for index, feature in enumerate(features):
        if tree is None:
            missed.append(feature["properties"].get("name"))
            continue
        distance, candidate = tree.query(xy[index])
        if distance <= radius_m:
            recovered.append({"registry_id": feature.get("id"),
                              "name": feature["properties"].get("name"),
                              "distance_m": round(float(distance), 1),
                              "candidate_id": settlements[int(candidate)]["id"]})
        else:
            missed.append(feature["properties"].get("name"))
    recall = len(recovered) / len(features) if features else None
    return {"status": "available", "recall": round(recall, 4) if recall is not None else None,
            "recovered": len(recovered), "missed": len(missed), "registry_points": len(features),
            "radius_m": radius_m, "matches": recovered, "unrecovered_names": [name for name in missed if name],
            "interpretation": "Geometric recovery of registry points by satellite detection, not accuracy about need. Withheld evaluation requires removing reference points before this run and discarding the omission clearly."}
