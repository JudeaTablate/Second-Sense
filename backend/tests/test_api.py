"""
Integration tests using FastAPI's TestClient against an in-memory
SQLite DB (swapped in for Postgres just for tests) and a fakeredis
stand-in, so these run in CI without needing real Postgres/Redis
containers. See conftest.py for the fixture wiring.
"""


def _sample_events(base_ts: int = 0) -> list[dict]:
    events = []
    ts = base_ts
    for i, key in enumerate("hello"):
        events.append({"type": "keydown", "timestamp": ts, "key": key})
        ts += 90
        events.append({"type": "keyup", "timestamp": ts, "key": key})
        ts += 40
    for i in range(5):
        events.append({"type": "mousemove", "timestamp": ts, "x": i * 20, "y": i * 5})
        ts += 30
    return events


def _signup_and_login(client, email="ja@example.com", password="supersecret123"):
    client.post("/auth/signup", json={"email": email, "password": password})
    resp = client.post("/auth/login", json={"email": email, "password": password})
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestHealthCheck:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestAuth:
    def test_signup_creates_user_and_returns_token(self, client):
        resp = client.post("/auth/signup", json={"email": "new@example.com", "password": "password123"})
        assert resp.status_code == 201
        assert "access_token" in resp.json()

    def test_signup_duplicate_email_rejected(self, client):
        client.post("/auth/signup", json={"email": "dup@example.com", "password": "password123"})
        resp = client.post("/auth/signup", json={"email": "dup@example.com", "password": "password123"})
        assert resp.status_code == 400

    def test_login_wrong_password_rejected(self, client):
        client.post("/auth/signup", json={"email": "wp@example.com", "password": "password123"})
        resp = client.post("/auth/login", json={"email": "wp@example.com", "password": "wrongpass"})
        assert resp.status_code == 401


class TestIngestion:
    def test_ingest_requires_auth(self, client):
        resp = client.post("/sessions/ingest", json={"events": _sample_events()})
        assert resp.status_code == 403  # no bearer token supplied

    def test_ingest_returns_score(self, client):
        headers = _signup_and_login(client)
        resp = client.post("/sessions/ingest", json={"events": _sample_events()}, headers=headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "risk_score" in body
        assert 0.0 <= body["risk_score"] <= 100.0
        assert body["baseline_sample_count"] == 1

    def test_repeated_consistent_sessions_build_baseline(self, client):
        headers = _signup_and_login(client, email="consistent@example.com")
        last_score = None
        for i in range(10):
            resp = client.post(
                "/sessions/ingest", json={"events": _sample_events(base_ts=i * 1000)}, headers=headers
            )
            last_score = resp.json()

        assert last_score["baseline_sample_count"] == 10

    def test_incidents_list_requires_auth(self, client):
        resp = client.get("/incidents")
        assert resp.status_code == 403

    def test_incidents_list_empty_initially(self, client):
        headers = _signup_and_login(client, email="noincidents@example.com")
        resp = client.get("/incidents", headers=headers)
        assert resp.status_code == 200
        assert resp.json() == []
