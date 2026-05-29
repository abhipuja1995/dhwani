from __future__ import annotations
import hashlib
import hmac
import time
import logging
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from dialer.db import get_db
from dialer.models import AgentCreate, AgentOut, TurnCredentials
from dialer.repositories import Repos
from dialer.config import settings

log = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])

# WebSocket manager: agent_id → WebSocket
_connections: dict[str, WebSocket] = {}


def get_repos(db=Depends(get_db)) -> Repos:
    return Repos(db)


@router.post("/", response_model=AgentOut, status_code=201)
async def create_agent(body: AgentCreate, repos: Repos = Depends(get_repos)):
    import bcrypt as _bcrypt
    existing = await repos.agents.get_by_username(body.username)
    if existing:
        raise HTTPException(409, f"Agent '{body.username}' already exists")

    hashed = _bcrypt.hashpw(body.password.encode(), _bcrypt.gensalt()).decode()
    agent = await repos.agents.create(
        username=body.username,
        display_name=body.display_name,
        hashed_password=hashed,
        skills=body.skills,
    )
    await repos.commit()
    return agent


@router.get("/", response_model=list[AgentOut])
async def list_agents(repos: Repos = Depends(get_repos)):
    return await repos.agents.list()


@router.patch("/{agent_id}/status")
async def set_agent_status(agent_id: str, status: str, repos: Repos = Depends(get_repos)):
    valid = {"available", "break", "offline", "wrap_up"}
    if status not in valid:
        raise HTTPException(400, f"Status must be one of {valid}")
    await repos.agents.set_status(agent_id, status)
    await repos.commit()
    await _broadcast_agent_state(agent_id, status)
    return {"agent_id": agent_id, "status": status}


@router.get("/turn-credentials", response_model=TurnCredentials)
async def get_turn_credentials():
    """
    Generate short-lived TURN credentials using HMAC-SHA1 over the TURN secret.
    Compatible with coturn time-limited credential scheme.
    """
    ttl = 86400
    timestamp = int(time.time()) + ttl
    username = f"{timestamp}:dialer_agent"
    password = hmac.new(
        settings.turn_secret.encode(),
        username.encode(),
        hashlib.sha1,
    ).digest()
    import base64
    credential = base64.b64encode(password).decode()

    return TurnCredentials(
        urls=[
            f"stun:{settings.turn_host}:{settings.turn_port}",
            f"turn:{settings.turn_host}:{settings.turn_port}?transport=udp",
            f"turn:{settings.turn_host}:{settings.turn_port}?transport=tcp",
        ],
        username=username,
        credential=credential,
        ttl=ttl,
    )


@router.websocket("/ws/{agent_id}")
async def agent_ws(agent_id: str, ws: WebSocket):
    """Real-time agent state channel: call events, status updates."""
    await ws.accept()
    _connections[agent_id] = ws
    log.info(f"Agent WS connected: {agent_id}")
    try:
        while True:
            msg = await ws.receive_json()
            await _handle_agent_message(agent_id, msg)
    except WebSocketDisconnect:
        _connections.pop(agent_id, None)
        log.info(f"Agent WS disconnected: {agent_id}")


async def _handle_agent_message(agent_id: str, msg: dict):
    """Handle messages from agent browser (status changes, call dispositions)."""
    action = msg.get("action")
    if action == "set_status":
        from dialer.db import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            repos = Repos(db)
            await repos.agents.set_status(agent_id, msg["status"])
            await repos.commit()


async def _broadcast_agent_state(agent_id: str, status: str):
    ws = _connections.get(agent_id)
    if ws:
        try:
            await ws.send_json({"event": "status_change", "status": status})
        except Exception:
            _connections.pop(agent_id, None)


async def notify_agent_incoming(agent_id: str, call_data: dict):
    """Called by pacing engine when a customer is being bridged to this agent."""
    ws = _connections.get(agent_id)
    if ws:
        try:
            await ws.send_json({"event": "incoming_call", **call_data})
        except Exception:
            _connections.pop(agent_id, None)
