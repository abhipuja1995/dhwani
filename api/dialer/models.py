from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, field_validator
import phonenumbers


# ── Enums ──────────────────────────────────────────────────────────────────────

class CampaignStatus(str, Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"


class CampaignType(str, Enum):
    batch = "batch"           # uploaded contact list
    triggered = "triggered"   # API-driven, event per contact
    scheduled = "scheduled"   # time-windowed


class DialMode(str, Enum):
    preview = "preview"
    progressive = "progressive"
    predictive = "predictive"


class ContactStatus(str, Enum):
    pending = "pending"
    dialing = "dialing"
    answered = "answered"
    no_answer = "no_answer"
    busy = "busy"
    voicemail = "voicemail"
    failed = "failed"
    dnd = "dnd"               # scrubbed by TRAI DND
    completed = "completed"


class CallStatus(str, Enum):
    initiated = "initiated"
    ringing = "ringing"
    answered = "answered"     # AMD still running
    human = "human"           # AMD: human detected, bridging
    machine = "machine"       # AMD: answering machine
    bridged = "bridged"       # connected to agent
    completed = "completed"
    failed = "failed"


class AgentStatus(str, Enum):
    offline = "offline"
    available = "available"
    ringing = "ringing"       # incoming bridge
    in_call = "in_call"
    wrap_up = "wrap_up"       # post-call disposition
    break_ = "break"


# ── Campaign ───────────────────────────────────────────────────────────────────

class CampaignCreate(BaseModel):
    name: str
    type: CampaignType = CampaignType.batch
    dial_mode: DialMode = DialMode.progressive
    caller_id: Optional[str] = None
    dial_ratio: float = 1.5        # for predictive: calls per available agent
    max_drop_rate: float = 0.03    # TRAI limit: 3%
    retry_attempts: int = 3
    retry_delay_minutes: int = 60
    schedule_start: Optional[datetime] = None
    schedule_end: Optional[datetime] = None
    calling_hours_start: str = "09:00"   # local time HH:MM
    calling_hours_end: str = "21:00"
    timezone: str = "Asia/Kolkata"
    notes: Optional[str] = None


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[CampaignStatus] = None
    dial_mode: Optional[DialMode] = None
    dial_ratio: Optional[float] = None
    calling_hours_start: Optional[str] = None
    calling_hours_end: Optional[str] = None


class CampaignOut(CampaignCreate):
    id: str
    status: CampaignStatus
    total_contacts: int = 0
    dialed: int = 0
    answered: int = 0
    dropped: int = 0
    current_drop_rate: float = 0.0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Contact ────────────────────────────────────────────────────────────────────

class ContactCreate(BaseModel):
    phone: str
    name: Optional[str] = None
    language: str = "hi"          # BCP-47 tag
    custom_data: Optional[dict] = None

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, v: str) -> str:
        try:
            parsed = phonenumbers.parse(v, "IN")
            if not phonenumbers.is_valid_number(parsed):
                raise ValueError(f"Invalid phone number: {v}")
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        except phonenumbers.NumberParseException as e:
            raise ValueError(str(e))


class ContactOut(ContactCreate):
    id: str
    campaign_id: str
    status: ContactStatus = ContactStatus.pending
    attempts: int = 0
    last_dialed_at: Optional[datetime] = None
    is_dnd: bool = False

    model_config = {"from_attributes": True}


# ── Call ───────────────────────────────────────────────────────────────────────

class CallOut(BaseModel):
    id: str
    campaign_id: str
    contact_id: str
    agent_id: Optional[str]
    fs_uuid: Optional[str]        # FreeSWITCH channel UUID
    status: CallStatus
    amd_result: Optional[str]     # HUMAN / MACHINE / NOTSURE / TOOLONG
    duration_seconds: Optional[int]
    recording_path: Optional[str]
    started_at: Optional[datetime]
    bridged_at: Optional[datetime]
    ended_at: Optional[datetime]

    model_config = {"from_attributes": True}


# ── Agent ──────────────────────────────────────────────────────────────────────

class AgentCreate(BaseModel):
    username: str              # maps to FreeSWITCH directory user id
    display_name: str
    password: str
    skills: list[str] = []


class AgentOut(BaseModel):
    id: str
    username: str
    display_name: str
    status: AgentStatus = AgentStatus.offline
    current_call_id: Optional[str] = None

    model_config = {"from_attributes": True}


# ── WebRTC / TURN ──────────────────────────────────────────────────────────────

class TurnCredentials(BaseModel):
    urls: list[str]
    username: str
    credential: str
    ttl: int = 86400


# ── Pacing stats (real-time) ───────────────────────────────────────────────────

class PacingStats(BaseModel):
    campaign_id: str
    available_agents: int
    in_call_agents: int
    active_calls: int
    calls_last_15min: int
    drops_last_15min: int
    current_drop_rate: float
    dial_ratio: float
    paused_for_compliance: bool
