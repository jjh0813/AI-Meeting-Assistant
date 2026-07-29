import asyncio
import base64
import hashlib
import json
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.security import hash_password
from app.main import app
from app.models.mcp_oauth import (
    McpOAuthAccessToken,
    McpOAuthAuthorizationCode,
    McpOAuthClient,
    McpOAuthRefreshToken,
    McpOAuthRequest,
)
from app.models.user import Department, Role, Status, User
from app.services import mcp_oauth


def _run(awaitable):
    return asyncio.run(awaitable)


def test_mcp_oauth_issues_account_bound_tokens_and_rotates_refresh(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        User.__table__,
        McpOAuthClient.__table__,
        McpOAuthRequest.__table__,
        McpOAuthAuthorizationCode.__table__,
        McpOAuthAccessToken.__table__,
        McpOAuthRefreshToken.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(mcp_oauth, "SessionLocal", TestingSession)

    db = TestingSession()
    user = User(
        username="mcp-user",
        display_name="MCP 사용자",
        hashed_password=hash_password("test-password"),
        department=Department.management,
        role=Role.member,
        status=Status.approved,
    )
    db.add(user)
    db.commit()
    db.close()

    client = OAuthClientInformationFull(
        client_id="test-client",
        redirect_uris=[AnyUrl("http://127.0.0.1:9876/callback")],
        token_endpoint_auth_method="none",
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        scope="noting:read noting:calendar",
        client_name="Noting MCP Test",
    )
    _run(mcp_oauth.oauth_provider.register_client(client))
    redirect = _run(
        mcp_oauth.oauth_provider.authorize(
            client,
            AuthorizationParams(
                state="state-value",
                scopes=["noting:read", "noting:calendar"],
                code_challenge="challenge",
                redirect_uri=AnyUrl("http://127.0.0.1:9876/callback"),
                redirect_uri_provided_explicitly=True,
                resource=mcp_oauth.settings.mcp_resource_server_url,
            ),
        )
    )
    request_token = parse_qs(urlparse(redirect).query)["request_token"][0]

    db = TestingSession()
    pending = db.get(McpOAuthRequest, mcp_oauth._hash(request_token))
    params = json.loads(pending.params_json)
    code = "authorization-code"
    db.add(
        McpOAuthAuthorizationCode(
            code_hash=mcp_oauth._hash(code),
            client_id=client.client_id,
            user_id=user.id,
            scopes=" ".join(params["scopes"]),
            code_challenge=params["code_challenge"],
            redirect_uri=params["redirect_uri"],
            redirect_uri_provided_explicitly=True,
            resource=params["resource"],
            expires_at=mcp_oauth._now() + mcp_oauth.timedelta(minutes=5),
        )
    )
    db.commit()
    db.close()

    loaded_code = _run(
        mcp_oauth.oauth_provider.load_authorization_code(client, code)
    )
    assert loaded_code is not None
    pair = _run(
        mcp_oauth.oauth_provider.exchange_authorization_code(
            client,
            loaded_code,
        )
    )
    access = _run(
        mcp_oauth.oauth_provider.load_access_token(pair.access_token)
    )
    assert access is not None
    assert access.subject == "mcp-user"
    assert set(access.scopes) == {"noting:read", "noting:calendar"}

    refresh = _run(
        mcp_oauth.oauth_provider.load_refresh_token(
            client,
            pair.refresh_token,
        )
    )
    assert refresh is not None
    rotated = _run(
        mcp_oauth.oauth_provider.exchange_refresh_token(
            client,
            refresh,
            refresh.scopes,
        )
    )
    assert rotated.refresh_token != pair.refresh_token
    assert (
        _run(
            mcp_oauth.oauth_provider.load_refresh_token(
                client,
                pair.refresh_token,
            )
        )
        is None
    )


def test_mcp_oauth_http_authorization_code_pkce_flow(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        User.__table__,
        McpOAuthClient.__table__,
        McpOAuthRequest.__table__,
        McpOAuthAuthorizationCode.__table__,
        McpOAuthAccessToken.__table__,
        McpOAuthRefreshToken.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(mcp_oauth, "SessionLocal", TestingSession)

    db = TestingSession()
    db.add(
        User(
            username="oauth-user",
            display_name="OAuth 사용자",
            hashed_password=hash_password("oauth-password"),
            department=Department.management,
            role=Role.member,
            status=Status.approved,
        )
    )
    db.commit()
    db.close()

    http = TestClient(app)
    registered = http.post(
        "/register",
        json={
            "redirect_uris": ["http://127.0.0.1:9876/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "noting:read noting:calendar",
            "client_name": "Noting Integration Test",
        },
    )
    assert registered.status_code == 201
    client_id = registered.json()["client_id"]

    verifier = "v" * 64
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )
    authorized = http.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "http://127.0.0.1:9876/callback",
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "oauth-state",
            "scope": "noting:read noting:calendar",
            "resource": mcp_oauth.settings.mcp_resource_server_url,
        },
        follow_redirects=False,
    )
    assert authorized.status_code == 302
    consent_url = urlparse(authorized.headers["location"])
    request_token = parse_qs(consent_url.query)["request_token"][0]

    consent = http.post(
        "/oauth/consent",
        data={
            "request_token": request_token,
            "username": "oauth-user",
            "password": "oauth-password",
        },
        follow_redirects=False,
    )
    assert consent.status_code == 302
    callback = urlparse(consent.headers["location"])
    callback_params = parse_qs(callback.query)
    assert callback_params["state"] == ["oauth-state"]

    token = http.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": callback_params["code"][0],
            "redirect_uri": "http://127.0.0.1:9876/callback",
            "client_id": client_id,
            "code_verifier": verifier,
            "resource": mcp_oauth.settings.mcp_resource_server_url,
        },
    )
    assert token.status_code == 200
    payload = token.json()
    assert payload["token_type"] == "Bearer"
    assert payload["refresh_token"]
    access = _run(
        mcp_oauth.oauth_provider.load_access_token(payload["access_token"])
    )
    assert access is not None
    assert access.subject == "oauth-user"
