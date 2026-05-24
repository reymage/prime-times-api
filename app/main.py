from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from tortoise.contrib.fastapi import register_tortoise

from app.ai.router import router as ai_router
from app.articles.router import router as articles_router
from app.auth.router import router as auth_router
from app.console.router import router as console_router
from app.gating.router import router as gating_router
from app.nav.router import router as nav_router
from app.config import settings
from app.database import TORTOISE_ORM
from app.middleware import SecurityHeadersMiddleware

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[settings.RATE_LIMIT_DEFAULT],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Prime Times Daily API",
    version="1.0.0",
    # Disable interactive docs in production — they expose schema details
    docs_url=None if settings.is_production else "/api/docs",
    redoc_url=None if settings.is_production else "/api/redoc",
    openapi_url=None if settings.is_production else "/api/openapi.json",
    lifespan=lifespan,
)

# ── Rate limiter ───────────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── Middleware (added in reverse execution order — last added = outermost) ─────

# Innermost: stamp security headers on every response that makes it this far
app.add_middleware(SecurityHeadersMiddleware)

# CORS — allow configured origins + any Cloudflare Workers/Pages deployment
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=r"https://[a-zA-Z0-9.-]+\.(workers|pages)\.dev",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)

# Reject requests with unrecognised Host headers (production only)
if "*" not in settings.ALLOWED_HOSTS:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS)

# ── Global exception handler ───────────────────────────────────────────────────
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak stack traces or internal detail to clients in production
    if settings.is_production:
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred."},
        )
    raise exc

# ── ORM ────────────────────────────────────────────────────────────────────────
register_tortoise(
    app,
    config=TORTOISE_ORM,
    generate_schemas=False,
    add_exception_handlers=True,
)

# ── Routes ─────────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(nav_router)
app.include_router(articles_router)
app.include_router(gating_router)
app.include_router(console_router)
app.include_router(ai_router, prefix="/api")


@app.get("/api/health")
@limiter.limit("30/minute")
async def health_check(request: Request):
    return {"status": "ok", "environment": settings.ENVIRONMENT}
