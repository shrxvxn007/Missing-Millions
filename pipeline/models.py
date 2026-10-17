"""Validated, nullable settlement contract shared by offline sources and the API."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScoreComponent(BaseModel):
    raw_value: float | None
    normalised: float | None = Field(ge=0, le=1)
    weight: float = Field(ge=0, le=1)
    contribution: float | None = Field(ge=0, le=100)


class HistoricalObservation(BaseModel):
    year: int = Field(ge=2000, le=2100)
    buildings: float | None = Field(ge=0)


class Settlement(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    region_id: str
    display_name: str
    data_mode: Literal["real", "synthetic"]
    geometry: dict[str, Any]
    centroid: tuple[float, float]
    building_count_by_year: dict[str, float | None]
    building_count_change: float | None
    building_growth_percentage: float | None
    population_estimate: float | None = Field(ge=0)
    population_reference_year: int | None
    osm_building_discrepancy: float | None = Field(ge=0, le=1)
    road_density: float | None = Field(ge=0)
    road_snap_distance: float | None = Field(ge=0)
    nearest_mapped_facility_id: str | None
    nearest_mapped_facility_name: str | None
    nearest_mapped_facility_distance_m: float | None = Field(ge=0)
    walking_route_distance_m: float | None = Field(ge=0)
    walking_time_minutes: float | None = Field(ge=0)
    routing_status: str
    anomaly_score: float | None = Field(ge=0, le=100)
    anomaly_stability: float | None = Field(ge=0, le=1)
    anomaly_contributors: list[dict[str, Any]]
    priority_score: float | None = Field(ge=0, le=100)
    priority_components: dict[str, ScoreComponent]
    priority_stability: float | None = Field(ge=0, le=1)
    source_metadata: dict[str, Any]
    data_quality_flags: list[str]
    verification_status: str
    history: list[HistoricalObservation]
    explanation: str

    @field_validator("centroid")
    @classmethod
    def valid_wgs84(cls, value):
        if not (-180 <= value[0] <= 180 and -90 <= value[1] <= 90):
            raise ValueError("Centroid must be [longitude, latitude] WGS84")
        return value

    @field_validator("building_count_by_year")
    @classmethod
    def nonnegative_counts(cls, value):
        if any(count is not None and count < 0 for count in value.values()):
            raise ValueError("Building counts must be nonnegative or null")
        return value


def validate_package(package: dict) -> None:
    identifiers = set()
    for value in package["settlements"]:
        settlement = Settlement.model_validate(value)
        if settlement.id in identifiers:
            raise ValueError(f"Duplicate settlement ID {settlement.id}")
        if settlement.data_mode != package["region"]["data_mode"]:
            raise ValueError("Synthetic and real settlements cannot share a package")
        identifiers.add(settlement.id)
