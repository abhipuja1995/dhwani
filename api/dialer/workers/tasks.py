"""
Celery tasks:
  - pacing_tick: runs every 30s, calculates how many calls to originate per active campaign
  - launch_campaign: called once when a campaign is started (seeds initial dial batch)
  - dial_contact: originates a single outbound call for a contact
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

from dialer.workers.celery_app import app

log = logging.getLogger(__name__)


def run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@app.task(name="dialer.workers.tasks.pacing_tick", bind=True, max_retries=3)
def pacing_tick(self):
    """
    Predictive pacing algorithm — runs every 30s via Celery beat.

    For each active campaign:
      1. Count available agents (A) and in-call agents (B)
      2. Check drop rate in last 15 min — pause if ≥ max_drop_rate (TRAI compliance)
      3. Calculate calls_to_dial = max(0, A × dial_ratio - active_calls)
      4. Originate that many calls against pending contacts
    """
    run_async(_pacing_tick_async())


async def _pacing_tick_async():
    from dialer.db import AsyncSessionLocal
    from dialer.repositories import Repos
    from dialer.tables import Campaign
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        repos = Repos(db)
        result = await db.execute(select(Campaign).where(Campaign.status == "active"))
        campaigns = list(result.scalars().all())

    for campaign in campaigns:
        try:
            await _pace_campaign(campaign)
        except Exception as e:
            log.error(f"Pacing error for campaign {campaign.id}: {e}")


async def _pace_campaign(campaign):
    from dialer.db import AsyncSessionLocal
    from dialer.repositories import Repos
    from dialer.esl.client import esl_client
    import redis.asyncio as aioredis
    from dialer.config import settings

    async with AsyncSessionLocal() as db:
        repos = Repos(db)

        available = await repos.agents.available_count()
        in_call = await repos.agents.in_call_count()

        total_answered, drops = await repos.calls.drop_count_last_n_minutes(campaign.id, 15)
        drop_rate = drops / total_answered if total_answered > 0 else 0.0

        # TRAI compliance gate: pause dialing if drop rate exceeds limit
        if drop_rate >= campaign.max_drop_rate:
            log.warning(
                f"Campaign {campaign.id}: drop rate {drop_rate:.1%} ≥ limit {campaign.max_drop_rate:.1%} "
                f"— pausing dial-out for compliance"
            )
            return

        if available == 0:
            return  # no agents ready

        # Check calling hours (Asia/Kolkata)
        if not _within_calling_hours(campaign):
            return

        # How many lines to dial
        # Dial ratio: for every available agent, dial ratio × 1 calls
        active_calls = await _active_call_count(campaign.id)
        target = int((available + in_call) * campaign.dial_ratio)
        to_dial = max(0, target - active_calls)

        if to_dial == 0:
            return

        log.info(
            f"Pacing campaign={campaign.id} available={available} in_call={in_call} "
            f"active={active_calls} target={target} dialing={to_dial}"
        )

        contacts = await repos.contacts.list_pending(campaign.id, limit=to_dial)
        for contact in contacts:
            dial_contact.delay(str(campaign.id), str(contact.id))
            await repos.contacts.update(contact.id, status="dialing",
                                        last_dialed_at=datetime.now(timezone.utc))
        await repos.commit()


async def _active_call_count(campaign_id: str) -> int:
    from dialer.db import AsyncSessionLocal
    from dialer.repositories import Repos
    from sqlalchemy import select, func
    from dialer.tables import Call
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(func.count()).where(
                Call.campaign_id == campaign_id,
                Call.status.in_(["initiated", "ringing", "answered", "human", "bridged"]),
            )
        )
        return result.scalar() or 0


def _within_calling_hours(campaign) -> bool:
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(campaign.timezone or "Asia/Kolkata")
    now = datetime.now(tz)
    start_h, start_m = map(int, campaign.calling_hours_start.split(":"))
    end_h, end_m = map(int, campaign.calling_hours_end.split(":"))
    current_minutes = now.hour * 60 + now.minute
    start_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m
    return start_minutes <= current_minutes < end_minutes


@app.task(name="dialer.workers.tasks.launch_campaign")
def launch_campaign(campaign_id: str):
    """Seed the first batch of calls when a campaign is activated."""
    log.info(f"Launching campaign {campaign_id}")
    pacing_tick.delay()  # trigger immediate first tick


@app.task(name="dialer.workers.tasks.dial_contact", bind=True, max_retries=2)
def dial_contact(self, campaign_id: str, contact_id: str):
    run_async(_dial_contact_async(campaign_id, contact_id))


async def _dial_contact_async(campaign_id: str, contact_id: str):
    from dialer.db import AsyncSessionLocal
    from dialer.repositories import Repos
    from dialer.esl.client import esl_client
    from dialer.config import settings
    from datetime import datetime, timezone

    async with AsyncSessionLocal() as db:
        repos = Repos(db)
        from dialer.tables import Contact
        contact = await db.get(Contact, contact_id)
        if not contact:
            log.error(f"Contact {contact_id} not found")
            return

        campaign = await repos.campaigns.get(campaign_id)
        caller_id = (campaign.caller_id or settings.sip_trunk_caller_id) if campaign else "0000000000"

        # Originate call via FreeSWITCH.
        # Dialplan handles fallback: tries SIP trunk first, falls through to
        # loopback echo if no trunk is configured (safe for WiFi testing).
        phone = contact.phone  # E.164 e.g. +919876543210
        digits = phone.lstrip("+")
        destination = f"sofia/gateway/pstn_trunk/{digits}"

        fs_uuid = await esl_client.originate(
            destination=destination,
            caller_id_name="Dialer",
            caller_id_number=caller_id,
            variables={
                "dialer_campaign_id": campaign_id,
                "dialer_contact_id": contact_id,
                "dialer_language": contact.language or "hi",
            },
        )

        if fs_uuid:
            call = await repos.calls.create(
                campaign_id=campaign_id,
                contact_id=contact_id,
                fs_uuid=fs_uuid,
                status="initiated",
                started_at=datetime.now(timezone.utc),
            )
            await repos.contacts.update(contact_id, status="dialing", attempts=contact.attempts + 1)
            await repos.commit()
            log.info(f"Originated call uuid={fs_uuid} contact={contact.phone}")
        else:
            await repos.contacts.update(contact_id, status="failed")
            await repos.commit()
            log.warning(f"Failed to originate call for contact {contact_id}")
