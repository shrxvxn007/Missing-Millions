from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest
import rasterio
from pyproj import Transformer
from rasterio.transform import from_origin
from shapely.geometry import box, mapping, shape

from pipeline.geospatial.grid import (AnalysisGrid, allocate_population_nonoverlapping,
                                     cluster_count_grid, local_metric_crs, project_geometry)
from pipeline.ingest.rasters import aggregate_count_raster, fractional_values_to_counts
from pipeline.ml.analysis import (fit_anomalies, percentile_normalise, prepare_features,
                                  score_priorities, temporal_growth)


def test_metric_crs_and_coordinate_roundtrip():
    assert local_metric_crs(34.18, 1.08) == "EPSG:32636"
    projected = project_geometry(box(34.179, 1.079, 34.181, 1.081), "EPSG:4326", "EPSG:32636")
    assert 49000 < projected.area < 50000
    roundtrip = project_geometry(projected, "EPSG:32636", "EPSG:4326")
    assert roundtrip.bounds == pytest.approx((34.179, 1.079, 34.181, 1.081), abs=1e-8)
    assert local_metric_crs(18, -33) == "EPSG:32734"


def test_fractional_count_is_not_binary_pixel_count():
    fractions = np.array([[.01, .02], [.03, .04]])
    assert fractional_values_to_counts(fractions, .25).sum() == pytest.approx(.1)
    # A mean-resampled 1m raster requires 4 native0.5m pixel supports.
    assert fractional_values_to_counts(fractions, 1).sum() == pytest.approx(.4)
    with pytest.raises(ValueError):
        fractional_values_to_counts(fractions, -1)


def test_count_raster_clips_and_preserves_total(tmp_path):
    path = tmp_path / "persons.tif"
    transform = from_origin(630000, 120000, 100, 100)
    with rasterio.open(path, "w", driver="GTiff", height=4, width=4, count=1,
                       dtype="float64", crs="EPSG:32636", transform=transform) as out:
        out.write(np.arange(1, 17, dtype=float).reshape(4, 4), 1)
    grid = AnalysisGrid("EPSG:32636", 630000, 120000, 2, 2, 200)
    aoi = mapping(project_geometry(box(630000, 119600, 630400, 120000), "EPSG:32636", "EPSG:4326"))
    result = aggregate_count_raster(path, aoi, grid)
    assert result.sum() == pytest.approx(136)
    assert result == pytest.approx(np.array([[14, 22], [46, 54]]))
    half_aoi = mapping(project_geometry(box(630000, 119600, 630200, 120000), "EPSG:32636", "EPSG:4326"))
    half = aggregate_count_raster(path, half_aoi, grid)
    assert np.nansum(half) == pytest.approx(60)
    assert np.all(np.isnan(half[:, 1]))


def test_google_conversion_uses_actual_source_pixel_support(tmp_path):
    path = tmp_path / "fractional.tif"
    with rasterio.open(path, "w", driver="GTiff", height=2, width=2, count=1,
                       dtype="float64", crs="EPSG:32636", transform=from_origin(630000, 120000, 1, 1)) as out:
        out.write(np.full((2, 2), .01), 1)
    grid = AnalysisGrid("EPSG:32636", 630000, 120000, 1, 1, 2)
    aoi = mapping(project_geometry(box(630000, 119998, 630002, 120000), "EPSG:32636", "EPSG:4326"))
    result = aggregate_count_raster(path, aoi, grid, kind="google_fractional")
    assert result[0, 0] == pytest.approx(.16)


def test_dbscan_support_and_nonoverlapping_candidate_totals():
    grid = AnalysisGrid("EPSG:32636", 630000, 120000, 10, 10)
    raster = np.zeros(grid.shape)
    raster[1:3, 1:3] = 20
    raster[7:9, 7:9] = 30
    raster[0, 9] = 100  # singleton artefact is rejected despite large count
    candidates, cells = cluster_count_grid(grid, {2016: raster / 2, 2023: raster})
    assert len(candidates) == 2
    assert len(cells) == 8
    assert sorted(s["building_count_by_year"]["2023"] for s in candidates) == [80, 120]
    assert shape(candidates[0]["geometry"]).intersection(shape(candidates[1]["geometry"])).area == 0
    repeated, _ = cluster_count_grid(grid, {2016: raster / 2, 2023: raster})
    assert [s["id"] for s in candidates] == [s["id"] for s in repeated]


def test_population_cell_cannot_be_double_counted():
    population = np.array([[12., 30.], [8., 5.]])
    settlements = [{"id": "b", "cell_indices": [[0, 0], [0, 1]]},
                   {"id": "a", "cell_indices": [[0, 0], [1, 0]]}]
    totals = allocate_population_nonoverlapping(population, settlements)
    assert totals == [30, 20]
    assert sum(totals) == 50
    population[1, 0] = np.nan
    assert allocate_population_nonoverlapping(population, settlements)[1] is None


def test_temporal_growth_no_interpolation_or_zero_division():
    endpoint = temporal_growth({"2016": 5, "2023": 100})
    assert endpoint["building_count_change"] == 95
    assert endpoint["building_growth_percentage"] is None
    assert endpoint["growth_persistence"] is None
    assert endpoint["growth_observation_count"] == 2
    full = temporal_growth({str(y): v for y, v in zip(range(2016, 2024), [100, 120, 140, 900, 180, 200, 220, 240])})
    assert full["estimated_change_per_year"] == 20
    assert full["building_growth_percentage"] == 140
    assert full["growth_persistence"] < 1


def sample_settlements(n=40):
    return [{"id": str(i), "population_estimate": 100 + i * 35 if i % 4 else None,
             "building_density": 200 + i * 10, "building_count_change": i * 5,
             "building_growth_percentage": i * 3, "walking_time_minutes": 20 + i * 2,
             "road_density": 3 - i / 20, "road_snap_distance": i * 10,
             "osm_building_discrepancy": i / n} for i in range(n)]


def test_ml_preprocess_missing_features_and_seeded_reproducibility():
    one, two = sample_settlements(), sample_settlements()
    features, raw, _ = prepare_features(one)
    assert features.shape == (40, 16)
    assert np.all(np.isfinite(features))
    assert np.isnan(raw[0, 0])
    metadata = fit_anomalies(one)
    fit_anomalies(two)
    assert metadata["status"] == "available"
    assert [s["anomaly_score"] for s in one] == [s["anomaly_score"] for s in two]
    assert all(0 <= s["anomaly_score"] <= 100 and 0 <= s["anomaly_stability"] <= 1 for s in one)
    assert one[-1]["anomaly_contributors"]


def test_insufficient_samples_disable_anomaly_instead_of_fake_confidence():
    candidates = sample_settlements(10)
    metadata = fit_anomalies(candidates)
    assert metadata["status"] == "insufficient_samples"
    assert all(s["anomaly_score"] is None and s["anomaly_stability"] is None for s in candidates)


def test_regional_normalisation_ties_and_missing():
    values = percentile_normalise([10, 20, 20, 30, None])
    assert values[:4] == pytest.approx([0, .5, .5, 1])
    assert np.isnan(values[4])


def test_priority_missing_data_retains_fixed_weights():
    candidates = sample_settlements()
    fit_anomalies(candidates)
    score_priorities(candidates)
    complete = deepcopy(candidates[-1])
    assert 0 <= complete["priority_score"] <= 100
    candidates[-1]["population_estimate"] = None
    score_priorities(candidates)
    incomplete = candidates[-1]
    assert incomplete["priority_score"] <= complete["priority_score"]
    assert incomplete["priority_status"] == "provisional"
    assert incomplete["priority_weight_coverage"] == .75
    assert incomplete["priority_components"]["population"]["contribution"] is None
    candidates[-1]["walking_time_minutes"] = None
    score_priorities(candidates)
    assert candidates[-1]["priority_score"] is None
    assert candidates[-1]["priority_status"] == "access_unknown"


def test_priority_rejects_invalid_weights():
    with pytest.raises(ValueError):
        score_priorities(sample_settlements(), {"access": 1})


def test_real_builder_never_silently_fills_missing_sources(tmp_path):
    from pipeline.build_demo import build_real
    from pipeline.models import validate_package
    grid = {"crs": "EPSG:32636", "west": 630000, "north": 120000,
            "width": 4, "height": 4, "cell_size_m": 250}
    (tmp_path / "grid.json").write_text(json.dumps(grid))
    (tmp_path / "provenance.json").write_text(json.dumps({"fixture_for_unit_test": True}))
    np.savez(tmp_path / "buildings.npz", counts_2016=np.full((4, 4), 10.),
             counts_2023=np.full((4, 4), 20.))
    package = build_real(tmp_path)
    validate_package(package)
    assert package["region"]["years"] == [2016, 2023]
    assert package["region"]["data_mode"] == "real"
    assert len(package["settlements"]) == 1
    settlement = package["settlements"][0]
    assert settlement["population_estimate"] is None
    assert settlement["walking_time_minutes"] is None
    assert settlement["priority_score"] is None
    assert settlement["anomaly_score"] is None
    assert settlement["osm_building_discrepancy"] is None
    assert "synthetic" not in settlement["explanation"].lower()


def test_offline_multi_source_routing_includes_both_connectors():
    from pipeline.build_demo import enrich_spatial_fields
    inverse = Transformer.from_crs("EPSG:32636", "EPSG:4326", always_xy=True)
    coordinates = lambda x: list(inverse.transform(630000 + x, 120000))
    settlements = [{"id": "left", "centroid": coordinates(400), "data_quality_flags": []},
                   {"id": "right", "centroid": coordinates(600), "data_quality_flags": []}]
    package = {"region": {"metric_crs": "EPSG:32636"}, "settlements": settlements,
               "graph": {"nodes": [{"id": "a", "coordinates": coordinates(0)}, {"id": "b", "coordinates": coordinates(1000)}],
                         "edges": [{"source": "a", "target": "b", "length_m": 1000}]},
               "roads": {"features": []},
               "facility_records": [{"id": "f-a", "name": "A", "coordinates": coordinates(-500)},
                                    {"id": "f-b", "name": "B", "coordinates": coordinates(1100)}]}
    enrich_spatial_fields(package)
    assert settlements[0]["nearest_mapped_facility_id"] == "f-a"
    assert settlements[0]["walking_route_distance_m"] == pytest.approx(900)
    assert settlements[1]["nearest_mapped_facility_id"] == "f-b"
    assert settlements[1]["walking_route_distance_m"] == pytest.approx(500)
    assert settlements[0]["route_geometry"]["coordinates"][0] == settlements[0]["centroid"]


def test_acquired_real_pack_counts_finite_and_candidates_do_not_double_count():
    root = Path(__file__).resolve().parents[1]
    source = root / "data/raw/turkana-real"
    output = root / "data/processed/turkana.json"
    if not output.exists():
        source = root / "data/raw/mbale-real"
        output = root / "data/processed/mbale.json"
    if not output.exists() or not (source / "buildings.npz").exists():
        pytest.skip("Optional acquired real source pack is not installed")
    package = json.loads(output.read_text())
    grid_info = json.loads((source / "grid.json").read_text())
    counts = np.load(source / "buildings.npz")
    population = np.load(source / "population.npz")["population"]
    provenance = json.loads((source / "provenance.json").read_text())
    assert package["region"]["data_mode"] == "real"
    assert package["region"]["years"] == [2016, 2023]
    expected_shape = (grid_info["height"], grid_info["width"])
    for record in provenance["open_buildings"]["records"]:
        values = counts[f"counts_{record['year']}"]
        assert values.shape == expected_shape
        assert np.all(np.isfinite(values)) and np.all(values >= 0)
        assert values.sum() == pytest.approx(record["building_count_sum"], rel=1e-9)
    assert np.nansum(population) == pytest.approx(provenance["worldpop"]["aggregated_grid_sum"], rel=1e-9)
    assigned = set()
    for settlement in package["settlements"]:
        cells = [tuple(cell) for cell in settlement["cell_indices"]]
        assert not assigned.intersection(cells)
        assigned.update(cells)
        rows, columns = zip(*cells)
        assert settlement["population_estimate"] == pytest.approx(float(population[rows, columns].sum()), abs=.051)
        for year in [2016, 2023]:
            assert settlement["building_count_by_year"][str(year)] == pytest.approx(float(counts[f"counts_{year}"][rows, columns].sum()), abs=.0051)
            assert 0 <= settlement["building_presence"]["mean_uncalibrated_score_by_year"][str(year)] <= 1
        assert settlement["walking_route_distance_m"] >= settlement["nearest_mapped_facility_distance_m"]
        route = project_geometry(settlement["route_geometry"], "EPSG:4326", package["region"]["metric_crs"])
        assert route.length == pytest.approx(settlement["walking_route_distance_m"], abs=.11)
        assert "representative_point_access_not_all_residents" in settlement["data_quality_flags"]
        assert settlement["osm_building_discrepancy"] is None
    assert len(assigned) == len(package["cells"]["features"]) <= grid_info["width"] * grid_info["height"]
    assert sum(s["population_estimate"] for s in package["settlements"]) <= np.nansum(population)
    assert sum(s["building_count_by_year"]["2023"] for s in package["settlements"]) <= counts["counts_2023"].sum()
