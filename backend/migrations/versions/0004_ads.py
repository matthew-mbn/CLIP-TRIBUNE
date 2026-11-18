"""Рекламные материалы хранятся отдельно от исходников нарезки."""

from alembic import op
from backend.models import AdAsset

revision = "0004"
down_revision = "0003"


def upgrade():
    AdAsset.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    AdAsset.__table__.drop(op.get_bind())
