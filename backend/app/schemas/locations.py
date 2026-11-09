from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class LocationPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    action: Literal["set", "reset", "clear"] = "set"
    latitude: float | None = Field(None, ge=-90, le=90)
    longitude: float | None = Field(None, ge=-180, le=180)

    @model_validator(mode="after")
    def coordinate_pair(self):
        if self.action == "set" and (self.latitude is None or self.longitude is None):
            raise ValueError("Set requires both latitude and longitude")
        if self.action != "set" and (self.latitude is not None or self.longitude is not None):
            raise ValueError("Reset/clear cannot include coordinates")
        return self


class LocationOut(BaseModel):
    latitude: float | None
    longitude: float | None
    geocode_precision: str | None
    geocode_source: str | None
    geocoded_at: datetime | None
    location_set_by: UUID | None
    can_reset_location: bool
    warnings: list[str] = Field(default_factory=list)
    actor_is_fallback: bool = False
