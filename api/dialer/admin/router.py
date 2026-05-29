"""Admin dashboard API — agent monitoring, lead assignment, campaign control."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, update

from dialer.db import get_db
from dialer.repositories import Repos
from dialer.tables import Agent, Contact, Call, Campaign

router = APIRouter(prefix="/admin", tags=["admin"])


def get_repos(db=Depends(get_db)) -> Repos:
    return Repos(db)


def _today_start() -> datetime:
    return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


# ── Overview KPIs ──────────────────────────────────────────────────────────────

@router.get("/overview")
async def overview(repos: Repos = Depends(get_repos)):
    """Live KPI summary for the dashboard header."""
    agents = await repos.agents.list()
    by_status: dict[str, int] = {}
    for a in agents:
        by_status[a.status] = by_status.get(a.status, 0) + 1

    today = _today_start()

    calls_res = await repos._db.execute(
        select(func.count(Call.id)).where(Call.started_at >= today)
    )
    calls_today = calls_res.scalar() or 0

    ptp_res = await repos._db.execute(
        select(
            func.count(Call.id),
            func.coalesce(func.sum(Call.ptp_amount), 0),
        ).where(Call.started_at >= today, Call.disposition == "ptp")
    )
    ptp_count, ptp_amount = ptp_res.one()

    pending_res = await repos._db.execute(
        select(func.count(Contact.id)).where(Contact.status == "pending")
    )
    pending = pending_res.scalar() or 0

    assigned_res = await repos._db.execute(
        select(func.count(Contact.id)).where(
            Contact.status == "pending",
            Contact.assigned_agent_id != None,  # noqa: E711
        )
    )
    assigned_pending = assigned_res.scalar() or 0

    return {
        "agents_total": len(agents),
        "agents_by_status": by_status,
        "agents_online": sum(v for k, v in by_status.items() if k != "offline"),
        "agents_in_call": by_status.get("in_call", 0),
        "agents_available": by_status.get("available", 0),
        "calls_today": calls_today,
        "ptps_today": int(ptp_count),
        "ptp_amount_today": float(ptp_amount),
        "pending_leads": pending,
        "assigned_leads": assigned_pending,
    }


# ── Live agent state ───────────────────────────────────────────────────────────

@router.get("/agents/live")
async def agents_live(repos: Repos = Depends(get_repos)):
    """All agents with current call details and today's performance stats."""
    agents = await repos.agents.list()
    today = _today_start()
    result = []

    for agent in agents:
        # Today's calls
        calls_res = await repos._db.execute(
            select(
                func.count(Call.id),
                func.coalesce(func.avg(Call.duration_seconds), 0),
            ).where(Call.agent_id == agent.id, Call.started_at >= today)
        )
        total_calls, avg_aht = calls_res.one()

        # Today's PTPs
        ptp_res = await repos._db.execute(
            select(
                func.count(Call.id),
                func.coalesce(func.sum(Call.ptp_amount), 0),
            ).where(
                Call.agent_id == agent.id,
                Call.started_at >= today,
                Call.disposition == "ptp",
            )
        )
        ptps, ptp_amount = ptp_res.one()

        # Leads assigned but not yet dialed
        assigned_res = await repos._db.execute(
            select(func.count(Contact.id)).where(
                Contact.assigned_agent_id == agent.id,
                Contact.status == "pending",
            )
        )
        assigned_leads = assigned_res.scalar() or 0

        # Current call info
        current_call = None
        if agent.current_call_id:
            call = await repos.calls.get(agent.current_call_id)
            if call:
                contact_res = await repos._db.execute(
                    select(Contact).where(Contact.id == call.contact_id)
                )
                contact = contact_res.scalar_one_or_none()
                ref = call.bridged_at or call.started_at
                duration = int((datetime.now(timezone.utc) - ref).total_seconds()) if ref else 0
                current_call = {
                    "call_id": call.id,
                    "customer_name": contact.name if contact else "Unknown",
                    "customer_phone": contact.phone if contact else "",
                    "duration_seconds": duration,
                    "status": call.status,
                }

        result.append({
            "id": agent.id,
            "username": agent.username,
            "display_name": agent.display_name,
            "skills": agent.skills or [],
            "status": agent.status,
            "current_call": current_call,
            "assigned_leads": assigned_leads,
            "today": {
                "calls": int(total_calls),
                "ptps": int(ptps),
                "ptp_amount": float(ptp_amount),
                "avg_handle_time": int(avg_aht),
            },
        })

    return result


# ── Pending leads priority queue ───────────────────────────────────────────────

@router.get("/leads/pending")
async def leads_pending(
    campaign_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    repos: Repos = Depends(get_repos),
):
    """Priority-scored pending leads for the assignment queue."""
    q = (
        select(Contact, Campaign.name.label("campaign_name"))
        .join(Campaign, Contact.campaign_id == Campaign.id)
        .where(Contact.status == "pending")
        .order_by(Contact.attempts.asc(), Contact.id.asc())
        .limit(limit)
    )
    if campaign_id:
        q = q.where(Contact.campaign_id == campaign_id)

    rows = (await repos._db.execute(q)).all()

    result = []
    for contact, campaign_name in rows:
        custom = contact.custom_data or {}
        dpd = int(custom.get("dpd", 0))
        outstanding = float(custom.get("outstanding", 0))
        attempts = contact.attempts or 0

        # Priority score 0-99: DPD heaviest weight, then amount, then fewer attempts = higher priority
        dpd_score    = min(40, dpd * 0.8)
        amount_score = min(35, outstanding / 1000 * 2)
        attempt_score = max(0, 24 - attempts * 8)
        score = int(min(99, dpd_score + amount_score + attempt_score))

        # Assigned agent name
        assigned_name = None
        if contact.assigned_agent_id:
            ag = await repos.agents.get(contact.assigned_agent_id)
            assigned_name = ag.display_name if ag else None

        result.append({
            "id": contact.id,
            "phone": contact.phone,
            "name": contact.name or "Unknown",
            "campaign_id": contact.campaign_id,
            "campaign_name": campaign_name,
            "status": contact.status,
            "attempts": attempts,
            "last_dialed_at": contact.last_dialed_at.isoformat() if contact.last_dialed_at else None,
            "assigned_agent_id": contact.assigned_agent_id,
            "assigned_agent_name": assigned_name,
            "priority_score": score,
            "dpd": dpd,
            "outstanding": outstanding,
            "language": contact.language,
        })

    result.sort(key=lambda x: x["priority_score"], reverse=True)
    return result


# ── Lead assignment ────────────────────────────────────────────────────────────

@router.post("/leads/{contact_id}/assign/{agent_id}")
async def assign_lead(
    contact_id: str,
    agent_id: str,
    repos: Repos = Depends(get_repos),
):
    contact = await repos._db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")

    agent = await repos.agents.get(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")

    await repos._db.execute(
        update(Contact).where(Contact.id == contact_id).values(assigned_agent_id=agent_id)
    )
    await repos.commit()

    # Notify agent via WebSocket
    try:
        from dialer.agents.router import notify_agent_incoming
        await notify_agent_incoming(agent_id, {
            "type": "assignment",
            "contact_id": contact_id,
            "customer_name": contact.name,
            "customer_phone": contact.phone,
        })
    except Exception:
        pass

    return {
        "contact_id": contact_id,
        "agent_id": agent_id,
        "agent_name": agent.display_name,
        "customer_name": contact.name,
        "customer_phone": contact.phone,
    }


@router.delete("/leads/{contact_id}/assign")
async def unassign_lead(contact_id: str, repos: Repos = Depends(get_repos)):
    """Remove agent assignment from a lead."""
    contact = await repos._db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(404, "Contact not found")
    await repos._db.execute(
        update(Contact).where(Contact.id == contact_id).values(assigned_agent_id=None)
    )
    await repos.commit()
    return {"contact_id": contact_id, "assigned_agent_id": None}


@router.post("/leads/auto-assign")
async def auto_assign(
    campaign_id: Optional[str] = Query(None),
    repos: Repos = Depends(get_repos),
):
    """Round-robin distribute unassigned pending leads to available agents."""
    avail_res = await repos._db.execute(
        select(Agent).where(Agent.status == "available")
    )
    available = list(avail_res.scalars().all())

    if not available:
        return {"assigned": 0, "message": "No available agents right now"}

    # Unassigned pending leads
    q = (
        select(Contact)
        .where(Contact.status == "pending", Contact.assigned_agent_id == None)  # noqa: E711
        .order_by(Contact.attempts.asc())
        .limit(len(available) * 10)
    )
    if campaign_id:
        q = q.where(Contact.campaign_id == campaign_id)

    leads_res = await repos._db.execute(q)
    leads = list(leads_res.scalars().all())

    assigned = 0
    for i, lead in enumerate(leads):
        agent = available[i % len(available)]
        await repos._db.execute(
            update(Contact).where(Contact.id == lead.id).values(assigned_agent_id=agent.id)
        )
        assigned += 1

    await repos.commit()
    return {
        "assigned": assigned,
        "agents": len(available),
        "message": f"Assigned {assigned} leads across {min(len(available), len(leads))} agents",
    }


# ── Leaderboard ────────────────────────────────────────────────────────────────

@router.get("/leaderboard")
async def leaderboard(repos: Repos = Depends(get_repos)):
    """Today's agent performance ranked by PTP amount secured."""
    agents = await repos.agents.list()
    today = _today_start()
    board = []

    for agent in agents:
        calls_res = await repos._db.execute(
            select(
                func.count(Call.id),
                func.coalesce(func.sum(Call.ptp_amount), 0),
                func.coalesce(func.avg(Call.duration_seconds), 0),
            ).where(Call.agent_id == agent.id, Call.started_at >= today)
        )
        total_calls, ptp_amount, avg_aht = calls_res.one()

        ptp_res = await repos._db.execute(
            select(func.count(Call.id)).where(
                Call.agent_id == agent.id,
                Call.started_at >= today,
                Call.disposition == "ptp",
            )
        )
        ptps = ptp_res.scalar() or 0

        board.append({
            "agent_id": agent.id,
            "display_name": agent.display_name,
            "username": agent.username,
            "status": agent.status,
            "calls": int(total_calls),
            "ptps": int(ptps),
            "ptp_amount": float(ptp_amount),
            "avg_handle_time": int(avg_aht),
            "connect_rate": round(ptps / total_calls * 100, 1) if total_calls else 0.0,
        })

    board.sort(key=lambda x: (x["ptp_amount"], x["calls"]), reverse=True)
    return board
