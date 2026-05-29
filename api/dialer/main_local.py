"""
Local dev entry point — no FreeSWITCH, no Redis, SQLite database.

Run with:
    python3 -m uvicorn dialer.main_local:app --reload --port 8000
"""
from __future__ import annotations
import logging
import os
os.environ.setdefault("LOCAL", "1")

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Patch settings to SQLite before any other import
from dialer import config as _cfg
from dialer.config_local import local_settings
_cfg.settings = local_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Auto-create tables (no Alembic needed for local dev)
    from dialer.db import engine
    from dialer.tables import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("SQLite tables ready")
    yield


app = FastAPI(title="Dialer API (local)", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
from dialer.campaigns.router import router as campaigns_router
from dialer.agents.router import router as agents_router

app.include_router(campaigns_router)
app.include_router(agents_router)


@app.get("/health")
async def health():
    return {"status": "ok", "mode": "local", "db": "sqlite"}


@app.get("/fs/status")
async def fs_status():
    return {"connected": False, "mode": "local", "note": "FreeSWITCH not running in local mode"}
