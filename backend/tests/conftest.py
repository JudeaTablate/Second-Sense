import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.services import redis_client

# In-memory SQLite for tests — fast, no external Postgres needed in CI.
# StaticPool keeps a single shared connection alive for the life of the
# engine; without it, ":memory:" SQLite gives every new connection a
# blank, separate database and tables "disappear" between requests.
TEST_DB_URL = "sqlite:///:memory:"
engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def _use_fake_redis(monkeypatch):
    """Swap the real Redis client for an in-memory fake so tests don't
    need a running Redis instance."""
    import fakeredis

    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(redis_client, "_client", fake)
    yield


@pytest.fixture(autouse=True)
def _fresh_db():
    """Create all tables before each test and drop them after, so
    tests are fully isolated from each other."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
