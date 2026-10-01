"""JSON API for the Leaflet map."""
from __future__ import annotations

from flask import Blueprint, jsonify, session
from db import queries
from db.connection import get_db


bp = Blueprint("api", __name__, url_prefix="/api/v1")


@bp.route("/summary")
def summary():
    pid = session.get("project_id", "farm_v1")
    return jsonify(queries.project_summary(pid))


@bp.route("/geojson")
def geojson():
    """Return the full project as a GeoJSON FeatureCollection."""
    pid = session.get("project_id", "farm_v1")
    db = get_db()
    features = []
    for coll, gfield in [("property", "geom"), ("basins", "geom"), ("water_points", "location"),
                         ("sectors", "geom"), ("zones", "geom"), ("pipes", "geom"),
                         ("rows", "geom"), ("valves", "location"),
                         ("trees", "location"), ("driplines", "geom"),
                         ("manifolds", "geom")]:
        for d in db[coll].find({"project_id": pid}):
            geom = d.get(gfield)
            if not geom:
                continue
            features.append({
                "type": "Feature",
                "properties": {
                    "name": d.get("name"),
                    "code": d.get("sector_code"),
                    "collection": coll,
                    "color": d.get("color"),
                    "area_m2": d.get("area_m2"),
                    "diameter_mm": d.get("diameter_mm"),
                    "species": d.get("species"),
                    "elev_m": d.get("elev_m"),
                    "depth_m": d.get("depth_m"),
                },
                "geometry": geom,
            })
    return jsonify({"type": "FeatureCollection", "features": features})


@bp.route("/bounds")
def bounds():
    """Return overall bounding box for map auto-fit."""
    pid = session.get("project_id", "farm_v1")
    db = get_db()
    prop = db.property.find_one({"project_id": pid})
    if not prop:
        return jsonify({"bounds": None})
    ring = prop["geom"]["coordinates"][0]
    lons = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    return jsonify({
        "bounds": [[min(lats), min(lons)], [max(lats), max(lons)]]
    })

@bp.route("/zones")
def zones():
    """Return only zones as a FeatureCollection (used after zone rebuild)."""
    pid = session.get("project_id", "")
    if not pid:
        return jsonify({"type": "FeatureCollection", "features": []})

    db = get_db()
    features = []
    for d in db.zones.find({"project_id": pid}):
        geom = d.get("geom")
        if not geom:
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "name":       d.get("name"),
                "sector":     d.get("sector_code"),
                "zone_index": d.get("zone_index"),
                "area_m2":    d.get("area_m2", 0),
                "collection": "zones",
            },
            "geometry": geom,
        })
    return jsonify({"type": "FeatureCollection", "features": features})
