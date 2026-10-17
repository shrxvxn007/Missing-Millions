"""Tier-1/2 additions: per-candidate access profiles, regional comparison, blind test."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from services.api.main import create_app


def build_fixture(tmp_path, *, with_cells=True, with_registry=True):
    region_id = "mbale-demo"
    coords = [(34.150 + i * .01, 1.07) for i in range(3)]
    settlements = []
    for i, (lon, lat) in enumerate(coords):
        settlements.append({
            "id": f"settlement-{i}", "region_id": region_id, "display_name": f"Candidate {i + 1}",
            "centroid": [lon, lat],
            "geometry": {"type": "Polygon", "coordinates": [[[lon - .001, 1.069], [lon + .001, 1.069],
                                                            [lon + .001, 1.071], [lon - .001, 1.071],
                                                            [lon - .001, 1.069]]]},
            "building_count_by_year": {"2016": 30 + i * 10, "2023": 50 + i * 20},
            "population_estimate": 100 + 100 * i, "population_reference_year": 2023,
            "building_density": 100, "road_density": 1, "osm_building_discrepancy": None,
            "data_mode": "synthetic", "data_quality_flags": [],
        })
    fixture = {"region": {"id": region_id, "name": "Tier-2 test region", "data_mode": "synthetic",
                          "bbox": [34.14, 1.06, 34.20, 1.08]},
               "data_mode": "synthetic", "settlements": settlements,
               "facility_records": [{"id": "clinic-1", "name": "Test clinic", "coordinates": [34.15, 1.07], "category": "clinic"}],
               "graph": {"nodes": [{"id": str(i), "coordinates": list(c)} for i, c in enumerate(coords)],
                         "edges": [{"source": "0", "target": "1", "length_m": 1110},
                                   {"source": "1", "target": "2", "length_m": 1110}]},
               "manifest": {"data_mode": "synthetic", "limitations": ["Synthetic test fixture"]}}
    if with_cells:
        # Two analysis cells for settlement-0: one on the network, one far off it.
        fixture["cells"] = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": "cell-on", "geometry": {"type": "Polygon", "coordinates": [[
                [34.149, 1.0695], [34.1498, 1.0695], [34.1498, 1.0705], [34.149, 1.0705], [34.149, 1.0695]]]},
             "properties": {"cluster_id": "settlement-0", "cell_size_m": 250}},
            {"type": "Feature", "id": "cell-off", "geometry": {"type": "Polygon", "coordinates": [[
                [34.199, 1.0695], [34.1998, 1.0695], [34.1998, 1.0705], [34.199, 1.0705], [34.199, 1.0695]]]},
             "properties": {"cluster_id": "settlement-0", "cell_size_m": 250}},
        ]}
    if with_registry:
        fixture["registry"] = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "id": f"registry-{i}",
             "geometry": {"type": "Point", "coordinates": [34.150 + 0.008 * i, 1.075]},
             "properties": {"id": f"registry-{i}", "name": f"Village {i}", "place": "village",
                            "source": "OpenStreetMap", "osm_id": f"registry-{i}"}}
            for i in range(4)]}
    data_path = tmp_path / "demo.json"
    data_path.write_text(json.dumps(fixture))
    return data_path


@pytest.fixture
def client(tmp_path):
    data_path = build_fixture(tmp_path)
    with TestClient(create_app(data_path, tmp_path / "db.sqlite", tmp_path / "dist")) as instance:
        yield instance


def test_precomputed_access_profile_never_builds_the_engine(tmp_path, monkeypatch):
    """Evidence-panel views on prepared packages must not pay the graph build."""
    data_path = build_fixture(tmp_path)
    fixture = json.loads(data_path.read_text())
    # Make the package "complete" so DataRepository.load() performs no routing
    # work — the only engine trigger then would be the profile endpoint itself.
    for settlement in fixture["settlements"]:
        settlement.update(routing_status="routable", walking_time_minutes=10.0,
                          walking_route_distance_m=420.0, road_snap_distance=0.0,
                          priority_score=40.0, priority_components={}, anomaly_score=None,
                          anomaly_status="insufficient_samples")
    fixture["settlements"][0]["access_profile"] = {
        "cells_measured": 2, "cells_unknown": 1,
        "median_minutes": 12.0, "p90_minutes": 18.0, "max_minutes": 19.0,
        "histogram_minutes": [1, 1], "walking_speed_kmh": 4.2,
    }
    data_path.write_text(json.dumps(fixture))
    from services.api.data import DataRepository
    original = DataRepository._make_engine
    monkeypatch.setattr(DataRepository, "_make_engine",
                        lambda self, package: pytest.fail("Evidence panels must not build the routing engine when the profile is precomputed"))
    with TestClient(create_app(data_path, tmp_path / "db2.sqlite", tmp_path / "dist")) as client:
        profile = client.get("/api/settlements/settlement-0/access-profile").json()
        assert profile["cells_measured"] == 2
        assert profile["p90_minutes"] == 18.0
        assert profile["walking_time_minutes_centroid"] is not None
        assert "Precomputed at package build time" in profile["method"]
        # The outreach endpoint keeps its own lazy engine path for real scenarios.
        assert client.get("/api/regions/mbale-demo/overview").status_code == 200


def test_access_profile_measures_cells_and_keeps_unknown_cells_unknown(client):
    response = client.get("/api/settlements/settlement-0/access-profile")
    assert response.status_code == 200
    profile = response.json()
    # The on-network cell reaches node 0 (facility side); the off-network cell
    # sits far beyond the snap limit and must be counted unknown, not imputed.
    assert profile["cells_measured"] == 1
    assert profile["cells_unknown"] == 1
    assert 0 < profile["median_minutes"] <= 3
    assert profile["p90_minutes"] == profile["median_minutes"]
    assert profile["walking_time_minutes_centroid"] is not None
    assert "not occupancy evidence" in profile["method"]
    profile_2 = client.get("/api/settlements/settlement-2/access-profile").json()
    # A candidate without recorded analysis cells reports that instead of fake values.
    assert profile_2["cells_measured"] == 0 and profile_2["cells_unknown"] == 0
    assert "No analysis cells" in profile_2["note"]
    assert client.get("/api/settlements/unknown/access-profile").status_code == 404


def test_region_compare_reports_each_package_separately(client):
    response = client.get("/api/regions/compare")
    assert response.status_code == 200
    rows = response.json()["regions"]
    assert len(rows) == 1
    row = rows[0]
    assert row["region_id"] == "mbale-demo" and row["country"] is None
    assert row["candidate_count"] == 3
    assert row["median_walk_minutes"] is not None
    assert row["registry_record_count"] == 4
    assert row["gap_counts"] == {"undetermined": 3}
    assert "not a merged analysis" in response.json()["note"]


def test_blind_test_withholds_discloses_and_reports_recovers(client):
    response = client.get("/api/regions/mbale-demo/blind-test?withhold=2&radius_m=500")
    assert response.status_code == 200
    report = response.json()
    assert report["status"] == "available"
    assert report["withheld_count"] == 2
    assert len(report["withheld_ids"]) == 2
    assert "intentionally withheld FOR EVALUATION" in report["disclosure"]
    assert isinstance(report["recovered"], int)
    # Unknown regions 404; invalid withhold fails validation.
    assert client.get("/api/regions/unknown/blind-test").status_code == 404
    assert client.get("/api/regions/mbale-demo/blind-test?withhold=1000").status_code == 422
