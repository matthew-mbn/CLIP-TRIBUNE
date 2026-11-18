"""Публичное имя автора эфира отдельно от настроек автопубликации."""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("live_recordings")}
    if "creator_name" not in columns:
        op.add_column(
            "live_recordings", sa.Column("creator_name", sa.Text(), nullable=False, server_default="")
        )


def downgrade():
    op.drop_column("live_recordings", "creator_name")
