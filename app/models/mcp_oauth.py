from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.sql import func

from app.core.database import Base


class McpOAuthClient(Base):
    __tablename__ = "mcp_oauth_clients"

    client_id = Column(String(128), primary_key=True)
    encrypted_client_secret = Column(Text, nullable=True)
    metadata_json = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class McpOAuthRequest(Base):
    __tablename__ = "mcp_oauth_requests"

    request_hash = Column(String(64), primary_key=True)
    client_id = Column(
        String(128),
        ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    params_json = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class McpOAuthAuthorizationCode(Base):
    __tablename__ = "mcp_oauth_authorization_codes"

    code_hash = Column(String(64), primary_key=True)
    client_id = Column(
        String(128),
        ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scopes = Column(Text, nullable=False)
    code_challenge = Column(Text, nullable=False)
    redirect_uri = Column(Text, nullable=False)
    redirect_uri_provided_explicitly = Column(Boolean, nullable=False)
    resource = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class McpOAuthAccessToken(Base):
    __tablename__ = "mcp_oauth_access_tokens"

    token_hash = Column(String(64), primary_key=True)
    family_id = Column(String(64), nullable=False, index=True)
    client_id = Column(
        String(128),
        ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scopes = Column(Text, nullable=False)
    resource = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class McpOAuthRefreshToken(Base):
    __tablename__ = "mcp_oauth_refresh_tokens"

    token_hash = Column(String(64), primary_key=True)
    family_id = Column(String(64), nullable=False, index=True)
    client_id = Column(
        String(128),
        ForeignKey("mcp_oauth_clients.client_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    scopes = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    revoked = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
