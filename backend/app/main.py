from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import get_settings
from .db import engine
from .errors import DomainError
from .routes.auth_routes import router as auth_router
from .routes.discovery_routes import close_discovery_client, router as discovery_router
from .routes.household_routes import router as household_router
from .routes.pantry_shopping_routes import router as pantry_shopping_router
from .routes.planning_routes import router as planning_router
from .routes.recipe_routes import router as recipe_router
from .routes.system_routes import router as system_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_discovery_client()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Meal Planner API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)

    prefix = "/api/v1"
    for router in (
        auth_router,
        household_router,
        recipe_router,
        discovery_router,
        planning_router,
        pantry_shopping_router,
        system_router,
    ):
        app.include_router(router, prefix=prefix)

    @app.get(f"{prefix}/health/live", tags=["system"])
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(f"{prefix}/health/ready", tags=["system"])
    def ready() -> dict[str, str]:
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Database is unavailable") from exc
        return {"status": "ready"}

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        return JSONResponse(
            status_code=exc.status_code,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": exc.code.replace("_", " ").title(),
                "status": exc.status_code,
                "code": exc.code,
                "detail": exc.detail,
                "field_errors": [],
                "actions": exc.actions,
                "trace_id": trace_id,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        trace_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        return JSONResponse(
            status_code=422,
            media_type="application/problem+json",
            content={
                "type": "about:blank",
                "title": "Validation Error",
                "status": 422,
                "code": "VALIDATION_ERROR",
                "detail": "The request contains invalid fields",
                "field_errors": [
                    {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
                    for error in exc.errors()
                ],
                "actions": [],
                "trace_id": trace_id,
            },
        )

    frontend_raw = os.getenv("FRONTEND_DIST_DIR")
    frontend_dir = Path(frontend_raw).resolve() if frontend_raw else None
    if frontend_dir and frontend_dir.is_dir():
        assets = frontend_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="frontend-assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = (frontend_dir / full_path).resolve()
            if frontend_dir in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(frontend_dir / "index.html")

    return app


app = create_app()
