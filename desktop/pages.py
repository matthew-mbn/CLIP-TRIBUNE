"""Карта навигации. Новую страницу достаточно добавить в этот словарь."""

from .integration_pages import PublisherPage, TrendsPage
from .production_pages import AnimationPage, LibraryPage, QueuePage
from .dashboard_page import DashboardPage
from .settings_page import SettingsPage
from .source_pages import SourcesPage, StudioPage
from .tiktok_page import TikTokPage
from .ads_page import AdsPage
from .live_page import LivePage

PAGES = {
    "Обзор": DashboardPage,
    "Источники": SourcesPage,
    "Эфиры": LivePage,
    "Тренды": TrendsPage,
    "Студия": StudioPage,
    "Реклама": AdsPage,
    "Очередь": QueuePage,
    "Библиотека": LibraryPage,
    "Публикация": PublisherPage,
    "TikTok": TikTokPage,
    "Анимация": AnimationPage,
    "Настройки": SettingsPage,
}
