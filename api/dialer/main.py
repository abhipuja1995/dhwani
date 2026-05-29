from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dialer.config import settings
from dialer.esl.client import esl_client

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Connect ESL on startup
    loop = asyncio.get_event_loop()
    try:
        esl_client.connect(loop)
        log.info("ESL client started")

        # Register event handlers with DB repo factory
        from dialer.db import AsyncSessionLocal
        from dialer.repositories import Repos
        from contextlib import asynccontextmanager as acm

        @acm
        async def repo_factory():
            async with AsyncSessionLocal() as db:
                yield Repos(db)

        from dialer.esl.events import register
        register(repo_factory)
    except Exception as e:
        log.warning(f"ESL connect failed at startup (will retry): {e}")

    yield

    log.info("Shutting down")


app = FastAPI(
    title="Dialer API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
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
    return {"status": "ok"}


@app.get("/fs/status")
async def fs_status():
    """Check FreeSWITCH connectivity."""
    try:
        result = await esl_client.api("status")
        return {"connected": True, "response": result}
    except Exception as e:
        return {"connected": False, "error": str(e)}
