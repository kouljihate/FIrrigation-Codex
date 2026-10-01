"""Tests for core geometry algorithms."""
from __future__ import annotations

import math

import pytest
from shapely.geometry import Polygon

from core.rows import build_rows
from core.trees import place_trees_on_row
from core.driplines import dripline_from_row
from core.geometry import clean_polygon, fall_direction, inward_offset
from routes.geometry import _ring_area_m2
from core.piping import direct_or_detour
from routes.field import _projection
from routes.project import _ring_area_m2


class TestRingArea:
    def test_square_ring_area(self):
        """Test area calculation for a square (1 degree ~ 111km at equator)."""
        # 1x1 degree square at equator ≈ 111km x 111km = 12.3M km² = 1.23e13 m²
        ring = [
            [0, 0],
            [1, 0],
            [1, 1],
            [0, 1],
            [0, 0],
        ]
        area = _ring_area_m2(ring)
        # At equator: 1 deg ≈ 111,320 m
        expected = 111320 * 111320  # ≈ 1.24e10 m²
        assert abs(area - expected) / expected < 0.02  # within 2%

    def test_small_polygon(self):
        """Test with a small polygon (0.001 deg ≈ 111m)."""
        ring = [
            [0, 0],
            [0.001, 0],
            [0.001, 0.001],
            [0, 0.001],
            [0, 0],
        ]
        area = _ring_area_m2(ring)
        expected = 111.32 * 111.32  # ≈ 12392 m²
        assert abs(area - expected) / expected < 0.05

    def test_import_area_uses_square_metres_at_mid_latitude(self):
        ring = [
            [2.0, 48.0],
            [2.001, 48.0],
            [2.001, 48.001],
            [2.0, 48.001],
            [2.0, 48.0],
        ]
        area = _ring_area_m2(ring)
        assert 8_000 < area < 9_000


class TestRows:
    def test_build_rows_simple_square(self):
        """Test row generation in a simple square zone."""
        # Square zone 100m x 100m (in local coords)
        poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        # Fall direction pointing down (south)
        rows = build_rows(poly, fall_ux=0, fall_uy=-1, spacing_m=10, first_offset_m=5)

        # Should have 10 rows (100m / 10m spacing)
        assert len(rows) == 10

        # First row should be at y=95 (100 - 5 offset)
        # Last row should be at y=5
        for ri, seg in rows:
            assert seg[0][1] == seg[1][1]  # Horizontal rows
            x0, x1 = seg[0][0], seg[1][0]
            assert x0 == 0 and x1 == 100  # Full width

    def test_build_rows_with_offset(self):
        """Test that first_offset is respected."""
        poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        rows = build_rows(poly, fall_ux=0, fall_uy=-1, spacing_m=20, first_offset_m=15)

        # First row at y=85 (100-15), then 65, 45, 25, 5 = 5 rows
        assert len(rows) == 5
        assert rows[0][1][0][1] == 85
        assert rows[-1][1][0][1] == 5


class TestTrees:
    def test_place_trees_on_row_basic(self):
        """Test basic tree placement."""
        start = (0, 0)
        end = (100, 0)
        trees = place_trees_on_row(start, end, spacing_m=10, center=True)

        # 100m / 10m = 10 segments, 11 trees with center=True
        # With center=True: margin = (100 - 10*10)/2 = 0, so trees at 0, 10, 20... 100
        assert len(trees) == 11
        assert trees[0] == (0.0, 0.0)
        assert trees[-1] == (100.0, 0.0)

    def test_place_trees_on_row_no_center(self):
        """Test tree placement without centering."""
        start = (0, 0)
        end = (100, 0)
        trees = place_trees_on_row(start, end, spacing_m=10, center=False)

        # 100m / 10m = 10 trees starting at 0
        assert len(trees) == 11
        assert trees[0] == (0, 0)
        assert trees[-1] == (100, 0)

    def test_place_trees_short_row(self):
        """Test row shorter than spacing."""
        start = (0, 0)
        end = (4, 0)  # Less than spacing*0.5 = 5
        trees = place_trees_on_row(start, end, spacing_m=10)
        assert len(trees) == 0


class TestDriplines:
    def test_dripline_from_row(self):
        """Test dripline generation from row."""
        start = (0, 0)
        end = (100, 0)
        dl = dripline_from_row(start, end, emitter_spacing_m=0.5)

        assert dl["length_m"] == 100.0
        assert dl["emitter_count"] == 201  # 100/0.5 + 1
        assert dl["geometry"] == [start, end]

    def test_wgs84_row_length_is_converted_before_spacing(self):
        start = (2.0, 48.0)
        end = (2.001, 48.0)
        to_local, _ = _projection([start, end])
        start_m = to_local(*start)
        end_m = to_local(*end)

        dripline = dripline_from_row(start_m, end_m, emitter_spacing_m=0.5)
        trees = place_trees_on_row(start_m, end_m, spacing_m=10)

        assert 70 < dripline["length_m"] < 80
        assert 140 < dripline["emitter_count"] < 170
        assert 7 <= len(trees) <= 9


class TestGeometry:
    def test_clean_polygon_valid(self):
        """Test that valid polygons pass through unchanged."""
        poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        cleaned = clean_polygon(poly)
        assert cleaned.equals(poly)

    def test_clean_polygon_bowtie(self):
        """Test that bowtie (self-intersecting) polygons are fixed."""
        # Bowtie shape
        poly = Polygon([(0, 0), (10, 10), (0, 10), (10, 0)])
        assert not poly.is_valid
        cleaned = clean_polygon(poly)
        assert cleaned.is_valid
        assert cleaned.area > 0

    def test_fall_direction_flat(self):
        """Test fall direction on flat terrain returns default."""
        poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        elevations = [100.0] * 4
        ux, uy = fall_direction(poly, elevations)
        assert (ux, uy) == (1.0, 0.0)  # Default fallback

    def test_fall_direction_slope(self):
        """Test fall direction on sloped terrain."""
        poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        # Elevation decreases toward positive Y (north)
        elevations = [100, 100, 90, 90]
        ux, uy = fall_direction(poly, elevations)
        # Should point in positive Y direction (north/downhill where elevation drops)
        assert uy > 0  # Pointing downhill (toward lower elevation)

    def test_inward_offset(self):
        """Test inward offset shrinks polygon."""
        poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        inner = inward_offset(poly, 10)
        assert inner.area < poly.area
        # Should be 80x80 = 6400
        assert abs(inner.area - 6400) < 1

    def test_inward_offset_too_large(self):
        """Test that too large offset raises error."""
        poly = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        with pytest.raises(ValueError):
            inward_offset(poly, 100)


class TestPiping:
    def test_direct_path_inside(self):
        """Test direct path when line is inside polygon."""
        poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        inner = poly  # Same for this test
        start = (10, 10)
        end = (90, 90)

        path = direct_or_detour(poly, inner, start, end)
        assert len(path) == 2
        assert path[0] == start
        assert path[1] == end

    def test_detour_outside_outer_boundary(self):
        """Test detour when direct path crosses OUTER polygon boundary."""
        poly = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        inner = Polygon([(10, 10), (90, 10), (90, 90), (10, 90)])
        # Start and end outside outer polygon
        start = (-10, 50)   # West of outer
        end = (110, 50)     # East of outer

        path = direct_or_detour(poly, inner, start, end)
        # Should go around outer boundary
        assert len(path) > 2
        assert path[0] == start
        assert path[-1] == end


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
