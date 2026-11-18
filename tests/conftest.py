"""Тесты всегда используют отдельную базу и отдельные файлы, не материалы пользователя."""

import os
import tempfile
from pathlib import Path

import pytest

TEST_ROOT = Path(tempfile.mkdtemp(prefix="clip-tribune-tests-"))
os.environ["STORAGE_ROOT"] = str(TEST_ROOT)
os.environ["DATABASE_URL"] = "sqlite:///" + str(TEST_ROOT / "tests.db")
os.environ["REDIS_URL"] = ""

from backend.database import Session, engine  # noqa: E402
from backend.models import Base  # noqa: E402


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield


@pytest.fixture
def session():
    with Session() as value:
        yield value


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from backend.api import app, LOCAL_TOKEN

    with TestClient(app, headers={"X-Clip-Tribune": LOCAL_TOKEN}) as value:
        yield value


@pytest.fixture(scope="session")
def sample_video():
    from backend.video import make_test_video

    path = TEST_ROOT / "test-pattern.mp4"
    make_test_video(path, 48)
    return path


@pytest.fixture
def asset(session, sample_video):
    from backend.sources import import_file

    return import_file(session, sample_video, True)
