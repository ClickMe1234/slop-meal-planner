from __future__ import annotations

import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from .config import get_settings
from .errors import DomainError
from .health import check_database, check_redis
from .routes.auth_routes import reset_login_security_state, router as auth_router
from .routes.discovery_routes import close_discovery_client, router as discovery_router
from .routes.food_routes import router as food_router
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
    reset_login_security_state()
    app = FastAPI(
        title="Meal Planner API",
        version=os.getenv("APP_VERSION", "1.1.0"),
        docs_url="/api/docs" if settings.public_api_docs else None,
        openapi_url="/api/openapi.json" if settings.public_api_docs else None,
        lifespan=lifespan,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(RequestSizeLimitMiddleware, maximum_bytes=settings.max_request_body_bytes)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(self), microphone=(), geolocation=(), payment=(), usb=()"
        )
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'none'; object-src 'none'; "
            "frame-ancestors 'none'; form-action 'self'; "
            "script-src 'self'; style-src 'self'; font-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; "
            "manifest-src 'self'; worker-src 'self' blob:"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        if settings.hsts_enabled:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    prefix = "/api/v1"
    for router in (
        auth_router,
        household_router,
        food_router,
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
        if not check_database():
            raise HTTPException(status_code=503, detail="Database is unavailable")
        if not check_redis():
            raise HTTPException(status_code=503, detail="Redis is unavailable")
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
                "issues": exc.issues,
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


class RequestSizeLimitMiddleware:
    """Bound request bodies even when clients use chunked transfer encoding."""

    def __init__(self, app: ASGIApp, maximum_bytes: int) -> None:
        self.app = app
        self.maximum_bytes = maximum_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers", []))
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = self.maximum_bytes + 1
        if declared > self.maximum_bytes:
            await self._reject(send)
            return
        body = bytearray()
        more = True
        while more:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > self.maximum_bytes:
                await self._reject(send)
                return
            more = message.get("more_body", False)
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if delivered:
                return {"type": "http.request", "body": b"", "more_body": False}
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)

    @staticmethod
    async def _reject(send: Send) -> None:
        content = (
            b'{"type":"about:blank","title":"Request Too Large","status":413,'
            b'"code":"REQUEST_TOO_LARGE","detail":"The request body is too large"}'
        )
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(content)).encode("ascii")),
                    (b"cache-control", b"no-store"),
                ],
            }
        )
        await send({"type": "http.response.body", "body": content})


app = create_app()
