import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc).timestamp()


def uid():
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Entity:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=uid)
    created_at: Mapped[float] = mapped_column(Float, default=now)


class UserSettings(Base):
    __tablename__ = "user_settings"
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class Source(Entity, Base):
    __tablename__ = "sources"
    name: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(30), default="folder")
    rights: Mapped[bool] = mapped_column(Boolean, default=False)
    watching: Mapped[bool] = mapped_column(Boolean, default=False)


class SourceAsset(Entity, Base):
    __tablename__ = "source_assets"
    name: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(ForeignKey("sources.id"), nullable=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    rights: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class AdAsset(Entity, Base):
    __tablename__ = "ad_assets"
    name: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)


class TrendRecord(Entity, Base):
    __tablename__ = "trend_records"
    video_id: Mapped[str] = mapped_column(String(32), index=True)
    query: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float)
    data: Mapped[dict] = mapped_column(JSON)


class ContentProject(Entity, Base):
    __tablename__ = "content_projects"
    name: Mapped[str] = mapped_column(Text)
    options: Mapped[dict] = mapped_column(JSON, default=dict)


class ClipCandidate(Entity, Base):
    __tablename__ = "clip_candidates"
    asset_id: Mapped[str] = mapped_column(ForeignKey("source_assets.id"))
    start: Mapped[float] = mapped_column(Float)
    duration: Mapped[float] = mapped_column(Float)
    score: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list] = mapped_column(JSON)
    fingerprint: Mapped[str] = mapped_column(Text, default="")


class RenderJob(Entity, Base):
    __tablename__ = "render_jobs"
    __table_args__ = (
        Index(
            "uq_active_asset_job",
            "asset_id",
            unique=True,
            sqlite_where=text("status IN ('pending', 'analyzing', 'rendering')"),
            postgresql_where=text("status IN ('pending', 'analyzing', 'rendering')"),
        ),
    )
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("source_assets.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ForeignKey("content_projects.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    kind: Mapped[str] = mapped_column(String(24), default="clips")
    progress: Mapped[float] = mapped_column(Float, default=0)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    message: Mapped[str] = mapped_column(Text, default="В очереди")
    updated_at: Mapped[float] = mapped_column(Float, default=now)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)


class RenderedClip(Entity, Base):
    __tablename__ = "rendered_clips"
    job_id: Mapped[str] = mapped_column(ForeignKey("render_jobs.id"))
    asset_id: Mapped[str | None] = mapped_column(ForeignKey("source_assets.id"), nullable=True)
    candidate_id: Mapped[str | None] = mapped_column(ForeignKey("clip_candidates.id"), nullable=True)
    title: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    thumbnail: Mapped[str] = mapped_column(Text, default="")
    duration: Mapped[float] = mapped_column(Float)
    size: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(24), default="ready")
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)


class YouTubeChannel(Entity, Base):
    __tablename__ = "youtube_channels"
    youtube_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(Text)
    tokens: Mapped[str] = mapped_column(Text)
    statistics: Mapped[dict] = mapped_column(JSON, default=dict)


class PublishJob(Entity, Base):
    __tablename__ = "publish_jobs"
    __table_args__ = (Index("uq_publish_clip", "clip_id", unique=True),)
    clip_id: Mapped[str] = mapped_column(ForeignKey("rendered_clips.id"))
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("youtube_channels.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    progress: Mapped[float] = mapped_column(Float, default=0)
    scheduled_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    upload_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class ActivityLog(Entity, Base):
    __tablename__ = "activity_logs"
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text)


class QuotaUsage(Base):
    __tablename__ = "quota_usage"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class OAuthState(Base):
    __tablename__ = "oauth_states"
    state: Mapped[str] = mapped_column(String(128), primary_key=True)
    verifier: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[float] = mapped_column(Float)


class TikTokAccount(Entity, Base):
    __tablename__ = "tiktok_accounts"
    open_id: Mapped[str] = mapped_column(String(128), unique=True)
    name: Mapped[str] = mapped_column(Text)
    tokens: Mapped[str] = mapped_column(Text)


class TikTokJob(Entity, Base):
    __tablename__ = "tiktok_jobs"
    __table_args__ = (Index("uq_tiktok_clip_account", "clip_id", "account_id", unique=True),)
    clip_id: Mapped[str] = mapped_column(ForeignKey("rendered_clips.id"))
    account_id: Mapped[str] = mapped_column(ForeignKey("tiktok_accounts.id"))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    mode: Mapped[str] = mapped_column(String(16), default="inbox")
    progress: Mapped[float] = mapped_column(Float, default=0)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    publish_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    upload_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[float] = mapped_column(Float, default=now)


class LiveRecording(Entity, Base):
    """Одна запись эфира. NULL в active_slot освобождает место для следующей."""

    __tablename__ = "live_recordings"
    __table_args__ = (Index("uq_live_active_slot", "active_slot", unique=True),)
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="Прямой эфир")
    platform: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    active_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    clipping_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    auto_tiktok_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_youtube_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    youtube_auto_state: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    finished_at: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[float] = mapped_column(Float, default=now)
    seconds: Mapped[float] = mapped_column(Float, default=0)
    bytes: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(Text, default="Ожидание записи")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class LiveSegment(Entity, Base):
    """Закрытая часть эфира: только такие файлы можно передавать монтажному воркеру."""

    __tablename__ = "live_segments"
    __table_args__ = (Index("uq_live_segment", "recording_id", "name", unique=True),)
    recording_id: Mapped[str] = mapped_column(ForeignKey("live_recordings.id"))
    name: Mapped[str] = mapped_column(Text)
    path: Mapped[str] = mapped_column(Text)
    start: Mapped[float] = mapped_column(Float)
    duration: Mapped[float] = mapped_column(Float)
    size: Mapped[int] = mapped_column(Integer)
    job_id: Mapped[str | None] = mapped_column(ForeignKey("render_jobs.id"), nullable=True)
