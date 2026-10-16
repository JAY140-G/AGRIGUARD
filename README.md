# AgriScan

A simulation-first crop survey workspace: create a farm, draw its boundary, plan a survey, collect synthetic or uploaded imagery, and review photo-level suspected findings.

**All current analysis is simulated. No trained model is selected, no diagnostic score is fabricated, and no live aircraft commands are implemented.**

## Run with Docker Compose

Requires Docker Engine + Compose v2. The normal build needs Internet access to Docker Hub, PyPI and npm. No datasets or model weights are downloaded.

```sh
cp .env.example .env
# Set a unique POSTGRES_PASSWORD and the matching password in DATABASE_URL.
docker compose up -d --build
```

The web service listens on local port 8080. Register an account in the app; there is no public authentication bypass or default login. The API documentation is at `/api/docs`, and health is at `/api/health`. Data persists in named Postgres, Redis, and image volumes. Do not delete these volumes to restart services.

For this proxy-managed cloud workspace, Docker build containers cannot resolve network destinations. Use the tested prepared-artifact build instead:

```sh
./scripts/prepare.sh
./scripts/cloud-compose.sh up -d --build
./scripts/cloud-compose.sh ps
```

`prepare.sh` installs the locked Python and npm dependencies in the actual workspace, creates `.env` with a random local database password only when absent, builds the frontend, and downloads Python wheels over verified TLS. It does not change application source or locks. The optional Compose override packages these prepared artifacts without downloading packages inside build containers. Wheels and built assets are ignored by Git and are regenerated on a fresh checkout. Use Python 3.12 and Node 24 on Linux x86-64 for the same prepared wheel platform. Change frontend build-time map variables **before** running the preparation command. `cloud-compose.sh` uses `/workspace/.docker` because the default Docker configuration directory is read-only here; override `DOCKER_CONFIG` on other machines.

## Demo walkthrough

1. Register a private account. Select **Add farm**; name it and select a crop.
2. Search for a location (or enter `latitude, longitude`). Choose **Draw boundary**, click at least three corners, then **Finish polygon**. Drag the corner handles to edit. **Use sample field in Jaipur** provides a reproducible example. Save the farm.
3. Open **Mission planner**. Configure altitude, speed and overlaps; optionally enter camera sensor width, focal length, image dimensions, and draw exclusion polygons. Generate a survey. Without complete camera specifications, estimates are visibly provisional.
4. For a short demonstration use altitude **120 m** and both overlaps **0%**. This is a simulation setting, not a field recommendation. Start the simulation. Pause, resume, abort, or inject a connection failure in the live view. Repeated starts are rejected.
5. Open **Results explorer**. Click a map marker or image card. Review synthetic crop photos, location source, model version and the persistent **Simulated analysis** label. Add inspection/confirmation/incorrect feedback, which is kept separately from predictions. Demo confirmation is not evidence of actual crop disease.
6. Upload a JPEG or PNG to test manual collection. Choose aerial, close-up or unknown domain. GPS is read from EXIF if present; missing GPS remains missing until manually assigned. Add a mission association through the mission filter. Export CSV or GeoJSON.

Optional reproducible development seed (no shared password is embedded):

```sh
# Supply DEMO_PASSWORD securely in the shell/environment; minimum 10 characters.
export DEMO_EMAIL=farmer@example.test
# Set DEMO_PASSWORD without placing it in version control.
docker compose run --rm -e DEMO_EMAIL -e DEMO_PASSWORD api python -m app.seed
# In cloud, substitute ./scripts/cloud-compose.sh for docker compose.
```

Seeding is idempotent and only enabled with `ENVIRONMENT=development`. It creates an account and sample farm; it does not automatically launch a mission. Repeated seeds preserve existing account passwords and farms.

## Development and tests

```sh
./scripts/prepare.sh
./scripts/check.sh
```

The backend test suite uses an isolated temporary SQLite database by default. To validate against PostGIS, provision a **dedicated empty test database**, then set `TEST_DATABASE_URL=postgresql+psycopg://.../agriscan_test` before running tests. The suite creates and drops its test tables; never point it at application data. Tests cover geometry/area, concave routes and exclusions, camera estimates, mission states, image validation/EXIF/missing GPS/duplicates, adapter output and unsupported domains, cross-user isolation, retries, and a complete simulated survey with exports.

For host development without Docker:

```sh
# In the repository root, with .venv installed:
mkdir -p .data/images
cd backend
# Override DATABASE_URL and STORAGE_DIR in your shell. The repository .env is not
# implicitly loaded from this subdirectory; SQLite + local storage are defaults.
../.venv/bin/alembic upgrade head
../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
# Second terminal, backend working directory:
../.venv/bin/python -m app.worker
# Third terminal, repository root:
npm run dev --prefix frontend
```

Vite proxies `/api` to the backend. Development CORS permits only the two Vite localhost origins by default. If supplying an Origin manually to write APIs, it must be allowed. All writes require `X-AgriScan: 1` to reject simple cross-site form requests; the frontend supplies it automatically.

Browser verification uses Playwright with the system Chromium where available. `scripts/browser-smoke.cjs` registers a fresh account and exercises the real UI against the running Compose stack; screenshots and temporary test credentials stay outside version control. This is optional to run locally, requiring `playwright` installed in the configured module location.

## Architecture

- `frontend/`: React 19, TypeScript, Vite, Tailwind CSS, MapLibre GL. Responsive dashboard, farm editor, planner, live simulation, results, settings. Map and photo locations use longitude/latitude (WGS84). Filters and image lists are paginated by the API.
- `backend/app/main.py`: FastAPI API, explicit ownership checks, scrypt password hashing, opaque hashed session tokens in the database, HttpOnly SameSite cookies, restricted CORS, safe upload handling, structured request logs.
- `backend/app/geo.py`: Shapely validation + farm-local UTM projection for areas and route calculations. PostGIS stores boundaries as indexed `geography(Polygon,4326)` in addition to a portable GeoJSON serialization. Invalid/self-intersecting rings and out-of-range coordinates are rejected.
- `backend/app/worker.py`: independently restarted worker, persistent database job records and attempt counts. Redis provides wake-up queues; database polling recovers jobs after Redis interruption or lost notifications. Postgres row locks with `SKIP LOCKED` keep workers from processing the same job concurrently. An analysis transaction atomically commits the prediction and job outcome. Exceptions retry at most three times, followed by explicit user retry. Mission progress and synthetic image creation commit together. Paused/aborted/failed missions do not advance.
- `backend/app/drone.py`: typed adapter extension point, simulator lifecycle and validated mission transitions. Start transitions use a conditional DB update to reject concurrent duplicate starts. Changing a farm boundary invalidates starting an older plan.
- `backend/app/inference.py`: replaceable inference protocol, deterministic demo analyzer, optional TorchScript adapter with manifest/domain checks. Aerial and close-up tasks remain separate.
- `backend/app/storage.py`: originals in local volume or S3-compatible object storage. The API checks ownership before streaming image bytes; buckets must stay private.
- `backend/migrations/`: Alembic schema history. Compose runs migrations before API/worker startup.
- `ml/`: explicitly invoked training/evaluation scaffold, separate from runtime dependencies.

The deployment uses five long-running services (web, API, worker, PostGIS, Redis), plus a one-shot migration. Health checks cover DB/Redis/API; worker readiness should additionally be verified by a completed test analysis/mission. A healthy API alone does not establish worker progress.

### API guide

OpenAPI documents request/response inputs at `/api/docs`. All farm, mission, image, job and export operations require an authenticated owner.

| Workflow | Endpoints |
| --- | --- |
| Accounts | `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout` |
| Farms | `GET/POST /api/farms`, `PUT /api/farms/{id}` |
| Planning/history | `POST/GET /api/farms/{id}/missions`, `GET /api/missions/{id}` |
| Simulator controls | `POST /api/missions/{id}/{start,pause,resume,abort,fail}` |
| Telemetry/capture event | `GET /api/missions/{id}/telemetry` (latest event; full capture history through mission-filtered images) |
| Photos/findings | `POST/GET /api/farms/{id}/images`, `GET /api/images/{id}/original` |
| Analysis jobs | `GET /api/images/{id}/job`, `POST /api/images/{id}/retry` |
| Manual geolocation/feedback | `PUT /api/images/{id}/location`, `PUT /api/images/{id}/feedback` |
| Dashboard | `GET /api/farms/{id}/summary` |
| Exports | `GET /api/farms/{id}/export/{csv,geojson}` |
| Operational | `GET /api/health`, `GET /api/settings` |

Farm, mission and image lists accept `offset` and `limit`; image queries also accept `mission_id`, `date_from`, `date_to`, `label`, and `min_score`. Demo scores are null and are excluded by numerical score filters. Exports include all images, not only the currently displayed page. Missing-location photos appear in CSV and lists but do not become GeoJSON point features.

### Map providers

The demo default style is OpenFreeMap Liberty (`tiles.openfreemap.org`), with its built-in OpenStreetMap attribution retained. Submitted place searches use Nominatim, with no autocomplete and a client throttle. Set `VITE_MAP_STYLE` and `VITE_GEOCODER_URL` to your own licensed providers for deployment; observe provider policies and traffic limits, and keep attribution. Nominatim's public endpoint is unsuitable for unrestricted production traffic. The application does not claim any public provider grants unlimited imagery use.

Settings can select `offline` as the style. This is a plain coordinate canvas without imagery, useful when external services are blocked. Drawing, metric planning, simulation, upload, review, and exports continue to work. Provider failure is surfaced in the map; offline mode is always available. No satellite imagery is bundled. Do not embed private provider credentials in a frontend build; use a provider-supported public key with origin limits or a properly authenticated tile gateway.

## Hardware extension

Implement `DroneAdapter` with connection lifecycle, capabilities, telemetry, plan validation/upload, controls, status and capture events. Add conformance tests and a separate explicit hardware opt-in; do not substitute an adapter silently. Translate geographic route segments into the platform's supported mission format, and verify coordinate reference/altitude conventions. Add capability constraints, battery limits, link-loss behavior, telemetry reconciliation, command acknowledgements and independently validated return-to-home behavior. Verify against the specific aircraft/firmware and controlled test environment before any operational use. No DJI, MAVLink, PX4 or other hardware compatibility is currently claimed.

## ML scaffold

Optional dependencies are in `ml/requirements.txt`; they are not installed during application setup. No dataset download or training happens automatically.

```sh
python -m venv ml/.venv
ml/.venv/bin/pip install -r ml/requirements.txt
cd ml
.venv/bin/python common.py /path/to/dataset.csv labels.example.json
.venv/bin/python train.py /path/to/dataset.csv labels.example.json --epochs 5 --output runs/wheat-v1
.venv/bin/python evaluate.py /path/to/dataset.csv runs/wheat-v1/manifest.json runs/wheat-v1/model.pt --output runs/wheat-v1/test_metrics.json
```

Dataset columns: `path,label,group,crop,domain,split`. Paths are relative to the CSV. Use `train`, `val`, `test` splits with mutually exclusive **farm or collection-session groups**. Prefer farm-level splits when repeated sessions from a farm are correlated. The validator rejects missing files, corrupt images, unsupported labels/domains/crops, duplicate image content and group leakage. The example CSV is a format template, not a bundled dataset.

Training explicitly downloads official pretrained ResNet18 weights (~45 MB), freezes the backbone, trains a configurable classification head, saves the best validation checkpoint as TorchScript and records real training metrics. Evaluation computes held-out classification metrics and a confusion matrix; it does not assert calibration or deployment approval. Training/evaluation have not been run on real crop data in this MVP.

The runtime `TorchScriptAdapter` requires model version, labels, crops and domain in a manifest and rejects unsupported images. Its scores are uncalibrated model outputs, not diagnostic certainty. Aerial deployment additionally requires documented evaluation on labelled **aerial** imagery and a reviewed `validated_aerial` manifest setting. A close-up classifier cannot establish aerial stress/disease validity. The default worker deliberately selects `DemoAnalyzer`; production model activation requires explicit integration and tests in a separate change. No bounding boxes, segmentation masks, severity, diagnostic accuracy, or affected acreage are invented.

## Deployment

No external deployment target or credentials were supplied. The Compose package is prepared for deployment, not publicly deployed.

1. Choose a host/container platform, domain and TLS termination. Keep DB/Redis private; expose only the web service through the HTTPS ingress. The default Compose port binds loopback deliberately; connect ingress to that endpoint or change binding intentionally.
2. Provision PostGIS 17-compatible PostgreSQL, Redis, persistent image storage or a private S3-compatible bucket. Use separate least-privilege runtime roles after the migration role creates the PostGIS extension/schema. Back up Postgres and original images together; test restoration. Enable appropriate bucket encryption and retention.
3. Set a unique database password and matching URL, `ENVIRONMENT=production`, `COOKIE_SECURE=true`, and exact HTTPS origins in `ALLOWED_ORIGINS`. Production startup rejects insecure-cookie configuration. Configure `STORAGE_BACKEND=s3`, `S3_BUCKET`, `S3_ENDPOINT` and workload identity/secure AWS environment bindings if using object storage. Do not commit credentials.
4. Set licensed map/geocoder build-time settings; build from lockfiles, run checks, apply migrations once, start the API/worker/web services. Standard Dockerfiles support an optional `build_ca` secret CA bundle for verified TLS through a trusted enterprise proxy. Never disable TLS verification.
5. Verify registration/login, a complete simulated survey, original-image retrieval, feedback and exports under HTTPS. Monitor worker progress, DB job failures, disk/bucket usage, and structured logs. Configure ingress rate limits and shared auth throttling across replicas (the included Nginx limit is per web instance). Add account recovery/email verification and any organizational identity requirements before a broader public launch.

## Deliberate MVP limits

- Survey calculation is a flat-ground, fixed-orientation lawnmower estimate for farms within 0.2 degrees on each axis and UTM latitude coverage (-80 to 84). It does not model slope, wind, optical distortion or regulatory constraints. Camera coverage uses sensor width/focal length and pixel aspect ratio, or a labelled provisional footprint.
- Scan segments are clipped inside the farm minus exclusions, including concave/disconnected segments. **Dashed transfers may leave the boundary or cross exclusions.** They are explicit unvalidated transits, not obstacle-avoiding routes. The launch point is the first capture; the labelled return point is the end of the route, not an implemented aircraft return-to-home command. Flight estimates include transfers but no takeoff, landing, reserves or ferry to a separate home location.
- The accelerated simulator moves between capture positions and emits illustrative battery/location/capture telemetry. It is not a physics simulator. Synthetic JPEGs depict crop rows, not actual farm imagery.
- Analysis is deterministic display data. Photo-level GPS cannot establish individual plant positions or affected polygons. Human feedback is not merged into model predictions.
- Authentication is private-account MVP functionality, without password recovery, email verification, team sharing or full audit history. Apply deployment-specific operational and identity requirements before a public rollout.
