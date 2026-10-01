"""Field section: Rows, Trees, Driplines."""
from __future__ import annotations

import math
from datetime import datetime, timezone

from flask import (
    Blueprint, current_app, flash, redirect, render_template,
    request, session, url_for,
)
from shapely.geometry import Polygon

from core.driplines import dripline_from_row
from core.geometry import clean_polygon, fall_direction
from core.rows import build_rows
from core.trees import place_trees_on_row
from core.validation import validate_form, RowBuild, TreePlace, DriplineBuild
from db import queries, repository


bp = Blueprint("field", __name__, url_prefix="/field")


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


# ---------------------------------------------------------------- rows
@bp.route("/rows", methods=["GET", "POST"])
@validate_form(RowBuild)
def rows(data: RowBuild | None = None):
    pid = session.get("project_id", "farm_v1")

    if request.method == "POST":
        assert data is not None
        _build_rows(pid, data.spacing, data.offset)
        flash("Rows built.", "success")
        return redirect(url_for("field.rows"))

    rows_list = queries.get_rows(pid)
    return render_template("field/rows.html", rows=rows_list)


def _build_rows(project_id: str, spacing: float, offset: float) -> None:
    zones = queries.get_zones(project_id)
    if not zones:
        flash("No zones.", "error")
        return

    revision = repository.new_revision(project_id, "08_rows", "Build rows")
    repository.clear_step(project_id, "rows")

    now = datetime.now(timezone.utc)
    total = 0

    for z in zones:
        ring = z["geom"]["coordinates"][0]
        to_local, to_lonlat = _projection(ring)
        pts_xy = [to_local(p[0], p[1]) for p in ring]
        poly = clean_polygon(Polygon(pts_xy))
        ux, uy = fall_direction(poly, [0.0] * len(pts_xy))

        for (ri, seg) in build_rows(poly, ux, uy, spacing, offset):
            seg_ll = [list(to_lonlat(x, y)) for x, y in seg]
            name = f"{z['name']}-R{ri+1:02d}"
            length = math.hypot(seg[1][0] - seg[0][0],
                                seg[1][1] - seg[0][1])
            repository.upsert("rows",
                {"project_id": project_id, "name": name},
                {"project_id": project_id, "name": name,
                 "zone_name": z["name"], "row_index": ri + 1,
                 "geom": {"type": "LineString",
                          "coordinates": [list(p) for p in seg_ll]},
                 "length_m": length,
                 "row_direction_deg": math.degrees(math.atan2(uy, ux)),
                 "revision_id": revision,
                 "created_at": now, "updated_at": now})
            total += 1

    current_app.logger.info("Built %d rows for %s", total, project_id)


# ---------------------------------------------------------------- trees
@bp.route("/trees", methods=["GET", "POST"])
@validate_form(TreePlace)
def trees(data: TreePlace | None = None):
    pid = session.get("project_id", "farm_v1")

    if request.method == "POST":
        assert data is not None
        _place_trees(pid, data.spacing, data.fig_pct)
        flash("Trees placed.", "success")
        return redirect(url_for("field.trees"))

    trees_list = queries.get_trees(pid)
    return render_template("field/trees.html", trees=trees_list)


def _place_trees(project_id: str, spacing: float, fig_pct: int) -> None:
    rows_list = queries.get_rows(project_id)
    if not rows_list:
        flash("No rows.", "error")
        return

    revision = repository.new_revision(project_id, "09_trees", "Place trees")
    repository.clear_step(project_id, "trees")

    now = datetime.now(timezone.utc)
    total = 0
    fig_counter = 0

    for r in rows_list:
        line = r["geom"]["coordinates"]
        start = (line[0][0], line[0][1])
        end = (line[-1][0], line[-1][1])
        to_local, to_lonlat = _projection([start, end])
        points_m = place_trees_on_row(
            to_local(*start), to_local(*end), spacing, center=True
        )
        for i, point_m in enumerate(points_m):
            lon, lat = to_lonlat(*point_m)
            fig_counter += 1
            species = "fig" if (fig_counter - 1) % 100 < fig_pct else "olive"
            name = f"T {r['name']}-T{i+1:02d}"
            repository.upsert("trees",
                {"project_id": project_id, "name": name},
                {"project_id": project_id, "name": name,
                 "row_name": r["name"], "zone_name": r["zone_name"],
                 "tree_index": i + 1,
                 "location": {"type": "Point", "coordinates": [lon, lat]},
                 "species": species, "revision_id": revision,
                 "created_at": now, "updated_at": now})
            total += 1

    current_app.logger.info("Placed %d trees for %s", total, project_id)


# ---------------------------------------------------------------- driplines
@bp.route("/driplines", methods=["GET", "POST"])
@validate_form(DriplineBuild)
def driplines(data: DriplineBuild | None = None):
    pid = session.get("project_id", "farm_v1")

    if request.method == "POST":
        assert data is not None
        _build_driplines(pid, data.emitter_spacing)
        flash("Driplines built.", "success")
        return redirect(url_for("field.driplines"))

    drips = list(__import__("db.connection", fromlist=["get_db"])
                 .get_db().driplines.find({"project_id": pid}, {"_id": 0}))
    return render_template("field/driplines.html", driplines=drips)


def _build_driplines(project_id: str, emitter_spacing: float) -> None:
    rows_list = queries.get_rows(project_id)
    if not rows_list:
        flash("No rows.", "error")
        return

    revision = repository.new_revision(project_id, "10_driplines",
                                       "Build driplines")
    repository.clear_step(project_id, "driplines")

    now = datetime.now(timezone.utc)
    for r in rows_list:
        line = r["geom"]["coordinates"]
        start = (line[0][0], line[0][1])
        end = (line[-1][0], line[-1][1])
        to_local, _ = _projection([start, end])
        start_m, end_m = to_local(*start), to_local(*end)
        dl = dripline_from_row(start_m, end_m, emitter_spacing)
        name = f"DL {r['name']}"
        repository.upsert("driplines",
            {"project_id": project_id, "name": name},
            {"project_id": project_id, "name": name,
             "row_name": r["name"], "zone_name": r["zone_name"],
             "geom": {"type": "LineString",
                      "coordinates": [list(start), list(end)]},
             "length_m": dl["length_m"],
             "emitter_count": dl["emitter_count"],
             "revision_id": revision,
             "created_at": now, "updated_at": now})

    current_app.logger.info("Built driplines for %s", project_id)
