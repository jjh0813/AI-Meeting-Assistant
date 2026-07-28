from sqlalchemy import text

from app.core.database import engine


STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS google_calendar_connections (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL UNIQUE
            REFERENCES users(id) ON DELETE CASCADE,
        google_email TEXT,
        calendar_id TEXT NOT NULL DEFAULT 'primary',
        encrypted_access_token TEXT NOT NULL,
        encrypted_refresh_token TEXT,
        token_expires_at TIMESTAMPTZ,
        scopes TEXT NOT NULL DEFAULT '',
        created_at TIMESTAMPTZ DEFAULT now(),
        updated_at TIMESTAMPTZ DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_google_calendar_connections_user_id
    ON google_calendar_connections(user_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS google_calendar_event_links (
        id SERIAL PRIMARY KEY,
        user_id INTEGER NOT NULL
            REFERENCES users(id) ON DELETE CASCADE,
        action_item_id INTEGER NOT NULL
            REFERENCES action_items(id) ON DELETE CASCADE,
        calendar_id TEXT NOT NULL DEFAULT 'primary',
        google_event_id TEXT NOT NULL,
        due_snapshot TEXT NOT NULL DEFAULT '',
        title_snapshot TEXT NOT NULL DEFAULT '',
        synced_at TIMESTAMPTZ DEFAULT now(),
        CONSTRAINT uq_google_calendar_user_action
            UNIQUE(user_id, action_item_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_google_calendar_event_links_user_id
    ON google_calendar_event_links(user_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_google_calendar_event_links_action_item_id
    ON google_calendar_event_links(action_item_id)
    """,
)


def main():
    with engine.begin() as connection:
        for statement in STATEMENTS:
            connection.execute(text(statement))
    print("Google Calendar tables are ready")


if __name__ == "__main__":
    main()
