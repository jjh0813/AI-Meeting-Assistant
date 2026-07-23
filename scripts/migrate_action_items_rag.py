from sqlalchemy import text

from app.core.database import engine


STATEMENTS = (
    """
    DO $$
    BEGIN
        CREATE TYPE actionitemstatus AS ENUM (
            'pending', 'in_progress', 'completed', 'superseded'
        );
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END
    $$;
    """,
    """
    ALTER TYPE actionitemstatus
    ADD VALUE IF NOT EXISTS 'superseded'
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
    """
    ALTER TABLE action_items
    ADD COLUMN IF NOT EXISTS superseded_by_id integer
    """,
    """
    DO $$
    BEGIN
        ALTER TABLE action_items
        ADD CONSTRAINT fk_action_items_superseded_by
        FOREIGN KEY (superseded_by_id)
        REFERENCES action_items(id)
        ON DELETE SET NULL;
    EXCEPTION
        WHEN duplicate_object THEN NULL;
    END
    $$;
    """,
)


def main():
    with engine.begin() as connection:
        for statement in STATEMENTS:
            connection.execute(text(statement))
    print("action_items RAG migration complete")


if __name__ == "__main__":
    main()
