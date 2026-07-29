import base64
import hashlib
import html
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import jwt
from cryptography.fernet import Fernet, InvalidToken
from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    RegistrationError,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import verify_password
from app.models.mcp_oauth import (
    McpOAuthAccessToken,
    McpOAuthAuthorizationCode,
    McpOAuthClient,
    McpOAuthRefreshToken,
    McpOAuthRequest,
)
from app.models.user import Status, User

READ_SCOPE = "noting:read"
CALENDAR_SCOPE = "noting:calendar"
VALID_SCOPES = (READ_SCOPE, CALENDAR_SCOPE)
ACCESS_TOKEN_MINUTES = 60
REFRESH_TOKEN_DAYS = 30


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fernet() -> Fernet:
    source = settings.token_encryption_key or settings.secret_key
    key = base64.urlsafe_b64encode(hashlib.sha256(source.encode("utf-8")).digest())
    return Fernet(key)


def _encrypt(value: str | None) -> str | None:
    if not value:
        return None
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def _decrypt(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None


def _scopes(value: str | None) -> list[str]:
    return [scope for scope in (value or "").split() if scope in VALID_SCOPES]


def _canonical_resource(value: str | None) -> str:
    configured = settings.mcp_resource_server_url.rstrip("/")
    if value and value.rstrip("/") != configured:
        raise TokenError(
            error="invalid_request",
            error_description="The requested resource is not this MCP server.",
        )
    return configured


def _valid_redirect_uri(value: AnyUrl) -> bool:
    scheme = value.scheme.lower()
    host = (value.host or "").lower()
    return scheme == "https" or (
        scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}
    )


class NotingOAuthProvider:
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        db = SessionLocal()
        try:
            row = db.get(McpOAuthClient, client_id)
            if row is None:
                return None
            data = json.loads(row.metadata_json)
            data["client_secret"] = _decrypt(row.encrypted_client_secret)
            return OAuthClientInformationFull.model_validate(data)
        finally:
            db.close()

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if not client_info.client_id or not client_info.redirect_uris:
            raise RegistrationError(
                error="invalid_client_metadata",
                error_description="client_id and redirect_uris are required.",
            )
        if any(not _valid_redirect_uri(uri) for uri in client_info.redirect_uris):
            raise RegistrationError(
                error="invalid_redirect_uri",
                error_description=(
                    "Redirect URIs must use HTTPS, except localhost loopback URIs."
                ),
            )
        metadata = client_info.model_dump(mode="json")
        secret = metadata.pop("client_secret", None)
        db = SessionLocal()
        try:
            if db.get(McpOAuthClient, client_info.client_id) is not None:
                raise RegistrationError(
                    error="invalid_client_metadata",
                    error_description="The client_id is already registered.",
                )
            db.add(
                McpOAuthClient(
                    client_id=client_info.client_id,
                    encrypted_client_secret=_encrypt(secret),
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                )
            )
            db.commit()
        finally:
            db.close()

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        if not client.client_id:
            raise AuthorizeError(
                error="invalid_request",
                error_description="The OAuth client has no client_id.",
            )
        try:
            resource = _canonical_resource(params.resource)
        except TokenError as exc:
            raise AuthorizeError(
                error="invalid_request",
                error_description=exc.error_description,
            ) from exc
        requested_scopes = params.scopes or _scopes(client.scope) or [READ_SCOPE]
        if any(scope not in VALID_SCOPES for scope in requested_scopes):
            raise AuthorizeError(
                error="invalid_scope",
                error_description="Unsupported Noting MCP scope.",
            )
        if READ_SCOPE not in requested_scopes:
            raise AuthorizeError(
                error="invalid_scope",
                error_description="The noting:read scope is required.",
            )
        request_token = secrets.token_urlsafe(32)
        payload = {
            "state": params.state,
            "scopes": requested_scopes,
            "code_challenge": params.code_challenge,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": (
                params.redirect_uri_provided_explicitly
            ),
            "resource": resource,
        }
        db = SessionLocal()
        try:
            db.add(
                McpOAuthRequest(
                    request_hash=_hash(request_token),
                    client_id=client.client_id,
                    params_json=json.dumps(payload),
                    expires_at=_now() + timedelta(minutes=10),
                )
            )
            db.commit()
        finally:
            db.close()
        issuer = settings.mcp_issuer_url.rstrip("/")
        return f"{issuer}/oauth/consent?{urlencode({'request_token': request_token})}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> AuthorizationCode | None:
        if not client.client_id:
            return None
        db = SessionLocal()
        try:
            row = db.get(McpOAuthAuthorizationCode, _hash(authorization_code))
            if (
                row is None
                or row.client_id != client.client_id
                or row.used
                or _aware(row.expires_at) <= _now()
            ):
                return None
            user = db.get(User, row.user_id)
            if user is None or user.status != Status.approved:
                return None
            return AuthorizationCode(
                code=authorization_code,
                scopes=_scopes(row.scopes),
                expires_at=_aware(row.expires_at).timestamp(),
                client_id=row.client_id,
                code_challenge=row.code_challenge,
                redirect_uri=AnyUrl(row.redirect_uri),
                redirect_uri_provided_explicitly=(
                    row.redirect_uri_provided_explicitly
                ),
                resource=row.resource,
                subject=user.username,
            )
        finally:
            db.close()

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        db = SessionLocal()
        try:
            row = db.get(
                McpOAuthAuthorizationCode,
                _hash(authorization_code.code),
            )
            if row is None or row.used or not client.client_id:
                raise TokenError(
                    error="invalid_grant",
                    error_description="Authorization code is invalid or already used.",
                )
            row.used = True
            user = db.get(User, row.user_id)
            if user is None or user.status != Status.approved:
                raise TokenError(
                    error="invalid_grant",
                    error_description="The Noting user is not approved.",
                )
            result = self._issue_token_pair(
                db,
                client_id=client.client_id,
                user=user,
                scopes=_scopes(row.scopes),
                resource=_canonical_resource(row.resource),
            )
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> RefreshToken | None:
        if not client.client_id:
            return None
        db = SessionLocal()
        try:
            row = db.get(McpOAuthRefreshToken, _hash(refresh_token))
            if (
                row is None
                or row.client_id != client.client_id
                or row.revoked
                or _aware(row.expires_at) <= _now()
            ):
                return None
            user = db.get(User, row.user_id)
            if user is None or user.status != Status.approved:
                return None
            return RefreshToken(
                token=refresh_token,
                client_id=row.client_id,
                scopes=_scopes(row.scopes),
                expires_at=int(_aware(row.expires_at).timestamp()),
                subject=user.username,
            )
        finally:
            db.close()

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        db = SessionLocal()
        try:
            row = db.get(McpOAuthRefreshToken, _hash(refresh_token.token))
            if row is None or row.revoked or not client.client_id:
                raise TokenError(
                    error="invalid_grant",
                    error_description="Refresh token is invalid or already used.",
                )
            row.revoked = True
            user = db.get(User, row.user_id)
            if user is None or user.status != Status.approved:
                raise TokenError(
                    error="invalid_grant",
                    error_description="The Noting user is not approved.",
                )
            result = self._issue_token_pair(
                db,
                client_id=client.client_id,
                user=user,
                scopes=scopes,
                resource=settings.mcp_resource_server_url.rstrip("/"),
                family_id=row.family_id,
            )
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    async def load_access_token(self, token: str) -> AccessToken | None:
        try:
            payload = jwt.decode(
                token,
                settings.secret_key,
                algorithms=["HS256"],
                audience=settings.mcp_resource_server_url.rstrip("/"),
                issuer=settings.mcp_issuer_url.rstrip("/"),
            )
        except jwt.PyJWTError:
            return None
        db = SessionLocal()
        try:
            row = db.get(McpOAuthAccessToken, _hash(token))
            if (
                row is None
                or row.revoked
                or _aware(row.expires_at) <= _now()
                or row.client_id != payload.get("client_id")
            ):
                return None
            user = db.get(User, row.user_id)
            if (
                user is None
                or user.status != Status.approved
                or user.username != payload.get("sub")
            ):
                return None
            return AccessToken(
                token=token,
                client_id=row.client_id,
                scopes=_scopes(row.scopes),
                expires_at=int(_aware(row.expires_at).timestamp()),
                resource=row.resource,
                subject=user.username,
                claims={"iss": payload.get("iss"), "jti": payload.get("jti")},
            )
        finally:
            db.close()

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        token_hash = _hash(token.token)
        db = SessionLocal()
        try:
            access = db.get(McpOAuthAccessToken, token_hash)
            refresh = db.get(McpOAuthRefreshToken, token_hash)
            family_id = access.family_id if access else refresh.family_id if refresh else None
            if family_id:
                db.query(McpOAuthAccessToken).filter(
                    McpOAuthAccessToken.family_id == family_id
                ).update({"revoked": True})
                db.query(McpOAuthRefreshToken).filter(
                    McpOAuthRefreshToken.family_id == family_id
                ).update({"revoked": True})
                db.commit()
        finally:
            db.close()

    def _issue_token_pair(
        self,
        db,
        *,
        client_id: str,
        user: User,
        scopes: list[str],
        resource: str,
        family_id: str | None = None,
    ) -> OAuthToken:
        now = _now()
        family = family_id or secrets.token_hex(24)
        access_expires = now + timedelta(minutes=ACCESS_TOKEN_MINUTES)
        refresh_expires = now + timedelta(days=REFRESH_TOKEN_DAYS)
        access_token = jwt.encode(
            {
                "sub": user.username,
                "client_id": client_id,
                "scope": " ".join(scopes),
                "aud": resource,
                "iss": settings.mcp_issuer_url.rstrip("/"),
                "iat": now,
                "exp": access_expires,
                "jti": secrets.token_hex(20),
            },
            settings.secret_key,
            algorithm="HS256",
        )
        refresh_token = secrets.token_urlsafe(48)
        db.add(
            McpOAuthAccessToken(
                token_hash=_hash(access_token),
                family_id=family,
                client_id=client_id,
                user_id=user.id,
                scopes=" ".join(scopes),
                resource=resource,
                expires_at=access_expires,
            )
        )
        db.add(
            McpOAuthRefreshToken(
                token_hash=_hash(refresh_token),
                family_id=family,
                client_id=client_id,
                user_id=user.id,
                scopes=" ".join(scopes),
                expires_at=refresh_expires,
            )
        )
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_MINUTES * 60,
            scope=" ".join(scopes),
            refresh_token=refresh_token,
        )


oauth_provider = NotingOAuthProvider()


def _consent_page(
    *,
    request_token: str,
    client_name: str,
    error: str = "",
) -> HTMLResponse:
    error_html = (
        f'<p class="error">{html.escape(error)}</p>' if error else ""
    )
    body = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Noting MCP 연결</title>
  <style>
    body {{ margin:0; min-height:100vh; display:grid; place-items:center;
      font-family:system-ui,sans-serif; background:#f6f3ed; color:#18251f; }}
    main {{ width:min(440px,calc(100% - 40px)); padding:36px; background:white;
      border:1px solid #d9ddd8; border-radius:22px; box-shadow:0 18px 50px #17362b18; }}
    .label {{ color:#2f7e76; font-weight:800; letter-spacing:.14em; font-size:12px; }}
    h1 {{ margin:10px 0 8px; font-size:30px; }}
    p {{ color:#66706b; line-height:1.6; }}
    label {{ display:block; margin:18px 0 7px; font-weight:700; }}
    input {{ width:100%; box-sizing:border-box; padding:14px; border:1px solid #ccd3cf;
      border-radius:12px; font-size:16px; }}
    button {{ width:100%; margin-top:24px; padding:15px; border:0; border-radius:12px;
      background:#2f7e76; color:white; font-size:16px; font-weight:800; cursor:pointer; }}
    .error {{ color:#c2413b; }}
  </style>
</head>
<body><main>
  <div class="label">NOTING MCP AUTHORIZATION</div>
  <h1>MCP 연결을 승인하세요.</h1>
  <p><b>{html.escape(client_name)}</b>에서 내 Noting 회의와 개인 업무에 접근하려고 합니다.
  승인된 내 계정 데이터만 제공됩니다.</p>
  {error_html}
  <form method="post" action="/oauth/consent">
    <input type="hidden" name="request_token" value="{html.escape(request_token)}">
    <label for="username">Noting 아이디</label>
    <input id="username" name="username" autocomplete="username" required>
    <label for="password">비밀번호</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required>
    <button type="submit">연결 승인</button>
  </form>
</main></body></html>"""
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


async def oauth_consent(request: Request) -> Response:
    if request.method == "GET":
        request_token = request.query_params.get("request_token", "")
        client_name, error = _load_request_client_name(request_token)
        if error:
            return HTMLResponse(error, status_code=400)
        return _consent_page(
            request_token=request_token,
            client_name=client_name,
        )

    form = await request.form()
    request_token = str(form.get("request_token", ""))
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    client_name, error = _load_request_client_name(request_token)
    if error:
        return HTMLResponse(error, status_code=400)
    db = SessionLocal()
    try:
        oauth_request = db.get(McpOAuthRequest, _hash(request_token))
        user = db.query(User).filter(User.username == username).first()
        if (
            oauth_request is None
            or oauth_request.used
            or _aware(oauth_request.expires_at) <= _now()
        ):
            return HTMLResponse("MCP 연결 요청이 만료되었습니다.", status_code=400)
        if (
            user is None
            or user.status != Status.approved
            or not verify_password(password, user.hashed_password)
        ):
            return _consent_page(
                request_token=request_token,
                client_name=client_name,
                error="아이디, 비밀번호 또는 계정 승인 상태를 확인해 주세요.",
            )
        params = json.loads(oauth_request.params_json)
        code = secrets.token_urlsafe(32)
        db.add(
            McpOAuthAuthorizationCode(
                code_hash=_hash(code),
                client_id=oauth_request.client_id,
                user_id=user.id,
                scopes=" ".join(params["scopes"]),
                code_challenge=params["code_challenge"],
                redirect_uri=params["redirect_uri"],
                redirect_uri_provided_explicitly=(
                    params["redirect_uri_provided_explicitly"]
                ),
                resource=params["resource"],
                expires_at=_now() + timedelta(minutes=5),
            )
        )
        oauth_request.used = True
        db.commit()
        return RedirectResponse(
            construct_redirect_uri(
                params["redirect_uri"],
                code=code,
                state=params.get("state"),
            ),
            status_code=302,
            headers={"Cache-Control": "no-store"},
        )
    finally:
        db.close()


def _load_request_client_name(request_token: str) -> tuple[str, str | None]:
    if not request_token:
        return "", "MCP 연결 요청 값이 없습니다."
    db = SessionLocal()
    try:
        oauth_request = db.get(McpOAuthRequest, _hash(request_token))
        if (
            oauth_request is None
            or oauth_request.used
            or _aware(oauth_request.expires_at) <= _now()
        ):
            return "", "MCP 연결 요청이 만료되었거나 이미 사용되었습니다."
        client = db.get(McpOAuthClient, oauth_request.client_id)
        if client is None:
            return "", "등록된 MCP 클라이언트를 찾을 수 없습니다."
        metadata = json.loads(client.metadata_json)
        return metadata.get("client_name") or "MCP 클라이언트", None
    finally:
        db.close()
