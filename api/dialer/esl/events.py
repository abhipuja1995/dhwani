"""
ESL event handlers — wire up on startup via esl_client.on().

Flow for a predictive dial leg:
  1. CHANNEL_ANSWER  → AMD kicks off (set in dialplan)
  2. DETECTED_SPEECH → AMD result: HUMAN → bridge to agent; MACHINE → hangup
  3. CHANNEL_BRIDGE  → mark call bridged, start duration timer
  4. CHANNEL_HANGUP  → update call record, release agent
"""
from __future__ import annotations
import logging
import ESL
from datetime import datetime, timezone

from dialer.esl.client import esl_client

log = logging.getLogger(__name__)

# Injected at startup to avoid circular imports
_repo_factory = None


def register(repo_factory):
    global _repo_factory
    _repo_factory = repo_factory

    esl_client.on("CHANNEL_ANSWER", _on_answer)
    esl_client.on("DETECTED_SPEECH", _on_amd_result)
    esl_client.on("CHANNEL_BRIDGE", _on_bridge)
    esl_client.on("CHANNEL_HANGUP_COMPLETE", _on_hangup)
    esl_client.on("CUSTOM", _on_custom)
    log.info("ESL event handlers registered")


async def _on_answer(event: ESL.ESLevent):
    uuid = event.getHeader("Unique-ID")
    direction = event.getHeader("Call-Direction")
    if direction != "outbound":
        return
    log.debug(f"ANSWER outbound uuid={uuid}")
    # AMD is triggered by dialplan execute_on_answer; nothing more to do here


async def _on_amd_result(event: ESL.ESLevent):
    """mod_spandsp fires DETECTED_SPEECH with AMD result in Speech-Type header."""
    uuid = event.getHeader("Unique-ID")
    result = event.getHeader("Speech-Type") or ""   # HUMAN | MACHINE | NOTSURE | TOOLONG

    log.info(f"AMD uuid={uuid} result={result}")

    if not _repo_factory:
        return

    async with _repo_factory() as repos:
        call = await repos.calls.get_by_fs_uuid(uuid)
        if not call:
            return

        amd = result.upper()
        await repos.calls.update(call.id, amd_result=amd)

        if amd == "HUMAN":
            agent = await repos.agents.next_available(call.campaign_id)
            if agent:
                await repos.agents.set_status(agent.id, "ringing", current_call_id=call.id)
                await repos.calls.update(call.id, status="human", agent_id=agent.id)
                await repos.commit()

                # Originate call to agent; FreeSWITCH bridges it to the parked customer leg
                from dialer.config import settings
                result = await esl_client.api(
                    f"originate {{ignore_early_media=true,"
                    f"origination_caller_id_name='Customer',"
                    f"origination_caller_id_number=0000000000}}"
                    f"user/{agent.username}@{settings.fs_domain} "
                    f"&bridge({uuid})"
                )
                if result.startswith("+OK"):
                    await repos.calls.update(call.id, status="bridged",
                                              bridged_at=datetime.now(timezone.utc))
                    await repos.agents.set_status(agent.id, "in_call")
                    log.info(f"Bridged customer uuid={uuid} to agent={agent.username}")
                else:
                    log.warning(f"Agent originate failed: {result} — dropping call uuid={uuid}")
                    await repos.agents.set_status(agent.id, "available", current_call_id=None)
                    await repos.calls.update(call.id, status="completed")
                    await esl_client.hangup(uuid, "NO_USER_RESPONSE")
                return

            # No agent available — TRAI drop
            log.warning(f"No agent available for human call uuid={uuid} — TRAI drop")
            await repos.calls.update(call.id, status="completed")
            await esl_client.hangup(uuid, "NO_USER_RESPONSE")
        else:
            # Machine or unclear — hang up cleanly
            await repos.calls.update(call.id, status="machine" if amd == "MACHINE" else "failed")
            await esl_client.hangup(uuid, "NORMAL_CLEARING")


async def _on_bridge(event: ESL.ESLevent):
    uuid = event.getHeader("Unique-ID")
    log.debug(f"BRIDGE uuid={uuid}")


async def _on_hangup(event: ESL.ESLevent):
    uuid = event.getHeader("Unique-ID")
    cause = event.getHeader("Hangup-Cause") or "UNKNOWN"
    duration = event.getHeader("variable_duration") or "0"

    if not _repo_factory:
        return

    async with _repo_factory() as repos:
        call = await repos.calls.get_by_fs_uuid(uuid)
        if not call:
            return

        await repos.calls.update(
            call.id,
            status="completed",
            duration_seconds=int(duration),
            ended_at=datetime.now(timezone.utc),
        )
        # Free the agent
        if call.agent_id:
            await repos.agents.set_status(call.agent_id, "wrap_up", current_call_id=None)

        log.info(f"HANGUP uuid={uuid} cause={cause} duration={duration}s")


async def _on_custom(event: ESL.ESLevent):
    subclass = event.getHeader("Event-Subclass") or ""
    if "sofia::register" in subclass:
        user = event.getHeader("from-user") or ""
        status = event.getHeader("status") or ""
        log.debug(f"SIP register: user={user} status={status}")


