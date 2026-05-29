from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime,
    ForeignKey, JSON, Enum as SAEnum, Text
)
from sqlalchemy.orm import DeclarativeBase, relationship


def utcnow():
    return datetime.now(timezone.utc)


def new_uuid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Campaign(Base):
    __tablename__ = "campaigns"

    id = Column(String, primary_key=True, default=new_uuid)
    name = Column(String, nullable=False)
    type = Column(String, nullable=False, default="batch")
    dial_mode = Column(String, nullable=False, default="progressive")
    status = Column(String, nullable=False, default="draft")
    caller_id = Column(String)
    dial_ratio = Column(Float, default=1.5)
    max_drop_rate = Column(Float, default=0.03)
    retry_attempts = Column(Integer, default=3)
    retry_delay_minutes = Column(Integer, default=60)
    schedule_start = Column(DateTime(timezone=True))
    schedule_end = Column(DateTime(timezone=True))
    calling_hours_start = Column(String, default="09:00")
    calling_hours_end = Column(String, default="21:00")
    timezone = Column(String, default="Asia/Kolkata")
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    contacts = relationship("Contact", back_populates="campaign", lazy="select")
    calls = relationship("Call", back_populates="campaign", lazy="select")


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(String, primary_key=True, default=new_uuid)
    campaign_id = Column(String, ForeignKey("campaigns.id"), nullable=False, index=True)
    phone = Column(String, nullable=False)
    name = Column(String)
    language = Column(String, default="hi")
    custom_data = Column(JSON)
    status = Column(String, default="pending")
    attempts = Column(Integer, default=0)
    last_dialed_at = Column(DateTime(timezone=True))
    is_dnd = Column(Boolean, default=False)

    # Admin: supervisor pre-assigns a lead to a specific agent
    assigned_agent_id = Column(String, ForeignKey("agents.id"), index=True)

    campaign = relationship("Campaign", back_populates="contacts")
    calls = relationship("Call", back_populates="contact")


class Call(Base):
    __tablename__ = "calls"

    id = Column(String, primary_key=True, default=new_uuid)
    campaign_id = Column(String, ForeignKey("campaigns.id"), nullable=False, index=True)
    contact_id = Column(String, ForeignKey("contacts.id"), nullable=False, index=True)
    agent_id = Column(String, ForeignKey("agents.id"), index=True)
    fs_uuid = Column(String, index=True)        # FreeSWITCH channel UUID
    status = Column(String, default="initiated")
    amd_result = Column(String)
    duration_seconds = Column(Integer)
    recording_path = Column(String)
    started_at = Column(DateTime(timezone=True))
    bridged_at = Column(DateTime(timezone=True))
    ended_at = Column(DateTime(timezone=True))

    disposition = Column(String)          # ptp / callback / refused / no_answer / dispute
    ptp_amount = Column(Float)
    ptp_date = Column(DateTime(timezone=True))
    notes = Column(Text)

    campaign = relationship("Campaign", back_populates="calls")
    contact = relationship("Contact", back_populates="calls")
    agent = relationship("Agent", back_populates="calls", foreign_keys=[agent_id])


class Agent(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True, default=new_uuid)
    username = Column(String, unique=True, nullable=False)
    display_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    skills = Column(JSON, default=list)
    status = Column(String, default="offline")
    current_call_id = Column(String, ForeignKey("calls.id"))

    calls = relationship("Call", back_populates="agent", foreign_keys="[Call.agent_id]")
