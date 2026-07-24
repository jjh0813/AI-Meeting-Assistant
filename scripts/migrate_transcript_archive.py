from sqlalchemy import text

from app.core.database import engine


def main():
    statements = [
        """
        ALTER TABLE transcripts
        ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE
        """,
        """
        ALTER TABLE transcripts
        ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ
        """,
        """
        ALTER TABLE action_items
        ADD COLUMN IF NOT EXISTS archived BOOLEAN NOT NULL DEFAULT FALSE
        """,
        """
        ALTER TABLE action_items
        ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
    print("transcript archive columns are ready")


if __name__ == "__main__":
    main()
