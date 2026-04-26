"""Pydantic models for VRPTW engine input/output."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator


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
