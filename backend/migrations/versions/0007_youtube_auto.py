"""Независимый выключатель и состояние серии YouTube; старые записи выключены."""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("live_recordings")}
    if "auto_youtube_enabled" not in columns:
        op.add_column(
            "live_recordings",
            sa.Column("auto_youtube_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "youtube_auto_state" not in columns:
        op.add_column(
            "live_recordings", sa.Column("youtube_auto_state", sa.JSON(), nullable=False, server_default="{}")
        )


def downgrade():
    op.drop_column("live_recordings", "youtube_auto_state")
    op.drop_column("live_recordings", "auto_youtube_enabled")
