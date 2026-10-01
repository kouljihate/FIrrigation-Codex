"""Pydantic validation schemas for API endpoints."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class SectorSave(BaseModel):
    code: str = Field(..., min_length=1, max_length=50)
    coords: str = Field(..., min_length=1)

    @field_validator("coords")
    @classmethod
    def validate_coords(cls, v: str) -> str:
        lines = [line.strip() for line in v.splitlines() if line.strip()]
        if len(lines) < 3:
            raise ValueError("need at least 3 coordinate lines")
        for line in lines:
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                raise ValueError(f"bad line: {line}")
            try:
                float(parts[0])
                float(parts[1])
            except ValueError:
                raise ValueError(f"not a number: {line}")
        return v


class ZoneBuild(BaseModel):
    n_parts: int = Field(default=3, ge=1, le=20)
    offset: float = Field(default=0.0, ge=0)
    split_mode: str = Field(default="contour")

    @field_validator("split_mode")
    @classmethod
    def validate_split_mode(cls, v: str) -> str:
        if v not in ("contour", "fan", "strip"):
            raise ValueError(f"unknown split_mode: {v}")
        return v


class MainlineBuild(BaseModel):
    offset: float = Field(default=5.0, ge=0)
    diameter: int = Field(default=75, gt=0)


class SubmainBuild(BaseModel):
    offset: float = Field(default=5.0, ge=0)
    diameter: int = Field(default=32, gt=0)


class RowBuild(BaseModel):
    spacing: float = Field(default=4.0, gt=0)
    offset: float = Field(default=2.0, ge=0)


class TreePlace(BaseModel):
    spacing: float = Field(default=4.0, gt=0)
    fig_pct: int = Field(default=20, ge=0, le=100)


class DriplineBuild(BaseModel):
    emitter_spacing: float = Field(default=0.5, gt=0)


class BasinCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    lon: float
    lat: float
    length: float = Field(default=30.0, gt=0)
    width: float = Field(default=30.0, gt=0)
    depth: float = Field(default=2.0, gt=0)
    elev: float = Field(default=0.0)

    @model_validator(mode="before")
    @classmethod
    def remove_empty_strings(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v != ""}
        return data


class WellCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    lon: float
    lat: float
    elev: float = Field(default=0.0)
    depth: float = Field(default=50.0, gt=0)

    @model_validator(mode="before")
    @classmethod
    def remove_empty_strings(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v != ""}
        return data


# ------------------------------------------------------- water & basin step
WATER_SOURCE_TYPES: tuple[str, ...] = ("well", "river", "basin", "other")
BASIN_SOURCE_TYPE = "basin"
POINT_SOURCE_TYPES: tuple[str, ...] = tuple(
    t for t in WATER_SOURCE_TYPES if t != BASIN_SOURCE_TYPE
)
# display order in the Water & Basin table
SOURCE_TYPE_ORDER: tuple[str, ...] = WATER_SOURCE_TYPES

SOURCE_TYPE_LABELS: dict[str, tuple[str, str]] = {
    "well":   ("Well", "بئر"),
    "river":  ("River", "نهر"),
    "basin":  ("Basin", "حوض"),
    "other":  ("Other water source", "مصدر مياه آخر"),
}

SOURCE_TYPE_ICONS: dict[str, str] = {
    "well": "🕳️", "river": "🏞️", "basin": "🛢️", "other": "💧",
}

SOURCE_TYPE_BADGES: dict[str, str] = {
    "well":  "text-bg-primary",
    "river": "text-bg-info",
    "basin": "text-bg-success",
    "other": "text-bg-secondary",
}


class WaterSourceCreate(BaseModel):
    """Well / river / basin / other water source (Step 02)."""

    name: str = Field(..., min_length=1, max_length=100)
    source_type: str = Field(default="well")
    lon: float
    lat: float
    elev: float = Field(default=0.0)
    depth: float = Field(default=0.0)
    length: float = Field(default=0.0, ge=0)
    width: float = Field(default=0.0, ge=0)
    discharge: float = Field(default=0.0, ge=0)
    notes: str = Field(default="", max_length=500)

    @field_validator("source_type")
    @classmethod
    def validate_source_type(cls, v: str) -> str:
        v = (v or "well").strip().lower()
        if v not in WATER_SOURCE_TYPES:
            raise ValueError(
                f"unknown source_type: {v} "
                f"(expected one of {', '.join(WATER_SOURCE_TYPES)})"
            )
        return v

    @field_validator("lon")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not -180.0 <= v <= 180.0:
            raise ValueError("longitude must be between -180 and 180")
        return v

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not -90.0 <= v <= 90.0:
            raise ValueError("latitude must be between -90 and 90")
        return v

    @model_validator(mode="before")
    @classmethod
    def remove_empty_strings(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if v != ""}
        return data

    @model_validator(mode="after")
    def basin_needs_size(self):
        if self.source_type == BASIN_SOURCE_TYPE and (self.length <= 0 or self.width <= 0):
            raise ValueError("a basin needs a length and a width greater than 0")
        return self


class NewProject(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=100)


def validate_json(model: type[BaseModel]) -> Any:
    """Decorator to validate request JSON against a Pydantic model."""
    from functools import wraps
    from flask import request, jsonify

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not request.is_json:
                return jsonify({"ok": False, "error": "Content-Type must be application/json"}), 400
            try:
                data = model(**request.get_json())
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            return f(data, *args, **kwargs)
        return wrapper
    return decorator


def validate_form(model: type[BaseModel]) -> Any:
    """Decorator to validate request form data against a Pydantic model."""
    from functools import wraps
    from flask import request, jsonify

    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            try:
                data = model(**request.form.to_dict())
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            return f(data, *args, **kwargs)
        return wrapper
    return decorator