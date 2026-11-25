from contextlib import asynccontextmanager
import time
import uuid
import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.health import router as health_router
from app.api.v1.auth import router as auth_router
from app.api.v1.workspaces import router as workspaces_router
from app.api.v1.datasets import router as datasets_router
from app.api.v1.lakehouse import router as lakehouse_router
from app.api.v1.sql import router as sql_router
from app.api.v1.pipelines import router as pipelines_router
from app.api.v1.observability import router as observability_router
from app.api.v1.catalog import router as catalog_router
from app.core.config import get_settings
from app.core.db import Base, engine
from app.core.security import sha256
from app.models import entities  # noqa: F401
from app.core.observability import configure_logging, request_id_ctx

settings = get_settings()
configure_logging(settings.log_level)

@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.app_env.lower() == "production":
        if settings.auth_secret == "change-this-secret-before-production":
            raise RuntimeError("AUTH_SECRET must be configured in production")
        if not settings.cookie_secure:
            raise RuntimeError("COOKIE_SECURE must be true in production")
        if "*" in settings.cors_origins:
            raise RuntimeError("CORS_ORIGINS must not contain wildcards in production")
        if settings.database_url.startswith("sqlite"):
            raise RuntimeError("SQLite is not the supported production application database")
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request_id_ctx.set(request_id)
    started = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    logging.getLogger("pylake.http").info(
        "method=%s path=%s status=%s duration_ms=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix=settings.api_v1_prefix, tags=["health"])
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(workspaces_router, prefix=settings.api_v1_prefix)
app.include_router(datasets_router, prefix=settings.api_v1_prefix)
app.include_router(lakehouse_router, prefix=settings.api_v1_prefix)
app.include_router(sql_router, prefix=settings.api_v1_prefix)
app.include_router(observability_router, prefix=settings.api_v1_prefix)
app.include_router(catalog_router, prefix=settings.api_v1_prefix)
app.include_router(pipelines_router, prefix=settings.api_v1_prefix)


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            path = request.url.path
            auth_public = path in {
                f"{settings.api_v1_prefix}/auth/register",
                f"{settings.api_v1_prefix}/auth/login",
            }
            if not auth_public and request.cookies.get(settings.auth_cookie_name):
                csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
                csrf_header = request.headers.get("X-CSRF-Token")
                if not csrf_cookie or not csrf_header or sha256(csrf_cookie) != sha256(csrf_header):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF validation failed"},
                    )
        return await call_next(request)


app.add_middleware(CsrfMiddleware)
