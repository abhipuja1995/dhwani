"""
Async wrapper around the FreeSWITCH ESL (Event Socket Library).

ESL is synchronous; we run it in a thread pool and expose an async interface.
One persistent inbound connection handles all events; outbound API calls
use short-lived connections so we never block the event loop.
"""
from __future__ import annotations
import asyncio
import logging
import threading
from typing import Callable, Optional
import ESL

from dialer.config import settings

log = logging.getLogger(__name__)


class ESLClient:
    """Singleton ESL client. Call connect() once at startup."""

    def __init__(self):
        self._lock = threading.Lock()
        self._conn: Optional[ESL.ESLconnection] = None
        self._listeners: dict[str, list[Callable]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None

    # ── Connection ─────────────────────────────────────────────────────────────

    def connect(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._thread = threading.Thread(target=self._event_loop, daemon=True)
        self._thread.start()
        log.info("ESL event thread started")

    def _make_conn(self) -> ESL.ESLconnection:
        conn = ESL.ESLconnection(
            settings.fs_host,
            str(settings.fs_esl_port),
            settings.fs_esl_password,
        )
        if not conn.connected():
            raise ConnectionError(
                f"Cannot connect to FreeSWITCH ESL at "
                f"{settings.fs_host}:{settings.fs_esl_port}"
            )
        return conn

    def _event_loop(self):
        while True:
            try:
                conn = self._make_conn()
                with self._lock:
                    self._conn = conn
                log.info("ESL connected — subscribing to events")
                conn.events("plain", "ALL")

                while conn.connected():
                    event = conn.recvEventTimed(500)
                    if event:
                        self._dispatch(event)
            except Exception as e:
                log.error(f"ESL connection lost: {e}. Reconnecting in 5s…")
                with self._lock:
                    self._conn = None
                import time; time.sleep(5)

    def _dispatch(self, event: ESL.ESLevent):
        name = event.getHeader("Event-Name")
        if not name:
            return
        handlers = self._listeners.get(name, []) + self._listeners.get("*", [])
        for handler in handlers:
            asyncio.run_coroutine_threadsafe(
                self._safe_call(handler, event), self._loop
            )

    @staticmethod
    async def _safe_call(handler: Callable, event: ESL.ESLevent):
        try:
            await handler(event)
        except Exception as e:
            log.error(f"ESL handler error: {e}")

    # ── Subscriptions ──────────────────────────────────────────────────────────

    def on(self, event_name: str, handler: Callable):
        self._listeners.setdefault(event_name, []).append(handler)

    def off(self, event_name: str, handler: Callable):
        if event_name in self._listeners:
            self._listeners[event_name].discard(handler)

    # ── API calls (run in thread pool, return string result) ───────────────────

    async def api(self, command: str) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._api_sync, command)

    def _api_sync(self, command: str) -> str:
        conn = self._make_conn()
        result = conn.api(command)
        reply = result.getBody() if result else ""
        return reply.strip() if reply else ""

    async def bgapi(self, command: str) -> str:
        return await self.api(f"bgapi {command}")

    # ── High-level helpers ─────────────────────────────────────────────────────

    async def originate(
        self,
        destination: str,
        context: str = "default",
        caller_id_name: str = "Dialer",
        caller_id_number: str = "0000000000",
        variables: Optional[dict] = None,
    ) -> str:
        """Originate a call. Returns FreeSWITCH channel UUID or empty on failure."""
        var_str = ""
        if variables:
            parts = ",".join(f"{k}={v}" for k, v in variables.items())
            var_str = f"{{{parts}}}"

        cmd = (
            f"originate {var_str}"
            f"{{origination_caller_id_name='{caller_id_name}',"
            f"origination_caller_id_number={caller_id_number}}}"
            f"{destination} &park()"
        )
        result = await self.api(cmd)
        if result.startswith("+OK"):
            return result.split()[-1]   # UUID
        log.warning(f"originate failed: {result}")
        return ""

    async def bridge(self, uuid_a: str, uuid_b: str) -> bool:
        result = await self.api(f"uuid_bridge {uuid_a} {uuid_b}")
        return result.startswith("+OK")

    async def hangup(self, uuid: str, cause: str = "NORMAL_CLEARING") -> bool:
        result = await self.api(f"uuid_kill {uuid} {cause}")
        return result.startswith("+OK")

    async def transfer(self, uuid: str, destination: str, context: str = "default") -> bool:
        result = await self.api(f"uuid_transfer {uuid} {destination} XML {context}")
        return result.startswith("+OK")

    async def hold(self, uuid: str) -> bool:
        result = await self.api(f"uuid_hold {uuid}")
        return result.startswith("+OK")

    async def unhold(self, uuid: str) -> bool:
        result = await self.api(f"uuid_hold off {uuid}")
        return result.startswith("+OK")

    async def play_moh(self, uuid: str) -> bool:
        result = await self.api(f"uuid_broadcast {uuid} local_stream://moh aleg")
        return result.startswith("+OK")

    async def channel_vars(self, uuid: str) -> dict[str, str]:
        """Fetch all channel variables for a UUID."""
        raw = await self.api(f"uuid_dump {uuid}")
        vars_: dict[str, str] = {}
        for line in raw.splitlines():
            if ": " in line:
                k, _, v = line.partition(": ")
                vars_[k.strip()] = v.strip()
        return vars_


esl_client = ESLClient()
