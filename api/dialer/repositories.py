from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from dialer.tables import Campaign, Contact, Call, Agent


class CampaignRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Campaign:
        obj = Campaign(**kwargs)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get(self, id: str) -> Optional[Campaign]:
        return await self.db.get(Campaign, id)

    async def list(self) -> list[Campaign]:
        result = await self.db.execute(select(Campaign).order_by(Campaign.created_at.desc()))
        return list(result.scalars().all())

    async def update(self, id: str, **kwargs) -> Optional[Campaign]:
        kwargs["updated_at"] = datetime.now(timezone.utc)
        await self.db.execute(update(Campaign).where(Campaign.id == id).values(**kwargs))
        return await self.get(id)

    async def contact_counts(self, campaign_id: str) -> dict:
        rows = await self.db.execute(
            select(Contact.status, func.count())
            .where(Contact.campaign_id == campaign_id)
            .group_by(Contact.status)
        )
        return dict(rows.all())

    async def stats(self, campaign_id: str) -> dict:
        """Return contact counts for a campaign by status."""
        counts = await self.contact_counts(campaign_id)
        total = sum(counts.values())
        dialed = sum(v for k, v in counts.items() if k not in ("pending", "dnd"))
        answered = counts.get("answered", 0) + counts.get("completed", 0)
        # Drops = human-answered calls with no agent (tracked separately in CallRepo)
        return {
            "total_contacts": total,
            "dialed": dialed,
            "answered": answered,
            "dropped": 0,
            "current_drop_rate": 0.0,
        }


class ContactRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Contact:
        obj = Contact(**kwargs)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def bulk_create(self, contacts: list[dict]) -> int:
        objects = [Contact(**c) for c in contacts]
        self.db.add_all(objects)
        await self.db.flush()
        return len(objects)

    async def list_pending(self, campaign_id: str, limit: int = 100) -> list[Contact]:
        result = await self.db.execute(
            select(Contact)
            .where(Contact.campaign_id == campaign_id, Contact.status == "pending", Contact.is_dnd == False)
            .order_by(Contact.id)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def mark_dnd(self, phone_numbers: list[str]) -> int:
        result = await self.db.execute(
            update(Contact).where(Contact.phone.in_(phone_numbers)).values(is_dnd=True, status="dnd")
        )
        return result.rowcount

    async def update(self, id: str, **kwargs) -> None:
        await self.db.execute(update(Contact).where(Contact.id == id).values(**kwargs))


class CallRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Call:
        obj = Call(**kwargs)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get(self, id: str) -> Optional[Call]:
        return await self.db.get(Call, id)

    async def get_by_fs_uuid(self, fs_uuid: str) -> Optional[Call]:
        result = await self.db.execute(select(Call).where(Call.fs_uuid == fs_uuid))
        return result.scalar_one_or_none()

    async def update(self, id: str, **kwargs) -> None:
        await self.db.execute(update(Call).where(Call.id == id).values(**kwargs))

    async def drop_count_last_n_minutes(self, campaign_id: str, minutes: int = 15) -> tuple[int, int]:
        """Returns (total_answered, drops) in the last N minutes."""
        from sqlalchemy import and_
        cutoff = datetime.now(timezone.utc).timestamp() - (minutes * 60)
        rows = await self.db.execute(
            select(Call.amd_result, func.count())
            .where(
                Call.campaign_id == campaign_id,
                Call.started_at >= datetime.fromtimestamp(cutoff, tz=timezone.utc),
                Call.amd_result == "HUMAN",
            )
            .group_by(Call.amd_result)
        )
        total = sum(c for _, c in rows.all())
        # Drops = HUMAN calls that were never bridged (no agent available)
        drop_rows = await self.db.execute(
            select(func.count(Call.id))
            .where(
                Call.campaign_id == campaign_id,
                Call.started_at >= datetime.fromtimestamp(cutoff, tz=timezone.utc),
                Call.amd_result == "HUMAN",
                Call.agent_id == None,
            )
        )
        drops = drop_rows.scalar() or 0
        return total, drops


class AgentRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, **kwargs) -> Agent:
        obj = Agent(**kwargs)
        self.db.add(obj)
        await self.db.flush()
        return obj

    async def get(self, id: str) -> Optional[Agent]:
        return await self.db.get(Agent, id)

    async def get_by_username(self, username: str) -> Optional[Agent]:
        result = await self.db.execute(select(Agent).where(Agent.username == username))
        return result.scalar_one_or_none()

    async def list(self) -> list[Agent]:
        result = await self.db.execute(select(Agent))
        return list(result.scalars().all())

    async def set_status(self, id: str, status: str, **kwargs) -> None:
        await self.db.execute(
            update(Agent).where(Agent.id == id).values(status=status, **kwargs)
        )

    async def next_available(self, campaign_id: str = None) -> Optional[Agent]:
        q = select(Agent).where(Agent.status == "available")
        if campaign_id:
            # Prefer agents who already have pending leads from this campaign assigned to them;
            # fall back to any available agent if none match.
            from dialer.tables import Contact
            preferred = await self.db.execute(
                q.join(Contact, (Contact.assigned_agent_id == Agent.id) &
                       (Contact.campaign_id == campaign_id) &
                       (Contact.status == "pending")).limit(1)
            )
            agent = preferred.scalar_one_or_none()
            if agent:
                return agent
        result = await self.db.execute(q.limit(1))
        return result.scalar_one_or_none()

    async def available_count(self) -> int:
        result = await self.db.execute(
            select(func.count()).where(Agent.status == "available")
        )
        return result.scalar() or 0

    async def in_call_count(self) -> int:
        result = await self.db.execute(
            select(func.count()).where(Agent.status == "in_call")
        )
        return result.scalar() or 0


class Repos:
    def __init__(self, db: AsyncSession):
        self.campaigns = CampaignRepo(db)
        self.contacts = ContactRepo(db)
        self.calls = CallRepo(db)
        self.agents = AgentRepo(db)
        self._db = db

    async def commit(self):
        await self._db.commit()
