from __future__ import annotations
import hashlib
import hmac
import time
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select, func

from dialer.db import get_db
from dialer.models import AgentCreate, AgentOut, TurnCredentials
from dialer.repositories import Repos
from dialer.tables import Call, Contact, Agent
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


# ── Agent self-performance stats ───────────────────────────────────────────────

def _period_range(period: str) -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "yesterday":
        return today - timedelta(days=1), today
    elif period == "week":
        return today - timedelta(days=today.weekday()), now   # Mon of current week
    elif period == "month":
        return today.replace(day=1), now
    elif period == "ytd":
        return today.replace(month=1, day=1), now
    else:  # today (default)
        return today, now


@router.get("/{agent_id}/stats")
async def agent_stats(
    agent_id: str,
    period: str = Query("today", regex="^(today|yesterday|week|month|ytd)$"),
    repos: Repos = Depends(get_repos),
):
    """Aggregated performance stats for an agent over a time period."""
    agent = await repos.agents.get(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    start, end = _period_range(period)

    # Core call metrics
    row = (await repos._db.execute(
        select(
            func.count(Call.id),
            func.coalesce(func.sum(Call.duration_seconds), 0),
            func.coalesce(func.avg(Call.duration_seconds), 0),
        ).where(Call.agent_id == agent_id, Call.started_at >= start, Call.started_at < end)
    )).one()
    total_calls, total_talk_secs, avg_aht = int(row[0]), int(row[1]), int(row[2])

    # PTPs
    ptp_row = (await repos._db.execute(
        select(
            func.count(Call.id),
            func.coalesce(func.sum(Call.ptp_amount), 0),
        ).where(
            Call.agent_id == agent_id,
            Call.started_at >= start,
            Call.started_at < end,
            Call.disposition == "ptp",
        )
    )).one()
    ptp_count, ptp_amount = int(ptp_row[0]), float(ptp_row[1])

    # Connected (AMD = HUMAN or disposition not null)
    connected_row = (await repos._db.execute(
        select(func.count(Call.id)).where(
            Call.agent_id == agent_id,
            Call.started_at >= start,
            Call.started_at < end,
            Call.amd_result == "HUMAN",
        )
    )).scalar() or 0

    # Dispositions breakdown
    disp_rows = (await repos._db.execute(
        select(Call.disposition, func.count(Call.id))
        .where(
            Call.agent_id == agent_id,
            Call.started_at >= start,
            Call.started_at < end,
            Call.disposition != None,  # noqa: E711
        )
        .group_by(Call.disposition)
    )).all()
    dispositions = {d: c for d, c in disp_rows}

    # Hourly distribution (local hour 0–23)
    hourly_rows = (await repos._db.execute(
        select(Call.started_at).where(
            Call.agent_id == agent_id,
            Call.started_at >= start,
            Call.started_at < end,
        )
    )).scalars().all()
    hourly: dict[int, int] = {}
    for ts in hourly_rows:
        if ts:
            h = ts.hour
            hourly[h] = hourly.get(h, 0) + 1

    # Rank among all agents for this period
    all_agents = await repos.agents.list()
    agent_ptp_amounts = []
    for a in all_agents:
        r = (await repos._db.execute(
            select(func.coalesce(func.sum(Call.ptp_amount), 0)).where(
                Call.agent_id == a.id,
                Call.started_at >= start,
                Call.started_at < end,
                Call.disposition == "ptp",
            )
        )).scalar() or 0
        agent_ptp_amounts.append((a.id, float(r)))
    agent_ptp_amounts.sort(key=lambda x: x[1], reverse=True)
    rank = next((i+1 for i, (aid, _) in enumerate(agent_ptp_amounts) if aid == agent_id), 1)

    return {
        "agent_id": agent_id,
        "display_name": agent.display_name,
        "period": period,
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "total_calls": total_calls,
        "connected": int(connected_row),
        "connect_rate": round(connected_row / total_calls * 100, 1) if total_calls else 0.0,
        "ptp_count": ptp_count,
        "ptp_amount": ptp_amount,
        "ptp_rate": round(ptp_count / total_calls * 100, 1) if total_calls else 0.0,
        "avg_handle_time": avg_aht,
        "total_talk_minutes": total_talk_secs // 60,
        "dispositions": dispositions,
        "hourly": hourly,
        "rank": rank,
        "total_agents": len(all_agents),
    }


@router.get("/{agent_id}/calls")
async def agent_calls(
    agent_id: str,
    period: str = Query("today", regex="^(today|yesterday|week|month|ytd)$"),
    limit: int = Query(30, le=100),
    repos: Repos = Depends(get_repos),
):
    """Recent call history for an agent over a time period."""
    agent = await repos.agents.get(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    start, end = _period_range(period)

    rows = (await repos._db.execute(
        select(Call, Contact.name.label("customer_name"), Contact.phone.label("customer_phone"))
        .join(Contact, Call.contact_id == Contact.id)
        .where(Call.agent_id == agent_id, Call.started_at >= start, Call.started_at < end)
        .order_by(Call.started_at.desc())
        .limit(limit)
    )).all()

    result = []
    for call, cname, cphone in rows:
        result.append({
            "id": call.id,
            "customer_name": cname or "Unknown",
            "customer_phone": cphone or "",
            "started_at": call.started_at.isoformat() if call.started_at else None,
            "duration_seconds": call.duration_seconds or 0,
            "status": call.status,
            "disposition": call.disposition,
            "ptp_amount": call.ptp_amount,
            "amd_result": call.amd_result,
        })
    return result
