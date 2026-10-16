# Verification record

Validated in this cloud workspace; public deployment and a fresh-task restoration have not been verified.

- **Backend:** 26 tests passed against isolated SQLite and 26 passed against a dedicated PostgreSQL 17 / PostGIS test database. Includes geometry, concave/exclusion routes, camera coverage, mission states, image validation/EXIF/duplicates/missing GPS, domain-safe simulated inference, ownership, failure retries, complete survey/export workflow, and ML dataset leakage validation.
- **Frontend:** TypeScript check and Vite production build passed. MapLibre's ESM worker is emitted as an asset and served with JavaScript MIME type by Nginx. The large MapLibre bundle produces an advisory size warning.
- **Browser:** System Chromium + Playwright passed registration, polygon drawing, farm creation, planning, visibly rendered route, pause/resume, 28-capture completed simulation, image review, feedback, CSV/GeoJSON downloads, and mobile horizontal-overflow check. No captured JavaScript or map errors. Screenshots are local ignored artifacts in `.data/screenshots/`.
- **Runtime:** Prepared-artifact Docker Compose build and startup passed; migrations completed, PostGIS/Redis/API health checks passed, worker generated and analysed imagery, and Nginx served the production app. Migrations were rerun during service recreation without losing data. Nginx resolves the API service dynamically after container replacement.
- **Setup:** `scripts/prepare.sh` executed successfully; locked installations, frontend build, wheel preparation and existing `.env` preservation verified. Demo seed ran twice successfully; its temporary verification account was removed afterwards so users can seed their own credentials.
- **Dependencies:** `npm audit` reported zero vulnerabilities. `pip check` reported no broken requirements. Python package versions are frozen in `backend/requirements.lock`. This is not a claim of a comprehensive security audit.
- **Documentation:** Build/runtime compatibility was checked against official source documentation: [Vite guide](https://github.com/vitejs/vite/blob/main/docs/guide/index.md), [FastAPI containers](https://github.com/fastapi/fastapi/blob/master/docs/en/docs/deployment/docker.md), and [MapLibre v6 migration](https://github.com/maplibre/maplibre-gl-js/blob/main/docs/guides/v5-to-v6-migration-guide.md). Node 24 and Python 3.12 were used.

## Unverified or external dependencies

- Live external basemap and place search returned proxy **403 Forbidden**. Offline map mode was used for browser tests. Network draft additions for `tiles.openfreemap.org` and `nominatim.openstreetmap.org` are saved, but require user review/save and environment publication; this does not prove current provider access. Provider production licensing and capacity remain deployment responsibilities.
- Docker build-container DNS/egress failed. The tested cloud override builds from wheels and frontend assets fetched/prepared in the actual workspace with TLS verification retained. The normal networked Dockerfiles are provided but were not built successfully in this environment.
- Real aircraft integration, trained model activation/evaluation, expensive ML training, S3 endpoint credentials/operation, public TLS deployment, backup restoration and identity hardening are not verified. The app deliberately runs only the simulator and deterministic demo analysis.
- The test runner emits one upstream deprecation warning for Starlette's httpx test transport. Tests execute and pass; no assertions are disabled.
