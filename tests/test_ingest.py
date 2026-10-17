"""Source adapter invariants: identities, topology, count conservation and honesty."""
from argparse import Namespace
import json

import numpy as np
from pyproj import Transformer
import pytest
import rasterio
from rasterio.transform import from_origin

from pipeline.ingest import acquire_sources as ingest
from pipeline.ingest.facilities import import_facilities, merge_facilities


def facility(identity, name, lon=34.18, lat=1.08):
    return {"type": "Feature", "id": identity,
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"name": name, "osm_id": identity}}


def grid():
    inverse = Transformer.from_crs(32636, 4326, always_xy=True)
    lower = inverse.transform(628750, 117000)
    upper = inverse.transform(633750, 122000)
    return {"crs": "EPSG:32636", "west": 628750, "north": 122000,
            "width": 20, "height": 20, "cell_size_m": 250,
            "bbox": [*lower, *upper]}


def test_physical_facility_duplicates_preserve_all_source_ids():
    features = [facility("node/1", "Test Clinic"),
                facility("way/2", "TEST  CLINIC", 34.1801)]
    result = ingest.deduplicate_facilities(features)
    assert len(result) == 1
    assert set(result[0]["properties"]["merged_source_ids"]) == {"node/1", "way/2"}
    assert "merged_source_ids" not in features[0]["properties"]


def test_distinct_nearby_and_distant_same_name_facilities_survive():
    features = [facility("node/1", "Clinic A"),
                facility("node/2", "Clinic B", 34.1801),
                facility("node/3", "Clinic A", 34.19),
                facility("node/4", "Unnamed mapped facility", 34.1801),
                facility("node/5", "Unnamed mapped facility", 34.1802)]
    assert len(ingest.deduplicate_facilities(features)) == 5


def test_osm_import_preserves_shared_node_topology_and_healthcare_scope(tmp_path, monkeypatch):
    raw = {"osm3s": {"timestamp_osm_base": "2026-06-01T00:00:00Z"}, "elements": [
        {"type": "way", "id": 10, "nodes": [1, 2], "tags": {"highway": "footway"},
         "geometry": [{"lon": 34.18, "lat": 1.08}, {"lon": 34.181, "lat": 1.08}]},
        {"type": "way", "id": 11, "nodes": [2, 3], "tags": {"highway": "residential"},
         "geometry": [{"lon": 34.181, "lat": 1.08}, {"lon": 34.182, "lat": 1.08}]},
        {"type": "node", "id": 100, "lon": 34.18, "lat": 1.08,
         "tags": {"amenity": "clinic", "healthcare": "clinic", "name": "Health Centre"}},
        {"type": "node", "id": 101, "lon": 34.18, "lat": 1.08, "tags": {"amenity": "pharmacy"}},
        {"type": "node", "id": 102, "lon": 34.18, "lat": 1.08, "tags": {"healthcare": "dentist"}},
    ]}
    monkeypatch.setattr(ingest, "request_json", lambda *a, **k: raw)
    report = ingest.acquire_osm(Namespace(out=tmp_path, overpass="https://example.invalid", buffer_m=20000), grid())
    graph = json.loads((tmp_path / "graph.json").read_text())
    assert len(graph["nodes"]) == 3
    assert len(graph["edges"]) == 2
    assert graph["edges"][0]["target"] == graph["edges"][1]["source"] == "2"
    assert 100 < graph["edges"][0]["length_m"] < 120
    assert not graph["directed"]
    assert report["facility_objects"] == 1
    assert report["vintage"] == raw["osm3s"]["timestamp_osm_base"]
    # Inspect the source request policy as well as the imported graph.
    assert "[foot!=no]" in report["query"] and "[access!=private]" in report["query"]
    assert "motorway|motorway_link|construction|proposed" in report["query"]
    project = Transformer.from_crs(4326, 32636, always_xy=True)
    west, south = project.transform(report["bbox"][0], report["bbox"][1])
    assert west == pytest.approx(628750 - 20000, abs=.1)
    assert south == pytest.approx(117000 - 20000, abs=.1)


def test_population_pixels_are_counted_once_without_averaging(tmp_path, monkeypatch):
    source = tmp_path / "input.tif"
    values = np.arange(100, dtype="float32").reshape(10, 10)
    with rasterio.open(source, "w", driver="GTiff", height=10, width=10, count=1,
                       dtype="float32", crs="EPSG:4326", nodata=-99999,
                       transform=from_origin(34.17, 1.09, .002, .002)) as dst:
        dst.write(values, 1)
    monkeypatch.setattr(ingest, "request_json", lambda _: {"assets": {"data": {"href": str(source)}}})
    report = ingest.acquire_population(Namespace(out=tmp_path), grid())
    population = np.load(tmp_path / "population.npz")["population"]
    assert population.shape == (20, 20)
    assert np.nansum(population) == report["selected_native_pixel_sum"] == 4500
    assert report["aggregated_grid_sum"] == 4500
    assert np.isnan(population).any()  # Unsupported cells are not invented zero population.


def test_inventory_never_silently_replaces_missing_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(ingest.urllib.request, "urlopen", lambda *a, **k: pytest.fail("Inventory must stay offline"))
    report = ingest.inventory(tmp_path)
    assert not report["complete"]
    assert report["source_mode"] == "real"
    assert {value["status"] for value in report["sources"].values()} == {"not_acquired"}
    assert not list(tmp_path.iterdir())


def test_optional_csv_import_excludes_specialists_and_preserves_register_identity(tmp_path):
    path = tmp_path / "register.csv"
    path.write_text("lon,lat,name,category,source_id,source\n"
                    "34.18,1.08,Local Centre,clinic,H001,Example register\n"
                    "34.1801,1.08,LOCAL CENTRE,clinic,H002,Example register\n"
                    "34.18,1.08,Dispensary,pharmacy,P001,Example register\n"
                    "34.18,1.08,Dental practice,dentist,D001,Example register\n")
    result = import_facilities(path, source_name="Provided register", source_url="https://example.invalid/register")
    assert len(result["features"]) == 1
    properties = result["features"][0]["properties"]
    assert properties["verification_status"] == "unverified"
    assert {record["source_id"] for record in properties["source_records"]} == {"H001", "H002"}
    assert all(record["source_url"] == "https://example.invalid/register" for record in properties["source_records"])
    assert len(result["provenance"][0]["excluded_records"]) == 2
    assert len(result["provenance"][0]["input_sha256"]) == 64


@pytest.mark.parametrize("lon,lat", [(181, 1), (34, 91), ("nan", 1), (34, "inf"), ("invalid", 1)])
def test_facility_register_rejects_invalid_wgs84_coordinates(tmp_path, lon, lat):
    path = tmp_path / "invalid.csv"
    path.write_text(f"lon,lat,name,category\n{lon},{lat},Clinic,clinic\n")
    with pytest.raises(ValueError, match="record 1"):
        import_facilities(path)


def test_geojson_register_and_osm_merge_retains_both_provenance_records(tmp_path):
    path = tmp_path / "register.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "id": "register-1", "geometry": {"type": "Point", "coordinates": [34.1801, 1.08]},
         "properties": {"name": "Test Clinic", "category": "clinic", "source": "Provided register"}}
    ]}))
    imported = import_facilities(path, source_url="https://example.invalid/register")
    osm = {"type": "FeatureCollection", "features": [facility("node/1", "TEST CLINIC")]}
    merged = merge_facilities(osm, imported)
    assert len(merged["features"]) == 1
    properties = merged["features"][0]["properties"]
    assert "node/1" in properties["merged_source_ids"]
    assert any(record["source_id"] == "register-1" for record in properties["source_records"])
    assert any(record["source_id"] == "node/1" for record in properties["source_records"])
    assert merged["provenance"][0]["source_url"] == "https://example.invalid/register"
    assert "source_records" not in osm["features"][0]["properties"]


def test_import_preserves_upstream_collection_provenance_and_license(tmp_path):
    path = tmp_path / "register.geojson"
    upstream = {"producer": "Example source", "vintage": "2024", "license": "Example source terms"}
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [],
                                "license": "Example source terms", "provenance": [upstream]}))
    imported = import_facilities(path)
    assert imported["provenance"][0] == upstream
    assert imported["provenance"][1]["license"] == "Example source terms"


def test_duplicate_reconciliation_refuses_degrees_as_metres():
    with pytest.raises(ValueError, match="projected CRS in metres"):
        ingest.deduplicate_facilities([facility("node/1", "Clinic")], "EPSG:4326")
