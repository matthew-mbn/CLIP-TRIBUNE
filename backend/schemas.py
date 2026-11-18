from typing import Literal
from pydantic import BaseModel, Field


class AdOptions(BaseModel):
    """Время отсчитывается от начала готового ролика, а не исходного видео."""

    enabled: bool = False
    asset_id: str = ""
    mode: Literal["once", "banner"] = "once"
    start: float = Field(default=3, ge=0, le=28800, allow_inf_nan=False)
    duration: float = Field(default=0, ge=0, le=600, allow_inf_nan=False)
    position: Literal[
        "top_left", "top", "top_right", "left", "center", "right", "bottom_left", "bottom", "bottom_right"
    ] = "bottom"
    width_percent: int = Field(default=70, ge=10, le=100)
    margin_percent: int = Field(default=3, ge=0, le=15)
    key_color: str = Field(default="#00FF00", pattern=r"^#[0-9a-fA-F]{6}$")
    similarity: float = Field(default=0.22, ge=0.01, le=0.8, allow_inf_nan=False)
    blend: float = Field(default=0.08, ge=0, le=0.5, allow_inf_nan=False)


class RenderOptions(BaseModel):
    asset_ids: list[str] = Field(default_factory=list, max_length=100)
    theme: str = Field(default="", max_length=150)
    count: int = Field(default=3, ge=1, le=30)
    duration: int = Field(default=30, ge=15, le=60)
    preset: Literal[
        "Gaming Viral", "Funny Moments", "Cinematic", "Action", "Storytelling", "Educational", "Custom"
    ] = "Gaming Viral"
    resolution: Literal["720", "1080"] = "1080"
    framing: Literal["crop", "blur", "original"] = "blur"
    subtitles: bool = False
    title_overlay: bool = False
    min_score: int = Field(default=0, ge=0, le=100)
    project_id: str | None = None
    use_ads: bool = True
    layout: Literal["single", "split"] = "single"
    secondary_asset_id: str | None = None
    secondary_start: float = Field(default=0, ge=0, le=28800, allow_inf_nan=False)
    secondary_loop: bool = True
    split_fit: Literal["crop", "fit"] = "crop"
    split_audio: Literal["top", "bottom", "mix", "mute"] = "top"


class FolderInput(BaseModel):
    path: str = Field(min_length=1, max_length=1024)
    rights: bool = False
    watching: bool = False


class RemoteInput(BaseModel):
    url: str = Field(max_length=4096)
    rights: bool = False


class DownloadInput(RemoteInput):
    height: Literal[720, 1080] = 1080


class LiveInput(RemoteInput):
    """Запись всегда запускается явным действием пользователя и имеет пределы."""

    height: Literal[720, 1080] = 720
    max_hours: float = Field(default=4, ge=0.05, le=24, allow_inf_nan=False)
    max_gb: int = Field(default=20, ge=1, le=500)
    segment_seconds: Literal[60, 120, 180, 300] = 120
    auto_clip: bool = True
    duration: int = Field(default=30, ge=15, le=60)
    count: int = Field(default=1, ge=1, le=3)
    min_score: int = Field(default=25, ge=0, le=100)
    resolution: Literal["720", "1080"] = "720"
    framing: Literal["crop", "blur", "original"] = "blur"
    subtitles: bool = False
    use_ads: bool = False
    theme: str = Field(default="", max_length=150)


class PublishInput(BaseModel):
    clip_ids: list[str] = Field(min_length=1, max_length=100)
    channel_id: str | None = None
    scheduled_at: float | None = None
    privacy: Literal["private", "unlisted", "public"] = "private"
    synthetic: bool = False
    made_for_kids: bool = False


class TrendInput(BaseModel):
    query: str = Field(min_length=1, max_length=150)
    region: str = Field(default="US", pattern="^[A-Z]{2}$")
    hours: Literal[1, 6, 24, 168] = 24


class TikTokPublishInput(BaseModel):
    clip_id: str
    account_id: str
    mode: Literal["inbox", "direct"] = "inbox"
    title: str = Field(default="", max_length=2200)
    privacy_level: str = ""
    allow_comment: bool = False
    allow_duet: bool = False
    allow_stitch: bool = False
    commercial: bool = False
    brand_organic: bool = False
    brand_content: bool = False
    synthetic: bool = False
    consent: bool = False


class SettingsInput(BaseModel):
    onboarded: bool = False
    workers: int = Field(default=1, ge=1, le=8)
    threads: int = Field(default=2, ge=1, le=16)
    resolution: Literal["720", "1080"] = "1080"
    framing: Literal["crop", "blur", "original"] = "blur"
    allow_public: bool = False
    auto_publish: bool = False
    auto_queue: bool = False
    auto_channel_id: str = ""
    auto_count: int = Field(default=3, ge=1, le=30)
    auto_duration: int = Field(default=30, ge=15, le=60)
    auto_theme: str = Field(default="", max_length=150)
    auto_preset: str = "Gaming Viral"
    auto_min_score: int = Field(default=20, ge=0, le=100)
    source_folder: str = ""
    output_folder: str = ""
    quota_search: int = Field(default=100, ge=1)
    quota_upload: int = Field(default=100, ge=1)
    quota_general: int = Field(default=10000, ge=1)
    trend_query: str = ""
    trend_region: str = Field(default="US", pattern="^[A-Z]{2}$")
    trend_hours: Literal[1, 6, 24, 168] = 24
    trend_interval_minutes: int = Field(default=0, ge=0)
    min_free_gb: int = Field(default=1, ge=1, le=1000)
    memory_limit_mb: int = Field(default=4096, ge=512, le=65536)
