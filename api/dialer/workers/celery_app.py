from celery import Celery
from dialer.config import settings

app = Celery(
    "dialer",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["dialer.workers.tasks"],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Kolkata",
    enable_utc=True,
    task_routes={
        "dialer.workers.tasks.pacing_tick": {"queue": "pacing"},
        "dialer.workers.tasks.launch_campaign": {"queue": "campaigns"},
        "dialer.workers.tasks.dial_contact": {"queue": "default"},
    },
    beat_schedule={
        "pacing-tick": {
            "task": "dialer.workers.tasks.pacing_tick",
            "schedule": 30.0,  # every 30 seconds
        },
    },
)
