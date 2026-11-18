from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from .config import DATABASE_URL
from .models import ActivityLog, UserSettings

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
if DATABASE_URL.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def sqlite_pragmas(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")


Session = sessionmaker(engine, expire_on_commit=False)

DEFAULTS = dict(
    onboarded=False,
    workers=1,
    threads=2,
    resolution="1080",
    framing="blur",
    production="stopped",
    publishing_enabled=False,
    auto_publish=False,
    allow_public=False,
    auto_count=3,
    auto_duration=30,
    auto_theme="",
    auto_preset="Gaming Viral",
    auto_min_score=20,
    auto_queue=False,
    auto_channel_id="",
    source_folder="",
    output_folder="",
    quota_search=100,
    quota_upload=100,
    quota_general=10000,
    trend_query="",
    trend_region="US",
    trend_hours=24,
    trend_interval_minutes=0,
    trend_last_run=0,
    min_free_gb=1,
    memory_limit_mb=4096,
)


def settings(session):
    row = session.get(UserSettings, 1)
    return {**DEFAULTS, **(row.data if row else {})}


def update_settings(session, values):
    row = session.get(UserSettings, 1)
    if not row:
        row = UserSettings(id=1, data={})
        session.add(row)
    row.data = {**settings(session), **values}
    session.commit()
    return row.data


def log(session, message, level="info"):
    import json
    from datetime import datetime, timezone
    from .config import STORAGE

    entry = dict(time=datetime.now(timezone.utc).isoformat(), level=level, message=message)
    with (STORAGE / "logs" / "activity.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + "\n")
    session.add(ActivityLog(message=message, level=level))
    session.commit()


def public(row):
    hidden = {"tokens", "upload_url", "path", "thumbnail", "verifier"}
    return {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in hidden}
