from typing import Literal
from pydantic import BaseModel, Field, model_validator


class WebcamRegion(BaseModel):
    """Доли исходного кадра: область сохраняется при смене 1080p на 720p."""

    x: float = Field(ge=0, lt=1, allow_inf_nan=False)
    y: float = Field(ge=0, lt=1, allow_inf_nan=False)
    width: float = Field(ge=0.02, le=1, allow_inf_nan=False)
    height: float = Field(ge=0.02, le=1, allow_inf_nan=False)

    @model_validator(mode="after")
    def inside_frame(self):
        if self.x + self.width > 1.000001 or self.y + self.height > 1.000001:
            raise ValueError("Область вебки должна находиться внутри кадра")
        return self


class FrameLayout(BaseModel):
    layout: Literal["single", "split", "webcam"] = "single"
    webcam_region: WebcamRegion | None = None
    webcam_fit: Literal["crop", "fit"] = "crop"
    main_fit: Literal["crop", "fit"] = "crop"
    secondary_asset_id: str | None = None
    secondary_start: float = Field(default=0, ge=0, le=28800, allow_inf_nan=False)
    secondary_loop: bool = True
    split_fit: Literal["crop", "fit"] = "fit"
    split_audio: Literal["top", "bottom", "mix", "mute"] = "top"
    subtitle_style: Literal["classic", "bold", "box", "red"] = "bold"

    @model_validator(mode="after")
    def webcam_selected(self):
        if self.layout == "webcam" and self.webcam_region is None:
            raise ValueError("Сначала выделите область вебки на предпросмотре")
        return self


class WebcamFrameInput(BaseModel):
    asset_id: str | None = None
    url: str = Field(default="", max_length=4096)
    rights: bool = False
    height: Literal[720, 1080] = 720
    second: float = Field(default=0, ge=0, le=28800, allow_inf_nan=False)

    @model_validator(mode="after")
    def one_source(self):
        if bool(self.asset_id) == bool(self.url.strip()):
            raise ValueError("Выберите один исходник или ссылку на эфир")
        return self


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
    pause_video: bool = True
    sound: bool = True


class RenderOptions(FrameLayout):
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


class TikTokAutoInput(BaseModel):
    """Явное разрешение пользователя на будущие клипы только одной записи."""

    enabled: bool = False
    account_id: str = ""
    privacy_level: str = ""
    caption_template: str = Field(default="{title}", max_length=1500)
    interval_minutes: int = Field(default=30, ge=10, le=1440)
    max_posts: int = Field(default=5, ge=1, le=15)
    allow_comment: bool = False
    allow_duet: bool = False
    allow_stitch: bool = False
    commercial: bool = False
    brand_organic: bool = False
    brand_content: bool = False
    synthetic: bool = False
    consent: bool = False


class YouTubeAutoInput(BaseModel):
    enabled: bool = False
    channel_id: str = ""
    privacy: Literal["private", "unlisted", "public"] = "private"
    interval_minutes: int = Field(default=30, ge=1, le=1440)
    max_posts: int = Field(default=5, ge=1, le=100)
    synthetic: bool = False
    made_for_kids: bool = False
    paid_product_placement: bool = False
    consent: bool = False


class LiveInput(RemoteInput, FrameLayout):
    """Запись всегда запускается явным действием пользователя и имеет пределы."""

    height: Literal[720, 1080] = 720
    layout: Literal["single", "webcam", "split"] = "single"
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

    tiktok_auto: TikTokAutoInput = Field(default_factory=TikTokAutoInput)
    youtube_auto: YouTubeAutoInput = Field(default_factory=YouTubeAutoInput)

    @model_validator(mode="after")
    def auto_post_requires_setup(self):
        if self.youtube_auto.enabled:
            if not self.auto_clip or not self.youtube_auto.channel_id or not self.youtube_auto.consent:
                raise ValueError(
                    "Для YouTube включите нарезки, выберите канал и разрешите автоматическую отправку"
                )
        if self.tiktok_auto.enabled:
            if not self.auto_clip:
                raise ValueError("Для автопубликации включите автоматические нарезки")
            if (
                not self.tiktok_auto.account_id
                or not self.tiktok_auto.privacy_level
                or not self.tiktok_auto.consent
            ):
                raise ValueError(
                    "Для автопубликации выберите аккаунт, видимость и разрешите отправку будущих клипов"
                )
        return self


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

    @model_validator(mode="after")
    def caption_length(self):
        if len(self.title.encode("utf-16-le", errors="surrogatepass")) // 2 > 2200:
            raise ValueError("Описание TikTok превышает 2200 единиц UTF-16; эмодзи могут занимать две")
        return self


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
