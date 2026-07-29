from sqlalchemy import text

from app.core.database import engine


STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS mcp_oauth_clients (
        client_id VARCHAR(128) PRIMARY KEY,
        encrypted_client_secret TEXT,
        metadata_json TEXT NOT NULL,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_oauth_requests (
        request_hash VARCHAR(64) PRIMARY KEY,
        client_id VARCHAR(128) NOT NULL
            REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE,
        params_json TEXT NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        used BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_mcp_oauth_requests_client_id
    ON mcp_oauth_requests(client_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_mcp_oauth_requests_expires_at
    ON mcp_oauth_requests(expires_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_oauth_authorization_codes (
        code_hash VARCHAR(64) PRIMARY KEY,
        client_id VARCHAR(128) NOT NULL
            REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        scopes TEXT NOT NULL,
        code_challenge TEXT NOT NULL,
        redirect_uri TEXT NOT NULL,
        redirect_uri_provided_explicitly BOOLEAN NOT NULL,
        resource TEXT,
        expires_at TIMESTAMPTZ NOT NULL,
        used BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_mcp_oauth_codes_client_id
    ON mcp_oauth_authorization_codes(client_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_mcp_oauth_codes_user_id
    ON mcp_oauth_authorization_codes(user_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_oauth_access_tokens (
        token_hash VARCHAR(64) PRIMARY KEY,
        family_id VARCHAR(64) NOT NULL,
        client_id VARCHAR(128) NOT NULL
            REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        scopes TEXT NOT NULL,
        resource TEXT NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        revoked BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_mcp_oauth_access_family
    ON mcp_oauth_access_tokens(family_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_mcp_oauth_access_user_id
    ON mcp_oauth_access_tokens(user_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS mcp_oauth_refresh_tokens (
        token_hash VARCHAR(64) PRIMARY KEY,
        family_id VARCHAR(64) NOT NULL,
        client_id VARCHAR(128) NOT NULL
            REFERENCES mcp_oauth_clients(client_id) ON DELETE CASCADE,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        scopes TEXT NOT NULL,
        expires_at TIMESTAMPTZ NOT NULL,
        revoked BOOLEAN NOT NULL DEFAULT FALSE,
        created_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_mcp_oauth_refresh_family
    ON mcp_oauth_refresh_tokens(family_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_mcp_oauth_refresh_user_id
    ON mcp_oauth_refresh_tokens(user_id)
    """,
)


def main():
    with engine.begin() as connection:
        for statement in STATEMENTS:
            connection.execute(text(statement))
    print("MCP OAuth tables are ready")


if __name__ == "__main__":
    main()
