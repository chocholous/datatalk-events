from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


class TestRoot:
    def test_root_returns_200_with_app_name_and_status(self) -> None:
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "app" in data
        assert data["app"] == "DataTalk Events"
        assert data["status"] == "running"


class TestHealth:
    def test_health_returns_200_with_healthy_status(self) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
