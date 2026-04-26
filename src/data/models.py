"""Pydantic models for travel plan validator (main app + VRPTW engine)."""
from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings


# ---------------------------------------------------------------------------
# Main application models
# ---------------------------------------------------------------------------


class POI(BaseModel):
    poi_id: str
    name: str
    lat: float
    lng: float
    open_start: str  # HH:MM
    open_end: str    # HH:MM
    duration_min: int
    category: str = ""

    @field_validator("poi_id")
    @classmethod
    def poi_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("poi_id must not be empty")
        return v

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError(f"Latitude must be in [-90, 90], got {v}")
        return v

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError(f"Longitude must be in [-180, 180], got {v}")
        return v

    @field_validator("open_start", "open_end")
    @classmethod
    def validate_hhmm(cls, v: str) -> str:
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            raise ValueError(f"Time must be HH:MM format, got: {v!r}")
        h, m = int(v[:2]), int(v[3:])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"Invalid time value: {v!r}")
        return v

    @field_validator("duration_min")
    @classmethod
    def validate_duration(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("duration_min must be > 0")
        return v


class PlaceInput(BaseModel):
    name: str
    stay_minutes: int
    visit_order: int

    @field_validator("stay_minutes")
    @classmethod
    def validate_stay(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("stay_minutes must be > 0")
        if v > 720:
            raise ValueError("stay_minutes must be <= 720 (12 hours)")
        return v

    @field_validator("visit_order")
    @classmethod
    def validate_order(cls, v: int) -> int:
        if v < 1:
            raise ValueError("visit_order must be >= 1")
        return v


class ItineraryPlan(BaseModel):
    places: list[PlaceInput]
    transport: Literal["transit", "car", "walk"]
    travel_type: Literal["cultural", "nature", "shopping", "food", "adventure"]
    date: str  # YYYY-MM-DD

    @field_validator("places")
    @classmethod
    def validate_place_count(cls, v: list[PlaceInput]) -> list[PlaceInput]:
        if len(v) < 4:
            raise ValueError("ItineraryPlan must have at least 4 places")
        if len(v) > 8:
            raise ValueError("ItineraryPlan must have at most 8 places")
        return v

    @computed_field
    def plan_id(self) -> str:
        key = "_".join(p.name for p in sorted(self.places, key=lambda x: x.visit_order)) + self.date
        return hashlib.sha256(key.encode()).hexdigest()[:12]


class ValidationResult(BaseModel):
    plan_id: str
    final_score: int
    hard_fails: list[str]
    warnings: list[str]
    explanations: list[str] = []

    @field_validator("final_score")
    @classmethod
    def validate_score_range(cls, v: int) -> int:
        if not 0 <= v <= 100:
            raise ValueError("final_score must be in [0, 100]")
        return v

    @model_validator(mode="after")
    def hard_fail_score_cap(self) -> "ValidationResult":
        if self.hard_fails and self.final_score >= 60:
            raise ValueError("final_score must be <= 59 when hard_fails are present")
        return self


class Settings(BaseSettings):
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"
    tour_api_key: str = ""
    kakao_rest_api_key: str = ""
    kakao_mobility_key: str = ""
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}


# ---------------------------------------------------------------------------
# VRPTW engine models
# ---------------------------------------------------------------------------


class VRPTWPlace(BaseModel):
    name: str
    lng: float
    lat: float
    open: str   # HH:MM
    close: str  # HH:MM
    stay_duration: int  # minutes; 0 allowed for depot
    is_depot: bool = False

    @field_validator("open", "close")
    @classmethod
    def validate_hhmm(cls, v: str) -> str:
        if not re.fullmatch(r"\d{2}:\d{2}", v):
            raise ValueError(f"Time must be HH:MM format, got: {v!r}")
        h, m = int(v[:2]), int(v[3:])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"Invalid time value: {v!r}")
        return v

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError(f"Latitude must be [-90, 90], got {v}")
        return v

    @field_validator("lng")
    @classmethod
    def validate_lng(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError(f"Longitude must be [-180, 180], got {v}")
        return v

    @field_validator("stay_duration")
    @classmethod
    def validate_stay(cls, v: int) -> int:
        if v < 0:
            raise ValueError("stay_duration must be >= 0")
        return v

    @property
    def open_minutes(self) -> int:
        h, m = int(self.open[:2]), int(self.open[3:])
        return h * 60 + m

    @property
    def close_minutes(self) -> int:
        h, m = int(self.close[:2]), int(self.close[3:])
        return h * 60 + m


class VRPTWDay(BaseModel):
    places: list[VRPTWPlace]

    @field_validator("places")
    @classmethod
    def at_least_one(cls, v: list[VRPTWPlace]) -> list[VRPTWPlace]:
        if len(v) < 1:
            raise ValueError("Each day must have at least one place")
        return v


class VRPTWRequest(BaseModel):
    days: list[VRPTWDay]

    @field_validator("days")
    @classmethod
    def at_least_one_day(cls, v: list[VRPTWDay]) -> list[VRPTWDay]:
        if len(v) < 1:
            raise ValueError("Request must have at least one day")
        return v


class DeepDiveItem(BaseModel):
    fact: str
    rule: str
    risk: Literal["OK", "WARNING", "CRITICAL"]
    suggestion: str


class DayRouteComparison(BaseModel):
    day_index: int
    user_order: list[str]        # place names in user order
    optimal_order: list[str] | None  # None when ortools unavailable
    user_travel_seconds: int
    optimal_travel_seconds: int | None


class VRPTWResult(BaseModel):
    risk_score: int                          # 0–100
    passed: bool                             # risk_score >= 60
    user_total_travel_seconds: int
    optimal_total_travel_seconds: int | None
    efficiency_gap: float | None             # (user - optimal) / optimal
    optimal_route: list[DayRouteComparison] | None
    deep_dive: list[DeepDiveItem]
    summary: str
