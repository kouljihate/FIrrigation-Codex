"""Geometry section: Sectors, Zones, Valves."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from flask import jsonify
from db.connection import get_db

import numpy as np
from flask import (
    Blueprint, current_app, flash, redirect, render_template,
    request, session, url_for,
)
from shapely.geometry import LineString, Polygon, mapping, shape
from shapely.ops import split, unary_union
from shapely.validation import make_valid

from core.geometry import clean_polygon, fall_direction
from core.valve_rules import MV_GROUPS, zv_name
from core.validation import validate_form, SectorSave, ZoneBuild
from core.async_tasks import submit_async_task, get_task_status
from db import queries, repository
from db.connection import get_db


bp = Blueprint("geometry", __name__, url_prefix="/geometry")


# ---------------------------------------------------------------- sectors
@bp.route("/sectors")
def sectors():
    pid = session.get("project_id", "")
    if not pid:
        return redirect(url_for("home.home"))

    rows = queries.get_sectors(pid)
    sectors = []
    for s in rows:
        ring = s["geom"]["coordinates"][0]
        sectors.append({
            "code":  s.get("sector_code") or s["name"],
            "name":  s["name"],
            "coords_text": "\n".join(f"{x:.7f},{y:.7f}" for x, y in ring),
            "vertices": len(ring),
            "area_m2":  s.get("area_m2", 0),
            "color": s.get("color", "#00bcd4"),
        })
    return render_template("geometry/sectors_enhanced.html", sectors=sectors)


@bp.route("/sectors/enhanced")
def sectors_enhanced():
    """Enhanced sector management with interactive map."""
    pid = session.get("project_id", "")
    if not pid:
        return redirect(url_for("home.home"))

    rows = queries.get_sectors(pid)
    sectors = []
    for s in rows:
        ring = s["geom"]["coordinates"][0]
        sectors.append({
            "code":  s.get("sector_code") or s["name"],
            "name":  s["name"],
            "coords_text": "\n".join(f"{x:.7f},{y:.7f}" for x, y in ring),
            "vertices": len(ring),
            "area_m2":  s.get("area_m2", 0),
            "color": s.get("color", "#00bcd4"),
        })
    return render_template("geometry/sectors_enhanced.html", sectors=sectors)


@bp.route("/sectors/save", methods=["POST"])
@validate_form(SectorSave)
def save_sector(data: SectorSave):
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400

    code = data.code
    coords_text = data.coords

    # parse lines "lon,lat" (or "lon,lat,ele")
    ring = []
    for line in coords_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        lon = float(parts[0])
        lat = float(parts[1])
        ring.append([lon, lat])

    if len(ring) < 3:
        return jsonify({"ok": False, "error": "need at least 3 points"}), 400

    # auto-close ring
    if ring[0] != ring[-1]:
        ring.append(ring[0])

    # compute area via lon/lat -> meters approximation
    area_m2 = _ring_area_m2(ring)

    revision = repository.new_revision(pid, "03_sectors_edit",
                                       f"Edit {code}")
    now = datetime.now(timezone.utc)

    repository.upsert("sectors",
        {"project_id": pid, "sector_code": code},
        {
            "project_id": pid,
            "name": code,
            "sector_code": code,
            "geom": {"type": "Polygon", "coordinates": [ring]},
            "area_m2": area_m2,
            "revision_id": revision,
            "updated_at": now,
        })

    return jsonify({
        "ok": True,
        "vertices": len(ring) - 1,   # excluding closing duplicate
        "area_m2": area_m2,
        "area_ha": area_m2 / 10000.0,
    })


@bp.route("/sectors/add", methods=["POST"])
@validate_form(SectorSave)
def add_sector(data: SectorSave):
    """Add a new sector."""
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400

    code = data.code
    coords_text = data.coords

    # Check if sector already exists
    db = get_db()
    exists = db.sectors.find_one({"project_id": pid, "sector_code": code})
    if exists:
        return jsonify({"ok": False, "error": f"Sector '{code}' already exists"}), 400

    # Parse coords
    ring = []
    for line in coords_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split(",")]
        lon = float(parts[0])
        lat = float(parts[1])
        ring.append([lon, lat])

    if len(ring) < 3:
        return jsonify({"ok": False, "error": "need at least 3 points"}), 400

    # Auto-close ring
    if ring[0] != ring[-1]:
        ring.append(ring[0])

    area_m2 = _ring_area_m2(ring)

    revision = repository.new_revision(pid, "03_sectors_add", f"Add {code}")
    now = datetime.now(timezone.utc)

    repository.upsert("sectors",
        {"project_id": pid, "sector_code": code},
        {
            "project_id": pid,
            "name": code,
            "sector_code": code,
            "geom": {"type": "Polygon", "coordinates": [ring]},
            "area_m2": area_m2,
            "revision_id": revision,
            "updated_at": now,
        })

    return jsonify({
        "ok": True,
        "code": code,
        "vertices": len(ring) - 1,
        "area_m2": area_m2,
        "area_ha": area_m2 / 10000.0,
    })


@bp.route("/sectors/delete", methods=["POST"])
def delete_sector():
    """Delete a sector by code."""
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400

    code = request.form.get("code", "").strip()
    if not code:
        return jsonify({"ok": False, "error": "missing code"}), 400

    db = get_db()
    result = db.sectors.delete_one({"project_id": pid, "sector_code": code})
    if result.deleted_count == 0:
        return jsonify({"ok": False, "error": f"Sector '{code}' not found"}), 404

    # Also delete dependent zones, valves, etc. for this sector
    revision = repository.new_revision(pid, "03_sectors_delete", f"Delete {code}")
    db.zones.delete_many({"project_id": pid, "sector_code": code})
    db.valves.delete_many({"project_id": pid, "sector_code": code})

    return jsonify({"ok": True, "deleted": code})


@bp.route("/sectors/geojson")
def sectors_geojson():
    """Return all sectors as GeoJSON for map display."""
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"type": "FeatureCollection", "features": []})

    features = []
    for s in queries.get_sectors(pid):
        geom = s.get("geom")
        if not geom:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "code": s.get("sector_code") or s["name"],
                "name": s["name"],
                "area_m2": s.get("area_m2", 0),
            },
            "geometry": geom,
        })
    return jsonify({"type": "FeatureCollection", "features": features})


@bp.route("/sectors/<code>/geojson")
def sector_geojson(code: str):
    """Return a single sector as GeoJSON."""
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"type": "FeatureCollection", "features": []})

    db = get_db()
    s = db.sectors.find_one({"project_id": pid, "sector_code": code})
    if not s:
        return jsonify({"type": "FeatureCollection", "features": []})

    geom = s.get("geom")
    if not geom:
        return jsonify({"type": "FeatureCollection", "features": []})

    return jsonify({
        "type": "Feature",
        "properties": {
            "code": s.get("sector_code") or s["name"],
            "name": s["name"],
            "area_m2": s.get("area_m2", 0),
        },
        "geometry": geom,
    })


def _ring_area_m2(ring):
    """Approximate polygon area in m² using lat-corrected shoelace."""
    if len(ring) < 4:
        return 0.0
    lat0 = sum(p[1] for p in ring) / len(ring)
    # scale factors (m per degree) at this latitude
    import math
    R = 6378137.0
    m_per_deg_lat = math.pi * R / 180.0
    m_per_deg_lon = m_per_deg_lat * math.cos(math.radians(lat0))

    s = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0] * m_per_deg_lon, ring[i][1] * m_per_deg_lat
        x2, y2 = ring[i+1][0] * m_per_deg_lon, ring[i+1][1] * m_per_deg_lat
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _polygon_from_coordinates(coordinates: list) -> Polygon:
    """Validate a WGS84 exterior ring and return one valid polygon."""
    if len(coordinates) < 3:
        raise ValueError("a sector needs at least three points")
    ring = [[float(point[0]), float(point[1])] for point in coordinates]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    polygon = make_valid(Polygon(ring))
    if polygon.is_empty or polygon.geom_type != "Polygon" or polygon.area == 0:
        raise ValueError("sector geometry must be one non-empty polygon")
    return polygon


def _ring_from_text(coords_text: str) -> list[list[float]]:
    ring = []
    for raw_line in coords_text.splitlines():
        parts = [part.strip() for part in raw_line.split(",")]
        if len(parts) < 2 or not raw_line.strip():
            continue
        ring.append([float(parts[0]), float(parts[1])])
    return ring


def _sector_payload(code: str, polygon: Polygon, color: str, now, revision: int) -> dict:
    geometry = mapping(polygon)
    ring = geometry["coordinates"][0]
    return {
        "name": code,
        "sector_code": code,
        "geom": geometry,
        "area_m2": _ring_area_m2(ring),
        "color": color,
        "updated_at": now,
        "revision_id": revision,
    }


@bp.route("/sectors/apply", methods=["POST"])
def apply_sector_changes():
    """Validate and atomically apply staged sector edits from the map editor."""
    pid = session.get("project_id", "")
    payload = request.get_json(silent=True) or {}
    operations = payload.get("operations")
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400
    if not isinstance(operations, list) or not operations:
        return jsonify({"ok": False, "error": "no staged sector changes"}), 400

    db = get_db()
    documents = {
        document["sector_code"]: document
        for document in db.sectors.find({"project_id": pid})
    }

    try:
        for operation in operations:
            operation_type = operation.get("type")
            if operation_type == "update":
                old_code = str(operation.get("code", "")).strip()
                new_code = str(operation.get("new_code", old_code)).strip()
                if old_code not in documents or not new_code:
                    raise ValueError("sector update references an unknown or empty code")
                if new_code != old_code and new_code in documents:
                    raise ValueError(f"sector code '{new_code}' already exists")
                polygon = _polygon_from_coordinates(operation.get("coordinates") or [])
                document = documents.pop(old_code)
                document.update(_sector_payload(
                    new_code, polygon, operation.get("color", document.get("color", "#00bcd4")),
                    datetime.now(timezone.utc), 0,
                ))
                documents[new_code] = document
            elif operation_type == "delete":
                for code in operation.get("codes") or []:
                    if code not in documents:
                        raise ValueError(f"sector '{code}' no longer exists")
                    documents.pop(code)
            elif operation_type == "merge":
                codes = operation.get("codes") or []
                new_code = str(operation.get("new_code", "")).strip()
                if len(codes) != 2 or not new_code or any(code not in documents for code in codes):
                    raise ValueError("merge requires exactly two existing sectors and a new code")
                if new_code not in codes and new_code in documents:
                    raise ValueError(f"sector code '{new_code}' already exists")
                merged = unary_union([shape(documents[code]["geom"]) for code in codes])
                if merged.geom_type != "Polygon":
                    raise ValueError("selected sectors must touch to merge into one polygon")
                first_document = documents[codes[0]]
                for code in codes:
                    documents.pop(code)
                first_document.update(_sector_payload(
                    new_code, merged, operation.get("color", first_document.get("color", "#00bcd4")),
                    datetime.now(timezone.utc), 0,
                ))
                documents[new_code] = first_document
            elif operation_type == "split":
                code = str(operation.get("code", "")).strip()
                new_codes = [str(value).strip() for value in operation.get("new_codes") or []]
                line = operation.get("line") or []
                if code not in documents or len(new_codes) != 2 or not all(new_codes) or new_codes[0] == new_codes[1]:
                    raise ValueError("split requires one sector and two distinct new codes")
                if any(new_code in documents and new_code != code for new_code in new_codes):
                    raise ValueError("a split sector code already exists")
                if len(line) != 2:
                    raise ValueError("split requires two line coordinates")
                pieces = list(split(shape(documents[code]["geom"]), LineString(line)).geoms)
                if len(pieces) != 2 or any(piece.geom_type != "Polygon" for piece in pieces):
                    raise ValueError("split line must divide the sector into exactly two polygons")
                original = documents.pop(code)
                for new_code, piece in zip(new_codes, pieces):
                    document = original.copy()
                    document.update(_sector_payload(
                        new_code, piece, operation.get("color", original.get("color", "#00bcd4")),
                        datetime.now(timezone.utc), 0,
                    ))
                    documents[new_code] = document
            else:
                raise ValueError("unknown sector operation")
    except (TypeError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    revision = repository.new_revision(pid, "03_sectors_batch", "Validate and apply sector changes")
    now = datetime.now(timezone.utc)
    db.sectors.delete_many({"project_id": pid})
    for document in documents.values():
        document["project_id"] = pid
        document["revision_id"] = revision
        document["updated_at"] = now
    if documents:
        db.sectors.insert_many(list(documents.values()))

    for collection in ("zones", "valves", "pipes", "rows", "trees", "driplines", "manifolds", "bom_items"):
        repository.clear_step(pid, collection)

    return jsonify({"ok": True, "revision": revision, "sector_count": len(documents)})

# ---------------------------------------------------------------- zones
@bp.route("/zones", methods=["GET", "POST"])
@validate_form(ZoneBuild)
def zones(data: ZoneBuild | None = None):
    pid = session.get("project_id", "farm_v1")

    if request.method == "POST":
        assert data is not None
        # Check if async mode requested
        if request.form.get("async") == "1":
            task_id = submit_async_task(
                "build_zones",
                _do_build_zones,
                pid, data.n_parts, data.offset, data.split_mode,
                project_id=pid,
            )
            return jsonify({"ok": True, "task_id": task_id, "async": True})
        
        _do_build_zones(pid, data.n_parts, data.offset, data.split_mode)
        flash("Zones built.", "success")
        return redirect(url_for("geometry.zones"))

    rows = queries.get_zones(pid)
    table = []
    for z in rows:
        table.append({
            "name":     z["name"],
            "sector":   z.get("sector_code", ""),
            "area_m2":  round(z.get("area_m2", 0), 1),
        })
    return render_template("geometry/zones.html", zones=table)

def _do_build_zones(project_id: str, n_parts: int, offset: float,
                    split_mode: str = "contour") -> int:
    sectors = queries.get_sectors(project_id)
    if not sectors:
        return 0

    revision = repository.new_revision(
        project_id, "04_zones",
        f"Build {n_parts} zones/sector — split={split_mode}"
    )
    repository.clear_step(project_id, "zones")

    now = datetime.now(timezone.utc)
    R = 6371000.0
    total = 0

    for s in sectors:
        code = s.get("sector_code") or s["name"]
        ring = s["geom"]["coordinates"][0]
        pts_ll = [(x, y, 0.0) for x, y in ring]

        lon0 = sum(p[0] for p in pts_ll) / len(pts_ll)
        lat0 = sum(p[1] for p in pts_ll) / len(pts_ll)

        def to_local(lon, lat, _lon0=lon0, _lat0=lat0):
            x = math.radians(lon - _lon0) * R * math.cos(math.radians(_lat0))
            y = math.radians(lat - _lat0) * R
            return x, y

        pts_xy = [to_local(p[0], p[1]) for p in pts_ll]
        poly = clean_polygon(Polygon(pts_xy))

        if offset > 0:
            shrunk = poly.buffer(-offset, join_style=2)
            if not shrunk.is_empty:
                if shrunk.geom_type == "MultiPolygon":
                    shrunk = max(shrunk.geoms, key=lambda g: g.area)
                if shrunk.geom_type == "Polygon":
                    poly = shrunk

        # --- dispatch by split mode ---
        if split_mode == "contour":
            zones_xy = _split_contour(poly, n_parts)
        elif split_mode == "fan":
            zones_xy = _split_fan(poly, n_parts)
        elif split_mode == "strip":
            zones_xy = _split_strip(poly, n_parts)
        else:
            zones_xy = _split_contour(poly, n_parts)

        def to_lonlat(x, y, _lon0=lon0, _lat0=lat0):
            lon = _lon0 + math.degrees(x / (R * math.cos(math.radians(_lat0))))
            lat = _lat0 + math.degrees(y / R)
            return lon, lat

        for j, z in enumerate(zones_xy, start=1):
            if z is None or z.is_empty:
                continue
            if z.geom_type == "MultiPolygon":
                z = max(z.geoms, key=lambda g: g.area)
            if z.geom_type != "Polygon":
                continue

            ring_ll = [list(to_lonlat(x, y)) for x, y in z.exterior.coords]
            if ring_ll[0] != ring_ll[-1]:
                ring_ll.append(ring_ll[0])

            geom = {"type": "Polygon", "coordinates": [ring_ll]}
            zname = f"{code}-Z{j}"
            repository.upsert("zones",
                {"project_id": project_id, "name": zname},
                {"project_id": project_id, "name": zname,
                 "sector_code": code, "zone_index": j,
                 "geom": geom, "area_m2": z.area,
                 "split_mode": split_mode,
                 "revision_id": revision,
                 "created_at": now, "updated_at": now})
            total += 1

    return total


# ---------------------------------------------------------------- strategies

def _split_contour(poly: Polygon, n_parts: int):
    """
    Equal-area bands perpendicular to the fall line.
    Since we don't carry elevations here, fall direction defaults to
    'largest variance axis' — a stable proxy.
    """
    coords = list(poly.exterior.coords)
    # estimate principal axis via covariance
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in coords)
    # principal direction angle (largest variance = the long axis)
    theta = 0.5 * math.atan2(2 * sxy, sxx - syy)
    # fall direction: perpendicular to long axis
    fall_ux = -math.sin(theta)
    fall_uy = math.cos(theta)

    return _split_by_direction(poly, n_parts, fall_ux, fall_uy)


def _split_fan(poly: Polygon, n_parts: int):
    """
    Equal-area fan: rays radiating from the centroid.
    Zones look like pie slices. Uses area sweep.
    """
    cx, cy = poly.centroid.x, poly.centroid.y
    # angles of each exterior vertex around the centroid
    coords = list(poly.exterior.coords)[:-1]
    angles = []
    for x, y in coords:
        a = math.atan2(y - cy, x - cx)
        if a < 0:
            a += 2 * math.pi
        angles.append(a)

    # target area per zone
    target = poly.area / n_parts

    # We'll sweep the full circle and find angles that accumulate `target`.
    # Simplify: sample 720 angles, integrate area by triangulating
    # with the centroid.
    samples = 720
    ang = [2 * math.pi * i / samples for i in range(samples + 1)]
    cum_area = [0.0] * (samples + 1)
    for i in range(samples):
        a0, a1 = ang[i], ang[i + 1]
        # tiny sector from centroid at [a0, a1]
        # approximate: use triangle (centroid, edge0, edge1) where edge
        # points are intersections of ray with polygon — but that's heavy.
        # Simpler: area of circle sector capped at a small angle,
        # scaled by whether the ray direction is inside the polygon.
        # Use radial intersection with the polygon.
        r0 = _ray_polygon_distance(poly, cx, cy, a0)
        r1 = _ray_polygon_distance(poly, cx, cy, a1)
        area = 0.5 * r0 * r1 * math.sin(a1 - a0) if a1 > a0 else 0
        cum_area[i + 1] = cum_area[i] + area

    total = cum_area[-1] or poly.area
    cut_angles = []
    for k in range(1, n_parts):
        want = total * k / n_parts
        # find index
        idx = 0
        for i in range(len(cum_area)):
            if cum_area[i] >= want:
                idx = i
                break
        cut_angles.append(ang[idx])

    # build wedge polygons
    zones = []
    boundaries = [0.0] + cut_angles + [2 * math.pi]
    for i in range(n_parts):
        a0 = boundaries[i]
        a1 = boundaries[i + 1]
        # sample boundary points
        steps = max(2, int((a1 - a0) * 30))
        pts = [(cx, cy)]
        for s in range(steps + 1):
            a = a0 + (a1 - a0) * s / steps
            r = _ray_polygon_distance(poly, cx, cy, a)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
        wedge = Polygon(pts)
        clipped = wedge.intersection(poly)
        if clipped.is_empty:
            zones.append(None)
            continue
        if clipped.geom_type == "MultiPolygon":
            clipped = max(clipped.geoms, key=lambda g: g.area)
        zones.append(clipped if clipped.geom_type == "Polygon" else None)

    return zones


def _split_strip(poly: Polygon, n_parts: int):
    """
    Equal-area strips parallel to the longest edge of the polygon.
    """
    coords = list(poly.exterior.coords)[:-1]
    best_len = 0.0
    best_dir = (1.0, 0.0)
    for i in range(len(coords)):
        x1, y1 = coords[i]
        x2, y2 = coords[(i + 1) % len(coords)]
        dx, dy = x2 - x1, y2 - y1
        L = math.hypot(dx, dy)
        if L > best_len:
            best_len = L
            best_dir = (dx / L, dy / L)

    ux, uy = best_dir
    # fall direction for _split_by_direction is perpendicular to strips
    fall_ux, fall_uy = -uy, ux

    return _split_by_direction(poly, n_parts, fall_ux, fall_uy)


def _split_by_direction(poly: Polygon, n_parts: int,
                        fall_ux: float, fall_uy: float):
    """
    Cut the polygon into n equal-area bands perpendicular to
    (fall_ux, fall_uy). Returns a list of shapely Polygons.
    """
    theta = -math.pi / 2 - math.atan2(fall_uy, fall_ux)
    c, s = math.cos(theta), math.sin(theta)

    def rot(p):
        return (c * p[0] - s * p[1], s * p[0] + c * p[1])

    def rot_inv(p):
        return (c * p[0] + s * p[1], -s * p[0] + c * p[1])

    rot_poly = Polygon([rot(p) for p in poly.exterior.coords])
    if not rot_poly.is_valid:
        rot_poly = rot_poly.buffer(0)
    if rot_poly.geom_type == "MultiPolygon":
        rot_poly = max(rot_poly.geoms, key=lambda g: g.area)

    minx, miny, maxx, maxy = rot_poly.bounds
    target = rot_poly.area / n_parts

    def area_below(ycut):
        box = Polygon([(minx - 50, miny - 50),
                       (maxx + 50, miny - 50),
                       (maxx + 50, ycut),
                       (minx - 50, ycut)])
        return rot_poly.intersection(box).area

    cuts = []
    for k in range(1, n_parts):
        lo, hi = miny, maxy
        want = target * k
        for _ in range(60):
            mid = (lo + hi) / 2
            if area_below(mid) < want:
                lo = mid
            else:
                hi = mid
        cuts.append((lo + hi) / 2)
    cuts.sort()

    edges = [miny - 50] + cuts + [maxy + 50]
    zones = []
    for j in range(n_parts):
        y_lo = edges[n_parts - j - 1]
        y_hi = edges[n_parts - j]
        box = Polygon([(minx - 50, y_lo), (maxx + 50, y_lo),
                       (maxx + 50, y_hi), (minx - 50, y_hi)])
        zone = rot_poly.intersection(box)
        if zone.is_empty:
            zones.append(None)
            continue
        if zone.geom_type == "MultiPolygon":
            zone = max(zone.geoms, key=lambda g: g.area)
        if zone.geom_type != "Polygon":
            zones.append(None)
            continue
        back = [rot_inv(p) for p in zone.exterior.coords]
        zones.append(Polygon(back))
    return zones


def _ray_polygon_distance(poly: Polygon, cx: float, cy: float, ang: float) -> float:
    """Distance from (cx,cy) to the polygon boundary along direction `ang`."""
    maxR = 100000.0
    far = (cx + maxR * math.cos(ang), cy + maxR * math.sin(ang))
    ray = LineString([(cx, cy), far])
    inter = poly.exterior.intersection(ray)
    if inter.is_empty:
        return 0.0
    if inter.geom_type == "Point":
        return math.hypot(inter.x - cx, inter.y - cy)
    if inter.geom_type == "MultiPoint":
        pts = [(p.x, p.y) for p in inter.geoms]
    else:
        # LineString — take its end
        pts = list(inter.coords)
    return max(math.hypot(x - cx, y - cy) for x, y in pts)

# ---------------------------------------------------------------- valves
@bp.route("/valves", methods=["GET", "POST"])
def valves():
    pid = session.get("project_id", "farm_v1")

    if request.method == "POST":
        _build_valves(pid)
        flash("Valves built.", "success")
        return redirect(url_for("geometry.valves"))

    mvs = queries.get_valves(pid, "MV")
    zvs = queries.get_valves(pid, "ZV")
    return render_template("geometry/valves.html", mvs=mvs, zvs=zvs)


def _build_valves(project_id: str) -> None:
    sectors = queries.get_sectors(project_id)
    zones = queries.get_zones(project_id)
    if not sectors or not zones:
        flash("Need sectors and zones first.", "error")
        return

    revision = repository.new_revision(project_id, "05_valves", "Generate valves")
    repository.clear_step(project_id, "valves")

    now = datetime.now(timezone.utc)

    for mv, sector_codes in MV_GROUPS.items():
        first = sector_codes[0]
        sdoc = next((s for s in sectors
                     if (s.get("sector_code") or s["name"]) == first), None)
        if not sdoc:
            continue
        ring = sdoc["geom"]["coordinates"][0]
        lon = sum(p[0] for p in ring) / len(ring)
        lat = sum(p[1] for p in ring) / len(ring)
        repository.upsert("valves",
            {"project_id": project_id, "name": mv},
            {"project_id": project_id, "name": mv, "valve_type": "MV",
             "sector_code": first,
             "location": {"type": "Point", "coordinates": [lon, lat]},
             "diameter_mm": 50, "revision_id": revision,
             "created_at": now, "updated_at": now})

    for z in zones:
        code = z["sector_code"]
        zi = z["zone_index"]
        ring = z["geom"]["coordinates"][0]
        lon = sum(p[0] for p in ring) / len(ring)
        lat = sum(p[1] for p in ring) / len(ring)
        name = zv_name(code, zi)
        repository.upsert("valves",
            {"project_id": project_id, "name": name},
            {"project_id": project_id, "name": name, "valve_type": "ZV",
             "sector_code": code, "zone_name": z["name"],
             "location": {"type": "Point", "coordinates": [lon, lat]},
             "diameter_mm": 32, "revision_id": revision,
             "created_at": now, "updated_at": now})

@bp.route("/zones/build", methods=["POST"])
@validate_form(ZoneBuild)
def build_zones_api(data: ZoneBuild):
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400

    count = _do_build_zones(pid, data.n_parts, data.offset, data.split_mode)

    return jsonify({
        "ok": True,
        "zones": count,
        "n_parts": data.n_parts,
        "offset": data.offset,
        "split_mode": data.split_mode,
    })


@bp.route("/tasks/<task_id>")
def task_status(task_id: str):
    """Get status of an async task."""
    status = get_task_status(task_id)
    if not status:
        return jsonify({"ok": False, "error": "Task not found"}), 404
    return jsonify({"ok": True, "task": status})


@bp.route("/tasks")
def project_tasks():
    """Get all tasks for current project."""
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"ok": False, "error": "no project"}), 400
    tasks = get_project_tasks(pid)
    return jsonify({"ok": True, "tasks": tasks})
