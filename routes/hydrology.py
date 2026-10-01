"""Hydrology section: Mainline, Sub-mains, Manifold."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from flask import (
    Blueprint, current_app, flash, redirect, render_template,
    request, session, url_for,
)
from shapely.geometry import Polygon

from core.geometry import clean_polygon, inward_offset
from core.piping import direct_or_detour
from core.valve_rules import MV_OF_SECTOR
from core.validation import validate_form, MainlineBuild, SubmainBuild
from db import queries, repository
from db.connection import get_db


bp = Blueprint("hydrology", __name__, url_prefix="/hydrology")


def _projection(ring):
    lon0 = sum(p[0] for p in ring) / len(ring)
    lat0 = sum(p[1] for p in ring) / len(ring)
    R = 6371000.0

    def to_local(lon, lat):
        x = math.radians(lon - lon0) * R * math.cos(math.radians(lat0))
        y = math.radians(lat - lat0) * R
        return x, y

    def to_lonlat(x, y):
        return (lon0 + math.degrees(x / (R * math.cos(math.radians(lat0)))),
                lat0 + math.degrees(y / R))

    return to_local, to_lonlat


# ---------------------------------------------------------------- mainline
@bp.route("/mainline", methods=["GET", "POST"])
@validate_form(MainlineBuild)
def mainline(data: MainlineBuild | None = None):
    pid = session.get("project_id", "farm_v1")

    if request.method == "POST":
        assert data is not None
        _build_mainline(pid, data.offset, data.diameter)
        flash("Mainline built.", "success")
        return redirect(url_for("hydrology.mainline"))

    pipes = [p for p in queries.get_pipes(pid, "mainline")]
    return render_template("hydrology/mainline.html", pipes=pipes)


def _build_mainline(project_id: str, offset: float, diameter: int) -> None:
    db = get_db()
    prop = db.property.find_one({"project_id": project_id})
    basin = db.basins.find_one({"project_id": project_id})
    mvs = {v["name"]: v for v in queries.get_valves(project_id, "MV")}
    if not prop or not basin or not mvs:
        flash("Need P1, basin, and MV valves first.", "error")
        return

    ring = prop["geom"]["coordinates"][0]
    to_local, to_lonlat = _projection(ring)
    p1_xy = clean_polygon(Polygon([to_local(p[0], p[1]) for p in ring]))
    inner = inward_offset(p1_xy, offset)

    basin_ring = basin["geom"]["coordinates"][0]
    b_lon = sum(p[0] for p in basin_ring) / len(basin_ring)
    b_lat = sum(p[1] for p in basin_ring) / len(basin_ring)
    basin_xy = to_local(b_lon, b_lat)

    revision = repository.new_revision(project_id, "06_mainline",
                                       f"Mainline offset={offset}m Ø{diameter}")
    repository.delete_where("pipes",
        {"project_id": project_id, "pipe_type": "mainline"})

    now = datetime.now(timezone.utc)
    for mv_name, mv in mvs.items():
        mv_lon, mv_lat = mv["location"]["coordinates"]
        mv_xy = to_local(mv_lon, mv_lat)
        path = direct_or_detour(p1_xy, inner, basin_xy, mv_xy)
        path_ll = [list(to_lonlat(x, y)) for x, y in path]

        length = sum(
            math.hypot(path[i + 1][0] - path[i][0],
                       path[i + 1][1] - path[i][1])
            for i in range(len(path) - 1)
        )

        name = f"MAIN-BASIN-{mv_name}"
        repository.upsert("pipes",
            {"project_id": project_id, "name": name},
            {"project_id": project_id, "name": name,
             "pipe_type": "mainline",
             "geom": {"type": "LineString",
                      "coordinates": [list(p) for p in path_ll]},
             "length_m": length, "diameter_mm": diameter,
             "material": "HDPE PE100 PN10",
             "revision_id": revision,
             "created_at": now, "updated_at": now})

    current_app.logger.info("Mainline built for %s", project_id)


# ---------------------------------------------------------------- sub-mains
@bp.route("/submains", methods=["GET", "POST"])
@validate_form(SubmainBuild)
def submains(data: SubmainBuild | None = None):
    pid = session.get("project_id", "farm_v1")

    if request.method == "POST":
        assert data is not None
        _build_submains(pid, data.offset, data.diameter)
        flash("Sub-mains built.", "success")
        return redirect(url_for("hydrology.submains"))

    pipes = queries.get_pipes(pid, "submain")
    return render_template("hydrology/submains.html", pipes=pipes)


def _build_submains(project_id: str, offset: float, diameter: int) -> None:
    db = get_db()
    prop = db.property.find_one({"project_id": project_id})
    mvs = {v["name"]: v for v in queries.get_valves(project_id, "MV")}
    zvs = queries.get_valves(project_id, "ZV")
    if not prop or not mvs or not zvs:
        flash("Need P1, MV valves, and ZV valves first.", "error")
        return

    ring = prop["geom"]["coordinates"][0]
    to_local, to_lonlat = _projection(ring)
    p1_xy = clean_polygon(Polygon([to_local(p[0], p[1]) for p in ring]))
    inner = inward_offset(p1_xy, offset)

    revision = repository.new_revision(project_id, "07_submains",
                                       f"Sub-mains Ø{diameter}")
    repository.delete_where("pipes",
        {"project_id": project_id, "pipe_type": "submain"})

    now = datetime.now(timezone.utc)
    for zv in zvs:
        code = zv["sector_code"]
        mv_name = MV_OF_SECTOR.get(code)
        if mv_name not in mvs:
            continue
        mv = mvs[mv_name]
        mv_lon, mv_lat = mv["location"]["coordinates"]
        zv_lon, zv_lat = zv["location"]["coordinates"]
        start = to_local(mv_lon, mv_lat)
        end = to_local(zv_lon, zv_lat)
        path = direct_or_detour(p1_xy, inner, start, end)
        path_ll = [list(to_lonlat(x, y)) for x, y in path]

        length = sum(
            math.hypot(path[i + 1][0] - path[i][0],
                       path[i + 1][1] - path[i][1])
            for i in range(len(path) - 1)
        )

        name = f"{mv_name}-{zv['name']}"
        repository.upsert("pipes",
            {"project_id": project_id, "name": name},
            {"project_id": project_id, "name": name,
             "pipe_type": "submain", "parent_pipe": mv_name,
             "geom": {"type": "LineString",
                      "coordinates": [list(p) for p in path_ll]},
             "length_m": length, "diameter_mm": diameter,
             "material": "HDPE PE100 PN10",
             "revision_id": revision,
             "created_at": now, "updated_at": now})

    current_app.logger.info("Sub-mains built for %s", project_id)


# ---------------------------------------------------------------- manifold
@bp.route("/manifold", methods=["GET", "POST"])
def manifold():
    pid = session.get("project_id", "farm_v1")

    if request.method == "POST":
        _build_manifolds(pid)
        flash("Manifolds built.", "success")
        return redirect(url_for("hydrology.manifold"))

    manifolds = list(get_db().manifolds.find(
        {"project_id": pid}, {"_id": 0}))
    return render_template("hydrology/manifold.html", manifolds=manifolds)


def _build_manifolds(project_id: str) -> None:
    zones = queries.get_zones(project_id)
    if not zones:
        flash("No zones.", "error")
        return

    revision = repository.new_revision(project_id, "11_manifold",
                                       "Build manifolds")
    repository.clear_step(project_id, "manifolds")

    now = datetime.now(timezone.utc)
    n = 0
    for z in zones:
        rows = queries.get_rows(project_id, z["name"])
        if not rows:
            continue
        starts = [(r["geom"]["coordinates"][0][0],
                   r["geom"]["coordinates"][0][1]) for r in rows]
        if len(starts) < 2:
            continue
        starts_sorted = sorted(starts, key=lambda p: p[0])
        manifold_ll = [list(starts_sorted[0]), list(starts_sorted[-1])]
        to_local, _ = _projection(z["geom"]["coordinates"][0])
        start_m = to_local(*starts_sorted[0])
        end_m = to_local(*starts_sorted[-1])
        name = f"MANIFOLD {z['name']}"
        length = math.hypot(end_m[0] - start_m[0], end_m[1] - start_m[1])
        repository.upsert("manifolds",
            {"project_id": project_id, "name": name},
            {"project_id": project_id, "name": name,
             "zone_name": z["name"],
             "geom": {"type": "LineString", "coordinates": manifold_ll},
             "length_m": length, "revision_id": revision,
             "created_at": now, "updated_at": now})
        n += 1

    current_app.logger.info("Built %d manifolds for %s", n, project_id)
