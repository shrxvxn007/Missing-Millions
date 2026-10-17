"""Validated requests; unavailable numeric evidence remains JSON null."""

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


TaskStatus = Literal["unverified", "needs_review", "assigned", "in_progress", "field_verification_in_progress", "verified", "rejected", "insufficient_evidence"]


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class OutreachRequest(StrictRequest):
    region_id: str = Field(min_length=1, max_length=100)
    target_settlement_ids: list[str] = Field(default_factory=list, max_length=500)
    coverage_minutes: float = Field(default=30, ge=5, le=180)
    locations: int = Field(default=1, ge=1, le=2)
    walking_speed_kmh: float = Field(default=4.2, ge=1, le=7)
    fixed_location: tuple[float, float] | None = None

    @model_validator(mode="after")
    def valid_fixed_location(self):
        if self.fixed_location is not None:
            lon, lat = self.fixed_location
            if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise ValueError("Fixed location must be a WGS84 [longitude, latitude] pair")
            if self.locations != 1:
                raise ValueError("A fixed location is a single-stop scenario; set locations to 1")
        return self


class OutreachLocation(StrictRequest):
    coordinates: tuple[float, float]
    name: str | None = Field(default=None, max_length=200)
    id: str | None = Field(default=None, max_length=100)
    node_id: str | None = Field(default=None, max_length=100)
    incremental_target_population: float | None = Field(default=None, ge=0)
    incremental_covered_population: float | None = Field(default=None, ge=0)
    covered_settlement_ids: list[str] | None = Field(default=None, max_length=500)
    simulated: bool = True
    manual: bool = False
    snap_distance_m: float | None = Field(default=None, ge=0)
    requested_coordinates: tuple[float, float] | None = None

    @model_validator(mode="after")
    def valid_coordinates(self):
        lon, lat = self.coordinates
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError("Coordinates must be a WGS84 [longitude, latitude] pair")
        if self.requested_coordinates is not None:
            lon, lat = self.requested_coordinates
            if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise ValueError("Requested coordinates must be a WGS84 [longitude, latitude] pair")
        return self


class TaskCreate(StrictRequest):
    settlement_id: str = Field(min_length=1, max_length=100)
    region_id: str = Field(min_length=1, max_length=100)
    notes: str = Field(default="", max_length=10000)
    status: TaskStatus = "unverified"
    hypothetical_outreach_location: OutreachLocation | None = Field(
        default=None, validation_alias=AliasChoices("hypothetical_outreach_location", "outreach_location")
    )


class TaskUpdate(StrictRequest):
    notes: str | None = Field(default=None, max_length=10000)
    status: TaskStatus | None = None

    @model_validator(mode="after")
    def some_change(self):
        if self.notes is None and self.status is None:
            raise ValueError("Provide status or notes to update")
        return self


ReviewLabel = Literal["residential", "non_residential", "uncertain"]


class ReviewCreate(StrictRequest):
    region_id: str = Field(min_length=1, max_length=100)
    label: ReviewLabel
    notes: str = Field(default="", max_length=10000)
    reviewer: str = Field(default="local reviewer", max_length=200)


class ConfirmedFacilityCreate(StrictRequest):
    region_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    coordinates: tuple[float, float]
    category: Literal["hospital", "clinic", "doctor", "health_post"] = "clinic"
    status: Literal["operating", "status_unverified"] = "operating"

    @model_validator(mode="after")
    def valid_coordinates(self):
        lon, lat = self.coordinates
        if not -180 <= lon <= 180 or not -90 <= lat <= 90:
            raise ValueError("Coordinates must be a WGS84 [longitude, latitude] pair")
        return self
