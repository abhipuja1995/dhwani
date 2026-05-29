from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # FreeSWITCH ESL
    fs_host: str = "freeswitch"
    fs_esl_port: int = 8021
    fs_esl_password: str = "ClueCon"
    fs_domain: str = "localhost"

    # Database
    database_url: str = "postgresql+asyncpg://dialer:dialer@postgres:5432/dialer"

    # Redis / Celery
    redis_url: str = "redis://redis:6379/0"

    # TURN
    turn_host: str = "localhost"
    turn_port: int = 3478
    turn_secret: str = "changeme_turn_secret"

    # API security
    api_secret_key: str = "changeme_api_secret"
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    # SIP trunk (optional)
    sip_trunk_host: str = ""
    sip_trunk_caller_id: str = "0000000000"

    # TRAI DND (optional)
    trai_api_key: str = ""
    trai_api_url: str = "https://api.ncrcp.gov.in/v1"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
