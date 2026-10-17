"""Import optional facility registers without asserting completeness or verification.

Public functions:
    import_facilities(path, source_name=..., source_url=...) -> GeoJSON collection
    merge_facilities(*collections, projected_crs=None) -> GeoJSON collection

CSV requires lon, lat, name, category; source_id and source are optional.
GeoJSON accepts Point Features with equivalent properties. Specialist categories
such as pharmacy and dentist are excluded. Malformed coordinates fail explicitly.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .acquire_sources import deduplicate_facilities

CATEGORIES = {"hospital": "hospital", "clinic": "clinic", "doctor": "doctor",
              "doctors": "doctor", "health_post": "health_post", "healthpost": "health_post"}


def _coordinates(lon: Any, lat: Any, record: int) -> list[float]:
    try:
        coordinates = [float(lon), float(lat)]
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Facility record {record}: lon/lat must be numeric") from exc
    if not all(math.isfinite(value) for value in coordinates) or not (-180 <= coordinates[0] <= 180 and -90 <= coordinates[1] <= 90):
        raise ValueError(f"Facility record {record}: coordinates must be finite WGS84 lon/lat")
    return coordinates


def _metric_crs(features: list[dict]) -> str:
    if not features:
        return "EPSG:32636"
    lon, lat = features[0]["geometry"]["coordinates"]
    if not -80 <= lat <= 84:
        raise ValueError("Specify a suitable projected CRS for a polar facility list")
    zone = min(60, int((lon + 180) // 6) + 1)
    return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"


def import_facilities(path: str | Path, *, source_name: str = "Imported facility list",
                      source_url: str | None = None, projected_crs: str | None = None) -> dict:
    path = Path(path)
    imported_at = datetime.now(timezone.utc).isoformat()
    upstream_provenance = []
    source_license = "Must be supplied/checked for the imported source; no license is inferred"
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required = {"lon", "lat", "name", "category"}
            if not required.issubset(set(reader.fieldnames or [])):
                raise ValueError("Facility CSV requires lon, lat, name and category columns")
            rows = [(row, _coordinates(row["lon"], row["lat"], index)) for index, row in enumerate(reader, 1)]
    elif path.suffix.lower() in {".json", ".geojson"}:
        document = json.loads(path.read_text())
        metadata = document.get("provenance", [])
        upstream_provenance = metadata if isinstance(metadata, list) else [metadata]
        source_license = document.get("license") or source_license
        if document.get("type") == "Feature":
            document = {"type": "FeatureCollection", "features": [document]}
        if document.get("type") != "FeatureCollection":
            raise ValueError("Facility GeoJSON must be a Feature or FeatureCollection")
        rows = []
        for index, feature in enumerate(document.get("features", []), 1):
            geometry = feature.get("geometry") or {}
            point = geometry.get("coordinates", [])
            if geometry.get("type") != "Point" or len(point) < 2:
                raise ValueError(f"Facility record {index}: GeoJSON geometry must be a WGS84 Point")
            properties = dict(feature.get("properties") or {})
            if feature.get("id") is not None:
                properties.setdefault("source_id", str(feature["id"]))
            rows.append((properties, _coordinates(point[0], point[1], index)))
    else:
        raise ValueError("Facility import supports .csv, .json and .geojson")
    features, excluded = [], []
    for index, (properties, point) in enumerate(rows, 1):
        category = str(properties.get("category") or properties.get("healthcare") or properties.get("amenity") or "").strip().casefold().replace("-", "_").replace(" ", "_")
        if category not in CATEGORIES:
            excluded.append({"record": index, "category": category, "reason": "outside default general-healthcare scope"})
            continue
        name = str(properties.get("name") or "Unnamed mapped facility").strip()
        source = str(properties.get("source") or source_name)
        generated = hashlib.sha256(json.dumps([source, name, category, point], sort_keys=True).encode()).hexdigest()[:16]
        source_id = str(properties.get("source_id") or generated)
        identity = f"import:{source}:{source_id}"
        source_record = {"source": source, "source_id": source_id, "source_url": source_url or properties.get("source_url"),
                         "imported_at": imported_at, "input_file": path.name}
        features.append({"type": "Feature", "id": identity, "geometry": {"type": "Point", "coordinates": point},
                         "properties": {**properties, "id": identity, "source": source, "source_id": source_id,
                                        "name": name, "category": CATEGORIES[category],
                                        "verification_status": "unverified", "source_records": [source_record]}})
    features = deduplicate_facilities(features, projected_crs or _metric_crs(features))
    provenance = {"dataset": source_name, "source_url": source_url, "kind": "mapped", "input_file": path.name,
                  "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "imported_at": imported_at,
                  "input_records": len(rows), "retained_facilities": len(features), "excluded_records": excluded,
                  "license": source_license,
                  "limitations": ["Import does not establish that records are verified, current, complete or suitable for a particular service.",
                                  "Same normalized non-empty names within 100 m are reconciled; original source records are retained."]}
    return {"type": "FeatureCollection", "features": features, "provenance": [*upstream_provenance, provenance]}


def merge_facilities(*collections: dict, projected_crs: str | None = None) -> dict:
    """Reconcile OSM and optional imports while preserving source-level metadata."""
    features, provenance = [], []
    for collection in collections:
        if collection.get("type") != "FeatureCollection":
            raise ValueError("Each facility input must be a GeoJSON FeatureCollection")
        metadata = collection.get("provenance", [])
        provenance.extend(metadata if isinstance(metadata, list) else [metadata])
        for feature in collection.get("features", []):
            item = json.loads(json.dumps(feature))
            geometry = item.get("geometry") or {}
            if geometry.get("type") != "Point":
                raise ValueError("Facility merge requires Point geometry")
            if len(geometry.get("coordinates", [])) < 2:
                raise ValueError("Facility merge requires finite WGS84 lon/lat coordinates")
            geometry["coordinates"] = _coordinates(*geometry["coordinates"][:2], record=len(features) + 1)
            properties = item.setdefault("properties", {})
            properties.setdefault("source_records", [{"source": properties.get("source", "OpenStreetMap" if properties.get("osm_id") else "Existing source"),
                                                      "source_id": properties.get("osm_id") or properties.get("source_id") or item.get("id")}])
            features.append(item)
    return {"type": "FeatureCollection", "features": deduplicate_facilities(features, projected_crs or _metric_crs(features)),
            "provenance": provenance}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-name", default="Imported facility list")
    parser.add_argument("--source-url")
    parser.add_argument("--merge-osm", type=Path, help="Existing OSM facility GeoJSON; no source file is modified")
    parser.add_argument("--crs", help="Metric CRS for 100 m duplicate reconciliation; local UTM inferred if omitted")
    args = parser.parse_args()
    result = import_facilities(args.input, source_name=args.source_name, source_url=args.source_url, projected_crs=args.crs)
    if args.merge_osm:
        result = merge_facilities(json.loads(args.merge_osm.read_text()), result, projected_crs=args.crs)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(f"Imported {len(result['features'])} facility records → {args.output}; no verification is inferred")


if __name__ == "__main__":
    main()
