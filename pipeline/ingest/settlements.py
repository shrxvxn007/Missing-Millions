"""Import a mapped-settlement registry without asserting completeness.

Public functions:
    extract_settlements(osm_raw) -> GeoJSON collection of OSM place=* records
    import_registry(path, source_name=...) -> GeoJSON collection
    merge_registries(*collections, projected_crs=None) -> GeoJSON collection

The registry is the reference layer used for candidate matching. It is a
volunteer/imported record: absence here is never proof a settlement is unknown,
unoccupied or undeserved. CSV requires lon, lat, name; place and population are
optional. Malformed coordinates fail explicitly.
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

PLACE_RANK = {"city": 1, "town": 2, "suburb": 3, "village": 4,
              "neighbourhood": 5, "hamlet": 6, "isolated_dwelling": 7, "farm": 8}


def extract_settlements(osm_raw: dict) -> dict:
    """Point registry of mapped settlements (OSM place=* records).

    Nodes use their coordinates; ways/relations use their geometry centroid
    with the original element ID retained for traceability.
    """
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
        features.append({"type": "Feature", "id": identity,
                         "geometry": {"type": "Point", "coordinates": center},
                         "properties": {"id": identity, "osm_id": identity, "source": "OpenStreetMap",
                                        "name": tags.get("name", "Unnamed mapped settlement"),
                                        "place": place, "place_rank": PLACE_RANK[place],
                                        "population": tags.get("population"),
                                        "registry_tags": {key: tags[key] for key in sorted(tags) if key != "place"}}})
    features.sort(key=lambda feature: (feature["properties"]["place_rank"], str(feature["properties"]["name"])))
    return {"type": "FeatureCollection", "features": features,
            "provenance": {"dataset": "OSM mapped settlement registry (place=*)", "kind": "mapped",
                           "registry_element_count": len(features),
                           "limitations": ["Volunteer-mapped reference; completeness is not guaranteed or verified.",
                                           "Absence from this registry is not evidence a settlement is unknown or unoccupied."]}}


def _coordinates(lon: Any, lat: Any, record: int) -> list[float]:
    try:
        coordinates = [float(lon), float(lat)]
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Settlement record {record}: lon/lat must be numeric") from exc
    if not all(math.isfinite(value) for value in coordinates) or not (-180 <= coordinates[0] <= 180 and -90 <= coordinates[1] <= 90):
        raise ValueError(f"Settlement record {record}: coordinates must be finite WGS84 lon/lat")
    return coordinates


def import_registry(path: str | Path, *, source_name: str = "Imported settlement registry",
                    source_url: str | None = None) -> dict:
    path = Path(path)
    imported_at = datetime.now(timezone.utc).isoformat()
    source_license = "Must be supplied/checked for the imported source; no license is inferred"
    upstream_provenance = []
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not {"lon", "lat", "name"}.issubset({(field or "").strip() for field in (reader.fieldnames or [])}):
                raise ValueError("Settlement registry CSV requires lon, lat and name columns")
            rows = [(row, _coordinates(row["lon"], row["lat"], index)) for index, row in enumerate(reader, 1)]
    elif path.suffix.lower() in {".json", ".geojson"}:
        document = json.loads(path.read_text())
        metadata = document.get("provenance", [])
        upstream_provenance = metadata if isinstance(metadata, list) else [metadata]
        source_license = document.get("license") or source_license
        if document.get("type") == "Feature":
            document = {"type": "FeatureCollection", "features": [document]}
        if document.get("type") != "FeatureCollection":
            raise ValueError("Settlement registry GeoJSON must be a Feature or FeatureCollection")
        rows = []
        for index, feature in enumerate(document.get("features", []), 1):
            geometry = feature.get("geometry") or {}
            point = geometry.get("coordinates", [])
            if geometry.get("type") != "Point" or len(point) < 2:
                raise ValueError(f"Settlement record {index}: GeoJSON geometry must be a WGS84 Point")
            rows.append((dict(feature.get("properties") or {}), _coordinates(point[0], point[1], index)))
    else:
        raise ValueError("Settlement registry import supports .csv, .json and .geojson")
    features, excluded = [], []
    for index, (properties, point) in enumerate(rows, 1):
        place = str(properties.get("place") or "village").strip().casefold().replace("-", "_").replace(" ", "_")
        if place not in PLACE_RANK:
            excluded.append({"record": index, "place": place, "reason": "place category outside the settlement registry scope"})
            continue
        name = str(properties.get("name") or "Unnamed mapped settlement").strip()
        source = str(properties.get("source") or source_name)
        generated = hashlib.sha256(json.dumps([source, name, point], sort_keys=True).encode()).hexdigest()[:16]
        source_id = str(properties.get("source_id") or properties.get("osm_id") or generated)
        identity = f"registry:{source}:{source_id}"
        features.append({"type": "Feature", "id": identity, "geometry": {"type": "Point", "coordinates": point},
                         "properties": {**properties, "id": identity, "source": source, "source_id": source_id,
                                        "name": name, "place": place, "place_rank": PLACE_RANK[place],
                                        "verification_status": "unverified"}})
    features = deduplicate_facilities(features, _metric_crs(features))
    provenance = {"dataset": source_name, "source_url": source_url, "kind": "mapped", "input_file": path.name,
                  "input_sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "imported_at": imported_at,
                  "input_records": len(rows), "retained_records": len(features), "excluded_records": excluded,
                  "license": source_license,
                  "limitations": ["Import does not claim the registry is verified, current or complete.",
                                  "Same normalized non-empty names within 100 m are reconciled; original ids are retained.",
                                  "Absence from a registry is not evidence a settlement is unknown."]}
    return {"type": "FeatureCollection", "features": features, "provenance": [*upstream_provenance, provenance]}


def merge_registries(*collections: dict, projected_crs: str | None = None) -> dict:
    """Combine multiple registry sources, preserving per-record source metadata."""
    features, provenance = [], []
    for collection in collections:
        if collection.get("type") != "FeatureCollection":
            raise ValueError("Each settlement registry input must be a GeoJSON FeatureCollection")
        metadata = collection.get("provenance", [])
        provenance.extend(metadata if isinstance(metadata, list) else [metadata])
        for feature in collection.get("features", []):
            item = json.loads(json.dumps(feature))
            geometry = item.get("geometry") or {}
            if geometry.get("type") != "Point":
                raise ValueError("Settlement registry merge requires Point geometry")
            geometry["coordinates"] = _coordinates(*geometry["coordinates"][:2], record=len(features) + 1)
            properties = item.setdefault("properties", {})
            properties.setdefault("source", "OpenStreetMap" if properties.get("osm_id") else "Existing source")
            features.append(item)
    return {"type": "FeatureCollection", "features": deduplicate_facilities(features, projected_crs or _metric_crs(features)),
            "provenance": provenance}


def _metric_crs(features: list[dict]) -> str:
    if not features:
        return "EPSG:32636"
    lon, lat = features[0]["geometry"]["coordinates"]
    if not -80 <= lat <= 84:
        raise ValueError("Specify a suitable projected CRS for a polar settlement registry")
    zone = min(60, int((lon + 180) // 6) + 1)
    return f"EPSG:{32600 + zone if lat >= 0 else 32700 + zone}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", type=Path, help="osm.json Overpass response or registry CSV/GeoJSON")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-name", default="Imported settlement registry")
    parser.add_argument("--source-url")
    parser.add_argument("--merge-osm", type=Path, help="Existing OSM-derived registry GeoJSON; no source file is modified")
    args = parser.parse_args()
    if args.input is None:
        raise SystemExit("Provide an osm.json path or an imported registry file")
    if args.input.suffix.lower() == ".json" and args.input.name == "osm.json":
        result = extract_settlements(json.loads(args.input.read_text()))
    else:
        result = import_registry(args.input, source_name=args.source_name, source_url=args.source_url)
    if args.merge_osm:
        result = merge_registries(result, json.loads(args.merge_osm.read_text()))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(f"Registry records: {len(result['features'])} → {args.output}; completeness is not implied")


if __name__ == "__main__":
    main()
