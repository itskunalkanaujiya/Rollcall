from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.v1 import api_router
from app.core import errors
from app.core.config import get_settings
from app.database.base import SessionLocal, engine
from app.middleware.security import OriginCheckMiddleware, SecurityHeadersMiddleware
from app.services import audit_service
from app.services.embedding_cache import get_cache
from app.services.face_detection import ModelUnavailableError
from app.services.face_recognition import get_engine

log = logging.getLogger("app")

# Populated by the Docker build (frontend built into backend/static). Absent in local dev,
# where the Vite dev server serves the frontend instead.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    logging.basicConfig(level=s.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # Load the model ONCE per process. If it is missing the API still starts and
    # /recognition/status + the scanner report the problem; nothing is faked.
    if s.load_model_on_startup:
        try:
            get_engine().load()
        except ModelUnavailableError as exc:
            log.error("Face model NOT loaded: %s", exc)
    try:
        with SessionLocal() as db:
            get_cache().refresh(db)
    except Exception:  # noqa: BLE001 - e.g. tables not migrated yet; say so clearly
        log.exception("Could not load face templates. Did you run 'alembic upgrade head'?")
    yield
    engine.dispose()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title=s.app_name, version="1.0.0", lifespan=lifespan,
                  docs_url="/docs" if s.environment != "production" else None,
                  redoc_url=None, openapi_url="/openapi.json" if s.environment != "production" else None)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(OriginCheckMiddleware)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_origin_list, allow_credentials=True,
                       allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type", "Authorization"])
    errors.install(app)
    app.include_router(api_router, prefix=s.api_prefix)

    @app.get("/health", tags=["system"])
    def health() -> dict:
        eng = get_engine()
        return {"status": "ok", "model_loaded": eng.is_loaded, "model_error": eng.info.error,
                "environment": s.environment}

    if STATIC_DIR.is_dir():
        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str) -> FileResponse:
            candidate = STATIC_DIR / full_path
            if full_path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(STATIC_DIR / "index.html")  # client-side routes (React Router)

    return app


app = create_app()
