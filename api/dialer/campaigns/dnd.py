"""
TRAI DND (Do Not Disturb) scrubbing.

TRAI's NCRCP portal provides an API to check if a number is registered on
the national DND list. In dev/test, we simulate with a local blocklist.

For production: register at https://www.ncrcp.gov.in and use your API key.
"""
from __future__ import annotations
import logging
import httpx
from dialer.config import settings

log = logging.getLogger(__name__)


async def scrub_dnd(campaign_id: str, phone_numbers: list[str]) -> list[str]:
    """
    Check phone_numbers against TRAI DND and mark flagged ones in DB.
    Returns list of DND numbers found.
    """
    if not settings.trai_api_key:
        log.info("TRAI DND key not set — skipping DND scrub (dev mode)")
        return []

    dnd_numbers = await _check_trai_api(phone_numbers)

    if dnd_numbers:
        from dialer.db import AsyncSessionLocal
        from dialer.repositories import Repos
        async with AsyncSessionLocal() as db:
            repos = Repos(db)
            count = await repos.contacts.mark_dnd(dnd_numbers)
            await repos.commit()
            log.info(f"DND scrub: {count} numbers marked DND for campaign {campaign_id}")

    return dnd_numbers


async def _check_trai_api(phone_numbers: list[str]) -> list[str]:
    """
    TRAI NCRCP bulk check endpoint.
    Batches of 100 numbers per request.
    """
    dnd = []
    batch_size = 100

    async with httpx.AsyncClient(timeout=30) as client:
        for i in range(0, len(phone_numbers), batch_size):
            batch = phone_numbers[i:i + batch_size]
            try:
                resp = await client.post(
                    f"{settings.trai_api_url}/dnd/check",
                    headers={"Authorization": f"Bearer {settings.trai_api_key}"},
                    json={"numbers": batch},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    dnd.extend(data.get("dnd_numbers", []))
                else:
                    log.warning(f"TRAI API returned {resp.status_code}: {resp.text}")
            except Exception as e:
                log.error(f"TRAI DND API error: {e}")

    return dnd
