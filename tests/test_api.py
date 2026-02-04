"""
AirEase Backend Tests
API测试
"""

import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client():
    """Create test client"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.anyio
async def test_root(client: AsyncClient):
    """Test root endpoint"""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "AirEase API"
    assert data["status"] == "running"


@pytest.mark.anyio
async def test_health(client: AsyncClient):
    """Test health endpoint"""
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.anyio
async def test_search_flights(client: AsyncClient):
    """Test flight search"""
    response = await client.get(
        "/v1/flights/search",
        params={
            "from": "北京",
            "to": "上海",
            "date": "2025-01-15",
            "cabin": "economy"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert "flights" in data
    assert "meta" in data
    assert isinstance(data["flights"], list)


@pytest.mark.anyio
async def test_search_flights_no_results(client: AsyncClient):
    """Test flight search with no results"""
    response = await client.get(
        "/v1/flights/search",
        params={
            "from": "火星",
            "to": "月球",
            "date": "2025-01-15",
            "cabin": "economy"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["flights"] == []
    assert data["meta"]["total"] == 0


@pytest.mark.anyio
async def test_flight_detail_not_found(client: AsyncClient):
    """Test flight detail 404"""
    response = await client.get("/v1/flights/nonexistent-flight")
    assert response.status_code == 404


@pytest.mark.anyio
async def test_ai_search(client: AsyncClient):
    """Test AI search endpoint"""
    response = await client.post(
        "/v1/ai/search",
        json={"query": "明天北京到上海"}
    )
    assert response.status_code == 200
    data = response.json()
    assert "confidence" in data
    assert "originalQuery" in data


@pytest.mark.anyio
async def test_ai_health(client: AsyncClient):
    """Test AI health endpoint"""
    response = await client.get("/v1/ai/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert data["service"] == "gemini"
