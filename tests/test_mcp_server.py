import asyncio

from fastapi.testclient import TestClient

from app.main import app
from app.mcp_server import build_transport_security, mcp


def test_mcp_registers_expected_tools():
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}

    assert names == {
        "search_meetings",
        "ask_meetings",
        "list_my_tasks",
        "get_meeting",
        "list_calendar_events",
        "sync_calendar_tasks",
    }


def test_mcp_http_requires_bearer_token():
    with TestClient(app) as client:
        response = client.post(
            "/mcp/",
            headers={"Accept": "application/json, text/event-stream"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
            },
        )

    assert response.status_code == 401


def test_mcp_transport_security_allows_configured_https_domain():
    security = build_transport_security(
        "https://noting.kro.kr",
        "https://noting.kro.kr/mcp",
    )

    assert security.enable_dns_rebinding_protection is True
    assert "noting.kro.kr" in security.allowed_hosts
    assert "https://noting.kro.kr" in security.allowed_origins
    assert "localhost:*" in security.allowed_hosts


def test_mcp_exposes_oauth_discovery_and_registration():
    client = TestClient(app)
    authorization = client.get("/.well-known/oauth-authorization-server")
    protected_resource = client.get(
        "/.well-known/oauth-protected-resource/mcp"
    )

    assert authorization.status_code == 200
    metadata = authorization.json()
    assert metadata["authorization_endpoint"].endswith("/authorize")
    assert metadata["token_endpoint"].endswith("/token")
    assert metadata["registration_endpoint"].endswith("/register")
    assert metadata["code_challenge_methods_supported"] == ["S256"]

    assert protected_resource.status_code == 200
    resource = protected_resource.json()
    assert resource["resource"].rstrip("/").endswith("/mcp")
    assert "noting:read" in resource["scopes_supported"]
