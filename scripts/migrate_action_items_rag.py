from sqlalchemy import text

from app.core.database import engine


STATEMENTS = (
    """
    DO $$
    BEGIN
        CREATE TYPE actionitemstatus AS ENUM ('pending', 'in_progress', 'completed');
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END
    $$;
    """,
    """
    ALTER TABLE action_items
    ADD COLUMN IF NOT EXISTS status actionitemstatus
    """,
    """
    UPDATE action_items
    SET status = 'pending'
    WHERE status IS NULL
    """,
    """
    ALTER TABLE action_items
    ALTER COLUMN status SET DEFAULT 'pending',
    ALTER COLUMN status SET NOT NULL
    """,
    """
    ALTER TABLE action_items
    ADD COLUMN IF NOT EXISTS task_embedding vector(768)
    """,
)


def main():
    with engine.begin() as connection:
        for statement in STATEMENTS:
            connection.execute(text(statement))
    print("action_items RAG migration complete")


if __name__ == "__main__":
    main()
