"""Tests for health check endpoints."""


def test_health_endpoint(client):
    """Test GET /health returns ok status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_health_endpoint_under_api_prefix(client):
    """Test GET /api/v1/health returns ok status."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_ready_endpoint(client):
    """Test GET /ready returns database status."""
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"


def test_ready_endpoint_under_api_prefix(client):
    """Test GET /api/v1/ready returns database status."""
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "ok"


def test_ready_reports_unavailable_storage(client, monkeypatch):
    """Readiness must fail when documents cannot be written.

    Without this the container is marked healthy, keeps receiving traffic, and
    the first evidence of a broken upload path is a student's failed upload.
    """
    from app.routers import health

    class BrokenStorage:
        def healthcheck(self) -> bool:
            return False

    monkeypatch.setattr(health, "get_storage", lambda: BrokenStorage())

    response = client.get("/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["storage"] == "unavailable"
    assert body["database"] == "ok"


def test_root_endpoint(client):
    """Test GET / returns application info."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert "name" in data
    assert "version" in data
    assert "docs" in data


def test_docs_endpoint(client):
    """Test GET /docs returns OpenAPI documentation."""
    response = client.get("/docs")
    assert response.status_code == 200
