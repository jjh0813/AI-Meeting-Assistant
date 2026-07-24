from sqlalchemy import text

from app.core.database import engine


def main():
    statements = [
        """
        ALTER TABLE transcripts
        ADD COLUMN IF NOT EXISTS analysis_status TEXT NOT NULL DEFAULT 'pending'
        """,
        """
        ALTER TABLE transcripts
        ADD COLUMN IF NOT EXISTS analysis_error TEXT
        """,
        """
        UPDATE transcripts
        SET analysis_status = CASE
            WHEN summary IS NOT NULL THEN 'completed'
            ELSE 'pending'
        END
        WHERE analysis_status IS NULL
           OR analysis_status = 'pending'
        """,
    ]
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
    print("analysis job columns are ready")


if __name__ == "__main__":
    main()
