import json

import pytest
from fastapi.testclient import TestClient

from services.api.main import create_app


@pytest.fixture
def demo_paths(tmp_path):
    region_id = "mbale-demo"
    settlements = []
    for i, lon in enumerate([34.15, 34.18, 34.21]):
        center = [lon, 1.07]
        settlements.append({
            "id": f"settlement-{i}", "region_id": region_id, "display_name": f"Candidate {i + 1}",
            "centroid": center, "geometry": {"type": "Polygon", "coordinates": [[
                [lon - .001, 1.069], [lon + .001, 1.069], [lon + .001, 1.071], [lon - .001, 1.071], [lon - .001, 1.069]]]},
            "building_count_by_year": {"2016": 30 + i * 10, "2023": 50 + i * 20},
            "population_estimate": 100 + 100 * i, "population_reference_year": 2023,
            "building_density": 100, "road_density": 1, "osm_building_discrepancy": None,
            "data_mode": "synthetic", "data_quality_flags": ["Synthetic demonstration data"],
        })
    fixture = {"region": {"id": region_id, "name": "Synthetic test region", "data_mode": "synthetic"},
               "data_mode": "synthetic", "settlements": settlements,
               "facility_records": [{"id": "clinic-1", "name": "Test clinic", "coordinates": [34.15, 1.07], "category": "clinic"}],
               "graph": {"nodes": [{"id": str(i), "coordinates": s["centroid"]} for i, s in enumerate(settlements)],
                         "edges": [{"source": "0", "target": "1", "length_m": 3340}, {"source": "1", "target": "2", "length_m": 3340}]},
               "manifest": {"data_mode": "synthetic", "limitations": ["Synthetic test fixture"]}}
    path, db = tmp_path / "demo.json", tmp_path / "tasks.sqlite"
    path.write_text(json.dumps(fixture))
    return path, db


@pytest.fixture
def client(demo_paths):
    with TestClient(create_app(*demo_paths)) as instance:
        yield instance


def test_region_lookup_layers_detail_and_actual_timeline(client):
    assert client.get("/api/health").json()["data_package"] == "ready"
    assert client.get("/api/regions").json()["regions"][0]["id"] == "mbale-demo"
    summary = client.get("/api/regions/mbale-demo/overview").json()["summary"]
    assert summary["candidate_count"] == 3 and summary["population_estimate"] == 600
    timeline = client.get("/api/regions/mbale-demo/timeline").json()
    assert timeline["years"] == [2016, 2023]
    assert len(timeline["settlements"]) == 3
    details = client.get("/api/settlements/settlement-2").json()
    assert details["walking_route_distance_m"] == 6680
    assert details["walking_time_minutes"] == 95.4
    assert details["anomaly_score"] is None  # Small samples disable the model.
    layers = client.get("/api/regions/mbale-demo/layers").json()
    assert len(layers["facilities"]["features"]) == 1
    assert len(layers["settlements"]["features"]) == 3
    assert layers["routes"]["type"] == "FeatureCollection"
    assert client.get("/api/regions/mbale-demo/manifest").json()["data_mode"] == "synthetic"


def test_invalid_inputs_have_explicit_json_errors(client):
    assert client.get("/api/regions/unknown/overview").status_code == 404
    assert client.get("/api/settlements/unknown").status_code == 404
    assert client.get("/api/regions/mbale-demo/settlements?min_priority=101").status_code == 422
    for body in [
        {"region_id": "mbale-demo", "locations": 3},
        {"region_id": "mbale-demo", "walking_speed_kmh": 0},
        {"region_id": "mbale-demo", "coverage_minutes": -1},
        {"region_id": "mbale-demo", "target_settlement_ids": ["unknown"]},
        {"region_id": "mbale-demo", "walking_speed_kmh": "nan"},
    ]:
        response = client.post("/api/outreach/simulate", json=body)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == 422
    assert client.get("/api/not-a-real-endpoint").status_code == 404


def test_outreach_simulation_uses_network_and_baseline(client):
    response = client.post("/api/outreach/simulate", json={"region_id": "mbale-demo", "target_settlement_ids": ["settlement-2"], "locations": 2})
    assert response.status_code == 200
    result = response.json()
    assert result["summary"]["incremental_covered_population"] >= 300
    assert result["summary"]["baseline_covered_population"] == 100
    assert result["locations"][0]["simulated"] is True
    assert result["coverage_network"]["type"] == "FeatureCollection"
    assert all(f["geometry"]["type"] == "LineString" for f in result["coverage_network"]["features"])


def test_verification_tasks_survive_new_app_and_export_evidence(client, demo_paths):
    response = client.post("/api/verification-tasks", json={"region_id": "mbale-demo", "settlement_id": "settlement-2", "notes": "Check path usability"})
    assert response.status_code == 201
    task = response.json()
    assert task["status"] == "unverified"
    assert task["evidence"]["walking_time_minutes"] == 95.4
    assert task["recommended_verification_questions"]
    result = client.patch(f"/api/verification-tasks/{task['id']}", json={"status": "assigned", "notes": "Local mapping review"})
    assert result.status_code == 200 and result.json()["status"] == "assigned"
    assert client.patch(f"/api/verification-tasks/{task['id']}", json={"status": "made-up"}).status_code == 422
    assert client.patch(f"/api/verification-tasks/{task['id']}", json={}).status_code == 422
    with TestClient(create_app(*demo_paths)) as second_client:
        tasks = second_client.get("/api/verification-tasks").json()["tasks"]
        assert tasks[0]["id"] == task["id"] and tasks[0]["status"] == "assigned"
        assert second_client.get("/api/settlements/settlement-2").json()["verification_status"] == "assigned"
        exported = second_client.get("/api/verification-tasks/export")
        assert exported.headers["content-type"].startswith("text/csv")
        assert "evidence_json" in exported.text and task["id"] in exported.text
        assert second_client.get("/api/verification-tasks/export?format=json").json()["tasks"][0]["id"] == task["id"]
        assert second_client.get("/api/verification-tasks/export?format=geojson").json()["features"][0]["geometry"]["type"] == "Polygon"


def test_task_region_and_location_validation(client):
    request = {"region_id": "mbale-demo", "settlement_id": "settlement-0", "status": "needs_review", "outreach_location": {"coordinates": [34.2, 1.07]}}
    assert client.post("/api/verification-tasks", json=request).status_code == 201
    request["outreach_location"]["coordinates"] = [200, 1]
    assert client.post("/api/verification-tasks", json=request).status_code == 422
    assert client.post("/api/verification-tasks", json={"region_id": "wrong", "settlement_id": "settlement-0"}).status_code == 404


def test_complete_simulated_stop_can_be_attached_to_investigation(client):
    simulation = client.post("/api/outreach/simulate", json={"region_id": "mbale-demo", "target_settlement_ids": ["settlement-2"]}).json()
    response = client.post("/api/verification-tasks", json={
        "region_id": "mbale-demo", "settlement_id": "settlement-2", "status": "needs_review",
        "outreach_location": simulation["locations"][0],
    })
    assert response.status_code == 201
    assert response.json()["hypothetical_outreach_location"]["simulated"] is True


def test_missing_data_and_static_frontend_fail_gracefully(tmp_path):
    with TestClient(create_app(tmp_path / "missing.json", tmp_path / "tasks.db", tmp_path / "dist")) as client:
        assert client.get("/api/health").json()["status"] == "degraded"
        assert client.get("/api/regions").status_code == 503
        assert client.get("/").status_code == 404
    (tmp_path / "dist").mkdir()
    (tmp_path / "dist/index.html").write_text("<html>The Missing Millions</html>")
    with TestClient(create_app(tmp_path / "missing.json", tmp_path / "tasks.db", tmp_path / "dist")) as client:
        assert "The Missing Millions" in client.get("/").text
        assert client.get("/investigate/settlement").status_code == 200
        assert client.get("/api/missing").status_code == 404


def test_default_catalog_keeps_separate_packages_and_engines(demo_paths, tmp_path, monkeypatch):
    from copy import deepcopy
    from services.api import main as api_module

    fixture_path, db = demo_paths
    synthetic = json.loads(fixture_path.read_text())
    turkana_fixture = deepcopy(synthetic)
    turkana_fixture["region"]["id"] = "turkana-real"
    turkana_fixture["region"]["data_mode"] = "real"
    turkana_fixture["data_mode"] = "real"
    for settlement in turkana_fixture["settlements"]:
        settlement["id"] = "turkana-" + settlement["id"]
        settlement["region_id"] = "turkana-real"
    for edge in turkana_fixture["graph"]["edges"]:
        edge["length_m"] = 1000
    mbale_fixture = deepcopy(synthetic)
    mbale_fixture["region"]["id"] = "mbale-real"
    mbale_fixture["region"]["data_mode"] = "real"
    mbale_fixture["data_mode"] = "real"
    for settlement in mbale_fixture["settlements"]:
        settlement["id"] = "mbale-" + settlement["id"]
        settlement["region_id"] = "mbale-real"
    for edge in mbale_fixture["graph"]["edges"]:
        edge["length_m"] = 2000
    processed = tmp_path / "data/processed"
    processed.mkdir(parents=True)
    (processed / "demo.json").write_text(json.dumps(synthetic))
    (processed / "turkana.json").write_text(json.dumps(turkana_fixture))
    (processed / "mbale.json").write_text(json.dumps(mbale_fixture))
    monkeypatch.setattr(api_module, "ROOT", tmp_path)
    monkeypatch.delenv("DATA_PACKAGE_PATH", raising=False)
    with TestClient(create_app(db_path=db)) as client:
        regions = client.get("/api/regions").json()["regions"]
        assert [region["id"] for region in regions] == ["turkana-real", "mbale-real", "mbale-demo"]
        assert client.get("/api/settlements/turkana-settlement-2").json()["walking_route_distance_m"] == 2000
        assert client.get("/api/settlements/mbale-settlement-2").json()["walking_route_distance_m"] == 4000
        assert client.get("/api/settlements/settlement-2").json()["walking_route_distance_m"] == 6680
        # Threshold is 30 minutes at 4.2 km/h = 2,100 m of mapped route distance.
        for region_id, baseline in [("turkana-real", 600), ("mbale-real", 300), ("mbale-demo", 100)]:
            result = client.post("/api/outreach/simulate", json={"region_id": region_id}).json()
            assert result["summary"]["baseline_covered_population"] == baseline
        assert client.post("/api/verification-tasks", json={"region_id": "mbale-real", "settlement_id": "mbale-settlement-2"}).status_code == 201
        assert client.post("/api/verification-tasks", json={"region_id": "mbale-real", "settlement_id": "turkana-settlement-2"}).status_code == 404
    monkeypatch.setenv("DATA_PACKAGE_PATH", str(processed / "demo.json"))
    with TestClient(create_app(db_path=db)) as client:
        assert [region["id"] for region in client.get("/api/regions").json()["regions"]] == ["mbale-demo"]
        assert client.get("/api/regions/turkana-real/overview").status_code == 404


def test_precomputed_package_skips_graph_and_model_work_until_simulation(demo_paths, monkeypatch):
    from services.api.data import DataRepository
    from pipeline.ml import analysis

    path, _ = demo_paths
    complete = DataRepository(path).load()
    path.write_text(json.dumps(complete))
    repository = DataRepository(path)
    original_factory = repository._make_engine
    builds = []

    def build_engine(package):
        builds.append(package)
        return original_factory(package)

    monkeypatch.setattr(repository, "_make_engine", build_engine)
    monkeypatch.setattr(analysis, "recompute_analysis", lambda _settlements: pytest.fail("Precomputed models must not be retrained"))
    loaded = repository.load()
    assert not builds and repository.engine is None
    assert loaded["settlements"][2]["walking_route_distance_m"] == 6680
    first_layers = repository.layers(loaded)
    assert repository.layers(loaded) is first_layers
    engine = repository.get_engine()
    assert repository.get_engine() is engine and len(builds) == 1
    assert engine.simulate(loaded["settlements"], [], 30)["summary"]["incremental_covered_population"] > 0


def test_manual_outreach_recalculates_and_preserves_zero_gain(client):
    baseline = client.post("/api/outreach/simulate", json={
        "region_id": "mbale-demo", "fixed_location": [34.15, 1.07],
    })
    assert baseline.status_code == 200
    result = baseline.json()
    assert len(result["locations"]) == 1 and result["locations"][0]["manual"] is True
    assert result["summary"]["incremental_covered_population"] == 0
    assert all(s["before_minutes"] == s["after_minutes"] for s in result["settlements"])
    moved = client.post("/api/outreach/simulate", json={
        "region_id": "mbale-demo", "fixed_location": [34.21, 1.07],
    }).json()
    assert moved["summary"]["incremental_covered_population"] == 300
    assert moved["locations"][0]["coordinates"] == [34.21, 1.07]
    assert client.post("/api/verification-tasks", json={
        "region_id": "mbale-demo", "settlement_id": "settlement-2",
        "outreach_location": moved["locations"][0],
    }).status_code == 201


def test_manual_outreach_rejects_invalid_or_unconnected_locations(client):
    for location in [[181, 1], [34, 91], [34], [34, "nan"], [0, 0]]:
        response = client.post("/api/outreach/simulate", json={
            "region_id": "mbale-demo", "fixed_location": location,
        })
        assert response.status_code == 422
        assert response.json()["error"]["code"] == 422
    assert client.post("/api/outreach/simulate", json={
        "region_id": "mbale-demo", "fixed_location": [34.2, 1.07], "locations": 2,
    }).status_code == 422
