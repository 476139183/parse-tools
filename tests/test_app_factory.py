"""Smoke tests for create_app / capabilities."""

from parse_tools.core.app_factory import create_app


def test_full_capabilities():
    app = create_app(mode="full", start_services=False)
    client = app.test_client()
    data = client.get("/api/capabilities").get_json()
    assert data["mode"] == "full"
    assert data["product"] == "Parse Tools"
    assert "douyin" in data.get("platforms", [])
    assert "weibo" in data.get("platforms", [])
    assert "alipay" in data.get("platforms", [])


def test_mp_capabilities():
    app = create_app(mode="mp", start_services=False)
    client = app.test_client()
    data = client.get("/api/capabilities").get_json()
    assert data["mode"] == "mp-only"
    assert "抖音" in data["disabled"]


def test_healthz():
    app = create_app(mode="full", start_services=False)
    data = app.test_client().get("/healthz").get_json()
    assert data["status"] == "ok"
