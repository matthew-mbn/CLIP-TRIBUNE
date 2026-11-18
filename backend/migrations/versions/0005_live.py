"""Запись прямых эфиров и индекс их завершённых частей."""

from alembic import op
from backend.models import LiveRecording, LiveSegment

revision = "0005"
down_revision = "0004"


def upgrade():
    LiveRecording.__table__.create(op.get_bind(), checkfirst=True)
    LiveSegment.__table__.create(op.get_bind(), checkfirst=True)


def downgrade():
    LiveSegment.__table__.drop(op.get_bind())
    LiveRecording.__table__.drop(op.get_bind())
