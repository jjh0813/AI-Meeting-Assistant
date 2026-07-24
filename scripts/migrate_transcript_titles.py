from sqlalchemy import text

from app.core.database import engine


STATEMENTS = (
    """
    ALTER TABLE transcripts
    ADD COLUMN IF NOT EXISTS title text
    """,
    """
    ALTER TABLE transcripts
    ADD COLUMN IF NOT EXISTS title_is_manual boolean
    """,
    """
    UPDATE transcripts
    SET title_is_manual = false
    WHERE title_is_manual IS NULL
    """,
    """
    ALTER TABLE transcripts
    ALTER COLUMN title_is_manual SET DEFAULT false,
    ALTER COLUMN title_is_manual SET NOT NULL
    """,
)


def main():
    with engine.begin() as connection:
        for statement in STATEMENTS:
            connection.execute(text(statement))
    print("transcript title migration complete")


if __name__ == "__main__":
    main()
