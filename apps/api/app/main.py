"""Voicera FastAPI application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import close_mongo_connection, connect_to_mongo, ping_database
from app.database_init import initialize_database
from app.routers import (
    agents,
    auth,
    calls,
    campaign,
    configuration,
    knowledge,
    languages,
    members,
    organisations,
    phone_numbers,
    rag,
    users,
)
from app.services import agent_seed, platform_auth
from app.services.limits.errors import LimitExceeded

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Connect to FerretDB and ensure auth collections/indexes on startup."""
    logger.info("Starting up application...")
    try:
        connect_to_mongo()
        initialize_database()
        platform_auth.validate_config()
        if settings.SANDBOX_SEED_AGENTS:
            agent_seed.validate_templates()
        logger.info("Application started successfully")
    except Exception as exc:
        logger.error("Failed to start application: %s", exc)
        raise

    yield

    logger.info("Shutting down application...")
    close_mongo_connection()
    logger.info("Application shut down successfully")


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "Voicera Backend API — auth, organisations, agents, "
        "provider catalogs, and credentials"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(LimitExceeded)
async def limit_exceeded_handler(_request: Request, exc: LimitExceeded) -> JSONResponse:
    """429 with Retry-After. Body carries only scope/limit — never account info,
    or the limiter itself becomes an enumeration oracle (S9)."""
    return JSONResponse(
        status_code=429,
        headers={"Retry-After": str(exc.retry_after)},
        content={
            "code": "rate_limited",
            "scope": exc.scope,
            "retry_after": exc.retry_after,
        },
    )


app.include_router(users.router, prefix=settings.API_V1_PREFIX)
app.include_router(members.router, prefix=settings.API_V1_PREFIX)
app.include_router(organisations.router, prefix=settings.API_V1_PREFIX)
app.include_router(languages.router, prefix=settings.API_V1_PREFIX)
app.include_router(configuration.router, prefix=settings.API_V1_PREFIX)
app.include_router(auth.router, prefix=settings.API_V1_PREFIX)
app.include_router(agents.router, prefix=settings.API_V1_PREFIX)
app.include_router(phone_numbers.router, prefix=settings.API_V1_PREFIX)
app.include_router(calls.router, prefix=settings.API_V1_PREFIX)
app.include_router(campaign.router, prefix=settings.API_V1_PREFIX)
app.include_router(knowledge.router, prefix=settings.API_V1_PREFIX)
app.include_router(rag.router, prefix=settings.API_V1_PREFIX)


@app.get("/")
async def root() -> dict[str, str]:
    """Root welcome endpoint."""
    return {
        "message": f"Welcome to {settings.PROJECT_NAME}",
        "version": settings.VERSION,
        "docs": "/docs",
    }


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness/readiness probe including database ping."""
    db_ok = ping_database()
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "up" if db_ok else "down",
    }
