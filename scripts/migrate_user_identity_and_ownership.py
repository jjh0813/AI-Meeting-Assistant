import os
import re

from sqlalchemy import text

from app.core.database import engine


LEGACY_OWNER_USERNAME = os.getenv(
    "LEGACY_TRANSCRIPT_OWNER_USERNAME", "acc_user"
).strip()
LEGACY_OWNER_DISPLAY_NAME = os.getenv(
    "LEGACY_OWNER_DISPLAY_NAME", "김철수"
).strip()


def backfill_legacy_pii_tokens(connection) -> int:
    transcripts = connection.execute(
        text("SELECT id, masked_content FROM transcripts ORDER BY id")
    ).all()
    changed_transcripts = 0
    chunk_table_exists = bool(
        connection.execute(
            text("SELECT to_regclass('public.transcript_chunks')")
        ).scalar()
    )
    for transcript in transcripts:
        content = transcript.masked_content
        changed = False
        entries = connection.execute(
            text(
                """
                SELECT id, pii_type, placeholder_token
                FROM pii_entries
                WHERE transcript_id = :transcript_id
                ORDER BY id
                """
            ),
            {"transcript_id": transcript.id},
        ).all()
        counters = {"name": 0, "phone": 0}
        for entry in entries:
            if entry.placeholder_token:
                match = re.fullmatch(
                    r"\[(이름|전화번호)#(\d+)\]", entry.placeholder_token
                )
                if match:
                    kind = "name" if match.group(1) == "이름" else "phone"
                    counters[kind] = max(counters[kind], int(match.group(2)))
                continue
            kind = "name" if entry.pii_type == "name" else "phone"
            generic = "[이름]" if kind == "name" else "[전화번호]"
            if generic not in content:
                continue
            counters[kind] += 1
            token_label = "이름" if kind == "name" else "전화번호"
            token = f"[{token_label}#{counters[kind]}]"
            content = content.replace(generic, token, 1)
            connection.execute(
                text(
                    """
                    UPDATE pii_entries
                    SET placeholder_token = :token
                    WHERE id = :entry_id
                    """
                ),
                {"token": token, "entry_id": entry.id},
            )
            changed = True
        if not changed:
            continue
        connection.execute(
            text(
                """
                UPDATE transcripts
                SET masked_content = :masked_content,
                    analysis_status = 'pending',
                    analysis_error = '사용자별 담당 업무 연결을 위해 재분석이 필요합니다.',
                    summary_embedding = NULL
                WHERE id = :transcript_id
                """
            ),
            {
                "masked_content": content,
                "transcript_id": transcript.id,
            },
        )
        if chunk_table_exists:
            connection.execute(
                text(
                    """
                    DELETE FROM transcript_chunks
                    WHERE transcript_id = :transcript_id
                    """
                ),
                {"transcript_id": transcript.id},
            )
        changed_transcripts += 1
    return changed_transcripts


def main():
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS display_name VARCHAR
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE users
                SET display_name = username
                WHERE display_name IS NULL OR BTRIM(display_name) = ''
                """
            )
        )
        owner = connection.execute(
            text(
                """
                UPDATE users
                SET display_name = :display_name
                WHERE username = :username
                RETURNING id
                """
            ),
            {
                "username": LEGACY_OWNER_USERNAME,
                "display_name": LEGACY_OWNER_DISPLAY_NAME,
            },
        ).first()
        if owner is None:
            raise RuntimeError(
                f"기존 회의 소유 계정 '{LEGACY_OWNER_USERNAME}'을 찾을 수 없습니다."
            )
        connection.execute(
            text("ALTER TABLE users ALTER COLUMN display_name SET NOT NULL")
        )
        connection.execute(
            text(
                """
                ALTER TABLE transcripts
                ADD COLUMN IF NOT EXISTS owner_user_id INTEGER
                """
            )
        )
        connection.execute(
            text(
                """
                UPDATE transcripts
                SET owner_user_id = :owner_user_id
                WHERE owner_user_id IS NULL
                """
            ),
            {"owner_user_id": owner.id},
        )
        connection.execute(
            text(
                """
                ALTER TABLE transcripts
                ALTER COLUMN owner_user_id SET NOT NULL
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_transcripts_owner_user_id
                ON transcripts (owner_user_id)
                """
            )
        )
        connection.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint
                        WHERE conrelid = 'transcripts'::regclass
                          AND contype = 'f'
                          AND pg_get_constraintdef(oid)
                              LIKE 'FOREIGN KEY (owner_user_id)%'
                    ) THEN
                        ALTER TABLE transcripts
                        ADD CONSTRAINT fk_transcripts_owner_user_id_users
                        FOREIGN KEY (owner_user_id)
                        REFERENCES users(id)
                        ON DELETE CASCADE;
                    END IF;
                END
                $$;
                """
            )
        )
        connection.execute(
            text(
                """
                ALTER TABLE pii_entries
                ADD COLUMN IF NOT EXISTS placeholder_token TEXT
                """
            )
        )
        changed_transcripts = backfill_legacy_pii_tokens(connection)
    print(
        "user display names and transcript ownership are ready; "
        f"legacy owner={LEGACY_OWNER_USERNAME}; "
        f"legacy transcripts requiring reanalysis={changed_transcripts}"
    )


if __name__ == "__main__":
    main()
