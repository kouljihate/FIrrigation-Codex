# Farm Irrigation Workbench

Flask + MongoDB web application for orchard/farm irrigation system design.

## Version

**2.0.0** — Added authentication, async processing, input validation, API versioning, tests, and MongoDB indexes.

## Stack

- **Backend**: Flask 3.x, PyMongo 4.x
- **Geometry**: Shapely 2.x, NumPy
- **Export**: lxml (KML), ezdxf (DXF), GeoJSON, CSV
- **Frontend**: Bootstrap 5 (Bootswatch Journal), Leaflet 1.9, bilingual EN/AR
- **Database**: MongoDB (local or Atlas)
- **Validation**: Pydantic 2.x
- **Async**: ThreadPoolExecutor for long-running geometry operations
- **Auth**: Flask-Login with role-based access
- **Testing**: pytest

## Install

```bash
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # macOS / Linux

pip install -r requirements.txt
```

## MongoDB

Install MongoDB Community Edition locally and start it as a service.
Default connection: `mongodb://localhost:27017`.

Copy `.env.example` to `.env` and adjust if needed:
```
MONGO_HOST=localhost
MONGO_PORT=27017
MONGO_DB=farm_irrigation
SECRET_KEY=your-secret-key
FLASK_DEBUG=1
LOG_LEVEL=INFO
```

**Indexes**: Auto-created on startup for all `project_id` fields + compound unique indexes.

## Run

```bash
python run.py
```

Open http://127.0.0.1:5001

## Project Structure

| Folder/File      | Purpose                                           |
|------------------|---------------------------------------------------|
| `app.py`         | Flask app factory, blueprint registration         |
| `run.py`         | Dev server entry point                            |
| `config.py`      | Configuration (YAML + env) with Pydantic validation |
| `routes/`        | 10 blueprints: home, project, geometry, hydrology, field, export, api, map_view, logs, auth |
| `core/`          | Domain logic: kml_io, geometry, piping, rows, trees, driplines, valves, BOM, validation, async_tasks |
| `db/`            | MongoDB connection, repository, queries, models   |
| `templates/`     | Jinja2 templates (base, home, project, geometry, hydrology, field, export, logs, map, auth) |
| `static/`        | CSS, JS (toasts, modals, Leaflet map)             |
| `imports/`       | User-uploaded KML files                           |
| `exports/`       | Generated KML / DXF / GeoJSON / CSV               |
| `logs/`          | Application log file                              |
| `tests/`         | Unit tests for core algorithms                    |

## Workflow

1. **Auth** — Register/login (required for all pages)
2. **Home** — Create new project or open existing
3. **Project → Initialize** — Upload KML (property P1, water points, basins, sectors)
4. **Project → Water & Basin** — Add/edit water points and basins
5. **Geometry → Sectors** — Verify/edit imported sectors
6. **Geometry → Zones** — Split each sector into equal-area zones (contour/fan/strip modes) — **async supported**
7. **Geometry → Valves** — Generate Main Valves (MV) + Zone Valves (ZV)
8. **Hydrology → Mainline** — Route basin → each MV (with boundary detour)
9. **Hydrology → Sub-mains** — Route each MV → its ZVs
10. **Hydrology → Manifold** — Build manifold per zone (connects row starts)
11. **Field → Rows** — Trace rows inside each zone (perpendicular to fall line)
12. **Field → Trees** — Place trees along rows (configurable spacing, species mix)
13. **Field → Driplines** — One dripline per row (emitter spacing configurable)
14. **Export → BOM** — Bill of Materials (pipes, valves, trees, driplines)
15. **Export** — Download KML, DXF, GeoJSON, CSV (trees)
16. **Map** — Full-screen Leaflet map with all layers

## Features

- **Authentication** — User registration, login, roles (admin/user), session management
- **Revision history** — Every build step creates a revision (see Project → Settings)
- **Bilingual UI** — English/Arabic with RTL support
- **Map view** — Interactive Leaflet map with GeoJSON API (`/api/v1/`)
- **Multiple zone split algorithms** — Contour (equal-area bands), Fan (radial), Strip (parallel)
- **Pipe routing** — Direct or boundary-detour routing around property
- **Export formats** — KML (Google Earth), DXF (CAD), GeoJSON (GIS), CSV (trees)
- **Input validation** — Pydantic schemas on all POST endpoints
- **Async processing** — Long geometry ops run in background with task status polling
- **MongoDB indexes** — Auto-created for query performance
- **Unit tests** — 16 tests covering core algorithms

## API Endpoints

```
GET  /api/v1/summary      — Project summary counts
GET  /api/v1/geojson      — Full project as GeoJSON FeatureCollection
GET  /api/v1/bounds       — Property bounding box for map fit
GET  /api/v1/zones        — Zones only (for zone rebuild updates)
GET  /geometry/tasks/<id> — Async task status
GET  /geometry/tasks      — All tasks for current project
```

## Configuration

Edit `config.yaml` for:
- App title/version
- MongoDB connection
- Import/export/config directories
- Default parameters (spacing, diameters, etc.)

Validated on startup with Pydantic — invalid config will fail fast with clear errors.

Environment variables in `.env` override YAML for secrets.

## Requirements

See `requirements.txt`:
- flask>=3.0
- flask-login>=0.6
- pymongo>=4.6
- shapely>=2.0
- lxml>=4.9
- numpy>=1.24
- PyYAML>=6.0
- pandas>=2.0
- ezdxf>=1.3
- python-dotenv>=1.0
- pydantic>=2.0
- pytest>=8.0

## Testing

```bash
python -m pytest tests/test_core.py -v
```

16 tests covering:
- Ring area calculations (m²)
- Row generation (spacing, offset)
- Tree placement (centered, non-centered, short rows)
- Dripline generation (emitter count, length)
- Geometry helpers (clean polygon, fall direction, inward offset)
- Pipe routing (direct, detour)
