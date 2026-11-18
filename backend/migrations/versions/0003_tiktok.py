"""Отдельные аккаунты и очередь TikTok сохраняют историю YouTube без изменений."""

from alembic import op
from backend.models import TikTokAccount, TikTokJob

revision = "0003"
down_revision = "0002"


def upgrade():
    TikTokAccount.__table__.create(op.get_bind(), checkfirst=True)
    TikTokJob.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    TikTokJob.__table__.drop(op.get_bind())
    TikTokAccount.__table__.drop(op.get_bind())
