"""Network distances, connector costs and reachability are physical invariants."""

import pytest
from pyproj import Transformer

from services.api.routing import RoutingEngine


TO_WGS84 = Transformer.from_crs("EPSG:32636", "EPSG:4326", always_xy=True)


def point(x, y=0):
    return list(TO_WGS84.transform(500000 + x, 100000 + y))


def graph(xs, edges=None, directed=False):
    nodes = [{"id": str(i), "coordinates": point(x)} for i, x in enumerate(xs)]
    return {"directed": directed, "nodes": nodes,
            "edges": [{"source": str(a), "target": str(b), "length_m": abs(xs[a] - xs[b])}
                      for a, b in (edges if edges is not None else zip(range(len(xs) - 1), range(1, len(xs))))]}


def test_projected_road_length_and_both_off_network_connectors():
    engine = RoutingEngine(graph([0, 700, 1400]), [{"id": "clinic", "name": "Clinic", "coordinates": point(-100)}])
    route = engine.route({"centroid": point(1400, 100)})
    assert route["routing_status"] == "routable"
    assert route["road_snap_distance"] == pytest.approx(100, abs=.1)
    assert route["walking_route_distance_m"] == pytest.approx(1600, abs=.1)
    assert route["walking_time_minutes"] == pytest.approx(22.9, abs=.1)
    assert route["walking_time_sensitivity"]["slow_3_kmh"] == pytest.approx(32)
    assert route["route_geometry"]["coordinates"][0] == point(1400, 100)
    assert route["route_geometry"]["coordinates"][-1] == point(-100)


def test_multi_source_facility_choice_includes_connector_cost():
    facilities = [{"id": "near-road", "coordinates": point(0)},
                  {"id": "off-road", "coordinates": point(700, 900)}]
    route = RoutingEngine(graph([0, 700]), facilities).route({"centroid": point(700)})
    assert route["nearest_mapped_facility_id"] == "near-road"
    assert route["walking_route_distance_m"] == 700


def test_directed_routes_compute_travel_to_facility():
    network = graph([0, 700, 1400], directed=True)
    forward = RoutingEngine(network, [{"id": "end", "coordinates": point(1400)}])
    assert forward.route({"centroid": point(0)})["walking_route_distance_m"] == 1400
    backward = RoutingEngine(network, [{"id": "start", "coordinates": point(0)}])
    unreachable = backward.route({"centroid": point(1400)})
    assert unreachable["routing_status"] == "disconnected_network"
    assert unreachable["walking_time_minutes"] is None
    assert unreachable["nearest_mapped_facility_id"] is None


def test_disconnected_and_distant_snaps_remain_unknown():
    engine = RoutingEngine(graph([0, 700, 1400], [(0, 1)]), [{"id": "clinic", "coordinates": point(0)}])
    assert engine.route({"centroid": point(1400)})["routing_status"] == "disconnected_network"
    assert engine.route({"centroid": point(1400, 2500)})["routing_status"] == "insufficient_network"
    empty = RoutingEngine({"nodes": [], "edges": []}, [])
    assert empty.route({"centroid": point(0)})["road_snap_distance"] is None


def test_greedy_max_coverage_is_incremental_over_facility_baseline():
    engine = RoutingEngine(graph([0, 700, 1400, 2100, 2800, 3500]), [{"id": "clinic", "coordinates": point(0)}])
    settlements = [{"id": f"s{i}", "centroid": point(x), "population_estimate": p}
                   for i, x, p in [(0, 0, 150), (1, 2800, 200), (2, 3500, 300)]]
    result = engine.simulate(settlements, ["s1", "s2"], coverage_minutes=15, locations=1)
    assert len(result["locations"]) == 1
    assert result["summary"]["baseline_covered_population"] == 150
    assert result["summary"]["scenario_covered_population"] == 650
    assert result["summary"]["incremental_covered_population"] == 500
    assert all(item["after_minutes"] <= item["before_minutes"] for item in result["settlements"])
    assert result["coverage_network"]["features"]
    assert {item["geometry"]["type"] for item in result["coverage_network"]["features"]} == {"LineString"}


def test_scenario_with_no_incremental_benefit_does_not_invent_a_stop():
    engine = RoutingEngine(graph([0, 700]), [{"id": "clinic", "coordinates": point(0)}])
    result = engine.simulate([{"id": "s0", "centroid": point(0), "population_estimate": 100}], [], 30, 2)
    assert result["locations"] == []
    assert result["summary"]["incremental_covered_population"] == 0
    assert result["coverage_network"]["features"] == []


def test_unreachable_baseline_can_get_a_valid_outreach_path():
    engine = RoutingEngine(graph([0, 700, 1400, 2100], [(0, 1), (2, 3)]), [{"id": "clinic", "coordinates": point(0)}])
    result = engine.simulate([{"id": "s0", "centroid": point(2100), "population_estimate": 100}], [], 15)
    assert result["settlements"][0]["before_minutes"] is None
    assert result["settlements"][0]["after_minutes"] is not None
    assert result["settlements"][0]["newly_covered"] is True


def test_manual_stop_cannot_invent_a_path_to_another_component():
    engine = RoutingEngine(graph([0, 700, 1400, 2100], [(0, 1), (2, 3)]), [{"id": "clinic", "coordinates": point(0)}])
    settlements = [{"id": "disconnected", "centroid": point(2100), "population_estimate": 100}]
    result = engine.simulate(settlements, [], 30, fixed_location=point(0))
    assert len(result["locations"]) == 1
    assert result["settlements"][0]["before_minutes"] is None
    assert result["settlements"][0]["after_minutes"] is None
    assert result["summary"]["incremental_covered_population"] == 0
    assert not result["settlements"][0]["newly_covered"]
    assert all(feature["geometry"]["type"] == "LineString" for feature in result["coverage_network"]["features"])
    with pytest.raises(ValueError, match="too far"):
        engine.simulate(settlements, [], fixed_location=point(10000, 10000))
    empty = RoutingEngine({"nodes": [], "edges": []}, [])
    with pytest.raises(ValueError, match="No mapped walking network"):
        empty.simulate(settlements, [], fixed_location=point(0))
