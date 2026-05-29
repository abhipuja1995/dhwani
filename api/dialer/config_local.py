"""
Local development config — SQLite, no Redis, no FreeSWITCH required.
Loaded automatically when LOCAL=1 env var is set.
"""
from dialer.config import Settings

class LocalSettings(Settings):
    database_url: str = "sqlite+aiosqlite:///./dialer_local.db"
    redis_url: str = "redis://localhost:6379/0"   # not used in local mode
    fs_host: str = "localhost"

local_settings = LocalSettings()
