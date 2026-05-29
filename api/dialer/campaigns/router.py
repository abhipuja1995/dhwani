from __future__ import annotations
import io
import logging
from datetime import datetime, timezone
from typing import Annotated

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks

from dialer.db import get_db
from dialer.models import CampaignCreate, CampaignUpdate, CampaignOut, ContactCreate, ContactOut
from dialer.repositories import Repos
from dialer.campaigns.dnd import scrub_dnd

log = logging.getLogger(__name__)
router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def get_repos(db=Depends(get_db)) -> Repos:
    return Repos(db)


async def _enrich(camp: object, repos: Repos) -> dict:
    """Merge ORM campaign with live contact stats into a CampaignOut-compatible dict."""
    data = {c.key: getattr(camp, c.key) for c in camp.__table__.columns}
    stats = await repos.campaigns.stats(camp.id)
    return {**data, **stats}


@router.post("/", response_model=CampaignOut, status_code=201)
async def create_campaign(body: CampaignCreate, repos: Repos = Depends(get_repos)):
    camp = await repos.campaigns.create(**body.model_dump())
    await repos.commit()
    return await _enrich(camp, repos)


@router.get("/", response_model=list[CampaignOut])
async def list_campaigns(repos: Repos = Depends(get_repos)):
    camps = await repos.campaigns.list()
    return [await _enrich(c, repos) for c in camps]


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: str, repos: Repos = Depends(get_repos)):
    camp = await repos.campaigns.get(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    return await _enrich(camp, repos)


@router.patch("/{campaign_id}", response_model=CampaignOut)
async def update_campaign(campaign_id: str, body: CampaignUpdate, repos: Repos = Depends(get_repos)):
    camp = await repos.campaigns.update(campaign_id, **body.model_dump(exclude_none=True))
    if not camp:
        raise HTTPException(404, "Campaign not found")
    await repos.commit()
    return camp


@router.post("/{campaign_id}/contacts/upload")
async def upload_contacts(
    campaign_id: str,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    repos: Repos = Depends(get_repos),
):
    """Accept CSV with columns: phone, name (optional), language (optional)."""
    camp = await repos.campaigns.get(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")

    raw = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception as e:
        raise HTTPException(400, f"Invalid CSV: {e}")

    if "phone" not in df.columns:
        raise HTTPException(400, "CSV must contain a 'phone' column")

    contacts = []
    errors = []
    for _, row in df.iterrows():
        try:
            c = ContactCreate(
                phone=str(row["phone"]),
                name=str(row.get("name", "")) or None,
                language=str(row.get("language", "hi")),
                custom_data={k: v for k, v in row.items() if k not in ("phone", "name", "language")},
            )
            contacts.append({**c.model_dump(), "campaign_id": campaign_id})
        except Exception as e:
            errors.append({"row": row.get("phone", "?"), "error": str(e)})

    count = await repos.contacts.bulk_create(contacts)
    await repos.commit()

    # Async DND scrub
    background_tasks.add_task(scrub_dnd, campaign_id, [c["phone"] for c in contacts])

    return {"imported": count, "errors": errors}


@router.post("/{campaign_id}/contacts", response_model=ContactOut, status_code=201)
async def add_contact(campaign_id: str, body: ContactCreate, repos: Repos = Depends(get_repos)):
    camp = await repos.campaigns.get(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    contact = await repos.contacts.create(**body.model_dump(), campaign_id=campaign_id)
    await repos.commit()
    return contact


@router.post("/{campaign_id}/start")
async def start_campaign(campaign_id: str, repos: Repos = Depends(get_repos)):
    from dialer.workers.tasks import launch_campaign
    camp = await repos.campaigns.get(campaign_id)
    if not camp:
        raise HTTPException(404, "Campaign not found")
    if camp.status not in ("draft", "paused"):
        raise HTTPException(400, f"Cannot start campaign in status '{camp.status}'")

    await repos.campaigns.update(campaign_id, status="active")
    await repos.commit()
    launch_campaign.delay(campaign_id)
    return {"status": "active", "campaign_id": campaign_id}


@router.post("/{campaign_id}/pause")
async def pause_campaign(campaign_id: str, repos: Repos = Depends(get_repos)):
    await repos.campaigns.update(campaign_id, status="paused")
    await repos.commit()
    return {"status": "paused"}
