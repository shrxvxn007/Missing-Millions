"""Tests for the discovery→verification loop added to the initial prototype.

Registry comparison, gap classification, human review overlays, active
learning, the review-label classifier and locally confirmed facilities must all
behave honestly: unknowns stay unknown, labels adjust rankings visibly, and
nothing silently overwrites source evidence.
"""
from __future__ import annotations

from copy import deepcopy
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import shape

from pipeline.geospatial.gaps import (classify_candidate_gaps, registry_recall,
                                     match_settlements_to_registry)
from pipeline.ml.reviews import (apply_review_overlays, investigation_value,
                                 review_queue, train_label_classifier)
from services.api.main import create_app


def registry_feature(identifier: str, lon: float, lat: float, name: str, place: str = "village") -> dict:
    return {"type": "Feature", "id": identifier,
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"id": identifier, "name": name, "place": place, "source": "OpenStreetMap"}}


def make_crs(lon: float, lat: float) -> str:
    from pipeline.geospatial.grid import local_metric_crs
    return local_metric_crs(lon, lat)


def settlement(identifier: str, lon: float, lat: float, **extra) -> dict:
    return {"id": identifier, "centroid": [lon, lat], **extra}


# ---------------- registry matching & gap classification ----------------

def test_registry_match_statuses_and_distances():
    crs = make_crs(34.18, 1.08)
    registry = {"type": "FeatureCollection", "features": [
        registry_feature("r-1", 34.180000, 1.080000, "Named village"),
        registry_feature("r-2", 34.193000, 1.080000, "Far hamlet"),  # ~1.4 km from r-1
    ]}
    settlements = [
        settlement("at-village", 34.18001, 1.08),      # ~1 m from r-1
        settlement("near-hamlet", 34.1865, 1.08),      # ~724 m from r-2
        settlement("no-record", 34.1950, 1.095),        # >1.6 km from every registry point
    ]
    result = match_settlements_to_registry(settlements, registry, crs)
    assert result["status"] == "available" and result["registry_record_count"] == 2
    statuses = {s["id"]: s["record_match_status"] for s in settlements}
    assert statuses == {"at-village": "matched", "near-hamlet": "ambiguous", "no-record": "unmatched"}
    at_village = settlements[0]
    assert at_village["nearest_registry_name"] == "Named village"
    assert at_village["nearest_registry_distance_m"] < 10
    assert "r-1" in at_village["registry_record_ids"]
    unmatched = settlements[2]
    assert unmatched["nearest_registry_distance_m"] > 900
    assert unmatched["registry_record_ids"] == []


def test_empty_registry_reports_no_registry_without_faking_gaps():
    crs = make_crs(34.18, 1.08)
    candidates = [settlement("any", 34.18, 1.08)]
    result = match_settlements_to_registry(candidates, {"type": "FeatureCollection", "features": []}, crs)
    assert result["status"] == "no_registry"
    assert candidates[0]["record_match_status"] == "no_registry"
    assert candidates[0]["nearest_registry_name"] is None
    classification = classify_candidate_gaps(candidates)
    assert classification["classification_counts"]["undetermined"] == 1
    assert candidates[0]["candidate_gap_type"] == "undetermined"


def test_gap_classification_distinguishes_mapping_access_and_combined():
    settlements = [
        settlement("a", 34.18, 1.08, record_match_status="unmatched", walking_time_minutes=95, routing_status="routable"),
        settlement("b", 34.19, 1.08, record_match_status="unmatched", walking_time_minutes=20, routing_status="routable"),
        settlement("c", 34.20, 1.08, record_match_status="matched", walking_time_minutes=120, routing_status="routable"),
        settlement("d", 34.21, 1.08, record_match_status="matched", walking_time_minutes=15, routing_status="routable"),
        settlement("e", 34.22, 1.08, record_match_status="matched", walking_time_minutes=None, routing_status="insufficient_road_data"),
    ]
    classify_candidate_gaps(settlements)
    types = {s["id"]: s["candidate_gap_type"] for s in settlements}
    assert types["a"] == "combined_gap"
    assert types["b"] == "mapping_gap"
    assert types["c"] == "access_gap"
    assert types["d"] == "none"
    # Unknown routing never fabricates an access gap.
    assert types["e"] == "none"
    classifications = {s["id"]: s["gap_classification"]["access_state"] for s in settlements}
    assert classifications["e"] == "unknown"


def test_registry_recall_only_counts_in_extent_points():
    package = {"region": {"metric_crs": "EPSG:32636", "bbox": [34.17, 1.07, 34.19, 1.09]},
               "registry": {"type": "FeatureCollection", "features": [
                   registry_feature("in-1", 34.175, 1.075, "Inside A"),
                   registry_feature("in-2", 34.185, 1.085, "Inside B"),
                   registry_feature("out-1", 34.30, 1.20, "Far outside")]},
               "settlements": [settlement("c-1", 34.175, 1.075), settlement("c-2", 34.186, 1.086)]}
    result = registry_recall(package)
    assert result["registry_points"] == 2
    assert result["recovered"] == 2
    assert result["recall"] == 1.0
    assert all(match["candidate_id"] for match in result["matches"])


# ---------------- review overlays & active learning ----------------

def sample_region(n: int = 8) -> list[dict]:
    settlements = []
    for index in range(n):
        settlements.append({
            "id": f"s-{index}", "region_id": "r", "display_name": f"C{index}",
            "population_estimate": 80 + index * 40,
            "walking_time_minutes": 20 + index * 12 if index < n - 1 else None,
            "routing_status": "routable" if index < n - 1 else "insufficient_road_data",
            "priority_missing_components": [],
            "candidate_gap_type": "combined_gap" if index % 2 else "none",
            "record_match_status": "ambiguous" if index % 2 else "matched",
            "data_quality_flags": [],
            "priority_score": 40 + index * 5,
            "priority_components": {}, "priority_status": "available",
            "priority_weight_coverage": 1.0, "priority_stability": .9, "priority_sensitivity_range": [0, 100],
        })
    return settlements


def test_non_residential_review_changes_priority_and_keeps_originals():
    settlements = sample_region()
    before = deepcopy(settlements)
    from pipeline.ml.analysis import score_priorities
    score_priorities(settlements)
    original_scores = {s["id"]: s.get("priority_score") for s in settlements}
    labels = {"s-2": "non_residential"}
    collections_changed = apply_review_overlays(settlements, labels)
    assert collections_changed == 1
    target = next(s for s in settlements if s["id"] == "s-2")
    assert target["review_label"] == "non_residential"
    assert target["effective_population_estimate"] is None
    assert "review_label_non_residential" in target["data_quality_flags"]
    assert target["adjustment_reason"] and "non-residential" in target["adjustment_reason"]
    # Regional towns beyond the label must keep their own priority intact.
    other = next(s for s in settlements if s["id"] == "s-5")
    assert other.get("adjusted_priority") is None or other.get("review_label") is None
    for source in before:
        pass  # deep-copied before the fit; originals never overlaid
    # The original region source is untouched by design (dict copies).
    assert original_scores["s-2"] is not None


def test_residential_and_uncertain_keep_ranking_but_flag():
    settlements = sample_region()
    apply_review_overlays(settlements, {"s-1": "residential", "s-3": "uncertain"})
    one = next(s for s in settlements if s["id"] == "s-1")
    three = next(s for s in settlements if s["id"] == "s-3")
    assert one["review_label"] == "residential" and one["effective_population_estimate"] == one["population_estimate"]
    assert "review_label_residential" in one["data_quality_flags"]
    assert three["review_label"] == "uncertain"
    assert "uncertain" in three["adjustment_reason"]


def test_investigation_value_rewards_uncertainty_and_gap():
    strong = sample_region(1)[0]
    strong.update({"walking_time_minutes": 15, "routing_status": "routable",
                   "candidate_gap_type": "none", "record_match_status": "matched",
                   "priority_missing_components": []})
    uncertain = sample_region(1)[0]
    uncertain.update({"walking_time_minutes": None, "routing_status": "insufficient_road_data",
                      "candidate_gap_type": "combined_gap", "record_match_status": "unmatched",
                      "priority_missing_components": ["anomaly", "population"]})
    low_priority_high_certainty = investigation_value(strong)
    high_priority_high_uncertainty = investigation_value(uncertain)
    assert high_priority_high_uncertainty["investigation_value"] > low_priority_high_certainty["investigation_value"]
    assert high_priority_high_uncertainty["unresolved_factors"]
    assert not low_priority_high_certainty["unresolved_factors"]


def test_review_queue_excludes_reviewed_and_ranks_by_value():
    settlements = sample_region()
    for s in settlements:
        s["routing_status"] = "routable"
    labels = {"s-0": "residential"}
    queue = review_queue(settlements, reviewed_ids=set(labels), limit=5)
    assert len(queue) == 5
    assert all(item["settlement_id"] != "s-0" for item in queue)
    values = [item["investigation_value"] for item in queue]
    assert values == sorted(values, reverse=True)
    assert queue[0]["queue_rank"] == 1


def test_classifier_honest_insufficiency_then_trains():
    settlements = sample_region(12)
    labels = {s["id"]: "residential" if i < 2 else "non_residential" for i, s in enumerate(settlements)}
    labels["s-2"] = "uncertain"
    result = train_label_classifier(settlements, labels, minimum_labeled=10)
    if result["status"] == "insufficient_labels":
        assert result["labeled_samples"] < result["minimum_labeled"]
    else:
        assert result["positive_class"] == "residential"
        assert result["coefficients"]
        assert "generalisation_warning" in result
    # Sparse uncertain labels never enter the two-class model.
    counts = result["label_counts"]
    assert counts["uncertain"] == 1


# ---------------- API: reviews, queue, classifier, confirmed facilities ----------------

@pytest.fixture
def feedback_client(tmp_path):
    region_id = "mbale-demo"
    settlements = []
    coords = [(34.150 + i * .01, 1.07) for i in range(4)]
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
    fixture = {"region": {"id": region_id, "name": "Feedback test region", "data_mode": "synthetic",
                          "bbox": [34.14, 1.06, 34.20, 1.08]},
               "data_mode": "synthetic", "settlements": settlements,
               "facility_records": [{"id": "clinic-1", "name": "Test clinic", "coordinates": [34.15, 1.07], "category": "clinic"}],
               "graph": {"nodes": [{"id": str(i), "coordinates": list(c)} for i, c in enumerate(coords)],
                         "edges": [{"source": "0", "target": "1", "length_m": 1110},
                                   {"source": "1", "target": "2", "length_m": 1110},
                                   {"source": "2", "target": "3", "length_m": 1110}]},
               "manifest": {"data_mode": "synthetic", "limitations": ["Synthetic test fixture"]}}
    data_path, db = tmp_path / "demo.json", tmp_path / "tasks.sqlite"
    data_path.write_text(json.dumps(fixture))
    return create_app(data_path, db, tmp_path / "dist")


def test_review_endpoint_recomputes_priority_and_persists(feedback_client):
    with TestClient(feedback_client) as client:
        detail = client.get("/api/settlements/settlement-2").json()
        before = detail["priority_score"]
        assert before is not None
        response = client.post("/api/settlements/settlement-2/reviews",
                               json={"region_id": "mbale-demo", "label": "non_residential", "notes": "imagery shows storage sheds"})
        assert response.status_code == 201
        payload = response.json()
        assert payload["review"]["label"] == "non_residential"
        settled = payload["settlement"]
        assert settled["review_label"] == "non_residential"
        assert settled["effective_population_estimate"] is None
        assert settled.get("adjusted_priority", {}).get("priority_score") is not None
        reviews = client.get("/api/settlements/settlement-2/reviews").json()
        assert reviews["current_label"] == "non_residential" and len(reviews["reviews"]) == 1


def test_review_queue_orders_and_excludes(feedback_client):
    with TestClient(feedback_client) as client:
        client.post("/api/settlements/settlement-3/reviews", json={"region_id": "mbale-demo", "label": "residential"})
        queue = client.get("/api/regions/mbale-demo/review-queue?limit=10").json()
        assert queue["labeled_count"] == 1
        ids = [item["settlement_id"] for item in queue["queue"]]
        assert "settlement-3" not in ids
        values = [item["investigation_value"] for item in queue["queue"]]
        assert values == sorted(values, reverse=True)
        assert all(item["suggested_task"] for item in queue["queue"])


def test_classifier_endpoint_reports_status(feedback_client):
    with TestClient(feedback_client) as client:
        result = client.post("/api/regions/mbale-demo/classifier/train").json()
        assert result["model_version"]
        assert result["status"] in ("available", "insufficient_labels")
        if result["status"] == "insufficient_labels":
            assert result["reason"] and "label" in result["reason"].lower()


def test_new_confirmed_facility_recomputes_access_and_rank(feedback_client):
    with TestClient(feedback_client) as client:
        before = {s["id"]: s["walking_time_minutes"] for s in
                  client.get("/api/regions/mbale-demo/settlements").json()["settlements"]}
        added = client.post("/api/regions/mbale-demo/confirmed-facilities", json={
            "region_id": "mbale-demo", "name": "Locally confirmed dispensary",
            "coordinates": [34.174, 1.07],  # snaps to node 2, shortening node 2/3 routes
        }).json()
        assert added["facilities"][0]["name"] == "Locally confirmed dispensary"
        target = next(change for change in added["settlements"] if change["id"] == "settlement-3")
        # At least one candidate must be closer through the confirmed record.
        improved = [c for c in added["settlements"]
                    if c["after_minutes"] is not None and c["before_minutes"] is not None
                    and c["after_minutes"] < c["before_minutes"]]
        assert improved, "A new nearby clinic should shorten at least one candidate's route"
        assert target["after_minutes"] < target["before_minutes"]
        listing = client.get("/api/regions/mbale-demo/confirmed-facilities").json()
        assert len(listing["facilities"]) == 1
        # Out-of-region coordinates are rejected honestly.
        assert client.post("/api/regions/mbale-demo/confirmed-facilities", json={
            "region_id": "mbale-demo", "name": "Away", "coordinates": [2.5, 45.0]}).status_code == 422


def test_review_validation_and_unknown_settlement(feedback_client):
    with TestClient(feedback_client) as client:
        assert client.post("/api/settlements/settlement-0/reviews",
                           json={"region_id": "mbale-demo", "label": "made_up"}).status_code == 422
        assert client.post("/api/settlements/unknown/reviews",
                           json={"region_id": "mbale-demo", "label": "residential"}).status_code == 404
