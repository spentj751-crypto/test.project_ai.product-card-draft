import json

import pytest
from fastapi.testclient import TestClient

import app.web as web

from .conftest import FakeLLM, make_draft


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setattr(web, "OpenAICompatibleClient", lambda settings: FakeLLM(make_draft()))
    return TestClient(web.app)


def test_index_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Черновик карточки товара" in res.text


def test_examples(client):
    ids = [e["id"] for e in client.get("/api/examples").json()]
    assert "input/vit-1" in ids and "input/plk210" in ids


def test_generate_ok(client, manometer):
    res = client.post("/api/generate", content=json.dumps(manometer, ensure_ascii=False).encode())
    assert res.status_code == 200
    body = res.json()
    assert body["card"]["status"] == "ok"
    assert body["markdown"].startswith("# Манометр")


def test_generate_invalid_json(client):
    res = client.post("/api/generate", content=b'{"name": ')
    assert res.status_code == 422
    assert res.json()["error"] == "Некорректный JSON"


def test_validate(client, manometer):
    res = client.post("/api/validate", content=json.dumps(manometer).encode())
    assert res.status_code == 200
    assert res.json()["category"] == "Манометр"


def test_missing_api_key(monkeypatch, manometer):
    monkeypatch.setenv("LLM_API_KEY", "")
    res = TestClient(web.app).post("/api/generate", content=json.dumps(manometer).encode())
    assert res.status_code == 500
    assert "LLM_API_KEY" in res.json()["error"]
