"""Named schedule drafts. The live board stays in `lessons` until a draft is published."""

from app.database import get_db


_LESSON_COLUMNS = """
    group_id, teacher_id, teacher2_id, subject_id,
    classroom_id, classroom2_id,
    weekday, period, week, lesson_type, note
"""


def _clean_name(name):
    text = str(name or "").strip()
    if not text:
        return None, "Укажите название черновика."
    if len(text) > 80:
        return None, "Название черновика не длиннее 80 символов."
    return text, None


def list_drafts():
    rows = get_db().execute(
        """
        SELECT
            schedule_drafts.id,
            schedule_drafts.name,
            schedule_drafts.created_at,
            schedule_drafts.updated_at,
            (
                SELECT COUNT(*)
                FROM draft_lessons
                WHERE draft_lessons.draft_id = schedule_drafts.id
            ) AS lesson_count
        FROM schedule_drafts
        ORDER BY schedule_drafts.updated_at DESC, schedule_drafts.id DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]


def get_draft(draft_id):
    row = get_db().execute(
        """
        SELECT
            schedule_drafts.id,
            schedule_drafts.name,
            schedule_drafts.created_at,
            schedule_drafts.updated_at,
            (
                SELECT COUNT(*)
                FROM draft_lessons
                WHERE draft_lessons.draft_id = schedule_drafts.id
            ) AS lesson_count
        FROM schedule_drafts
        WHERE schedule_drafts.id = ?
        """,
        (draft_id,),
    ).fetchone()
    return dict(row) if row else None


def create_draft(name, copy_current=True):
    cleaned, error = _clean_name(name)
    if error:
        return None, error

    db = get_db()
    cursor = db.execute(
        "INSERT INTO schedule_drafts (name) VALUES (?)",
        (cleaned,),
    )
    draft_id = cursor.lastrowid
    if copy_current:
        _copy_live_into_draft(db, draft_id)
    db.commit()
    return draft_id, None


def _copy_live_into_draft(db, draft_id):
    rows = db.execute(
        f"""
        SELECT {_LESSON_COLUMNS}
        FROM lessons
        ORDER BY week, weekday, period, id
        """
    ).fetchall()
    if not rows:
        return 0
    db.executemany(
        f"""
        INSERT INTO draft_lessons (
            draft_id, {_LESSON_COLUMNS}
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                draft_id,
                row["group_id"],
                row["teacher_id"],
                row["teacher2_id"],
                row["subject_id"],
                row["classroom_id"],
                row["classroom2_id"],
                row["weekday"],
                row["period"],
                row["week"],
                row["lesson_type"],
                row["note"],
            )
            for row in rows
        ],
    )
    return len(rows)


def rename_draft(draft_id, name):
    cleaned, error = _clean_name(name)
    if error:
        return False, error

    db = get_db()
    cursor = db.execute(
        """
        UPDATE schedule_drafts
        SET name = ?, updated_at = datetime('now')
        WHERE id = ?
        """,
        (cleaned, draft_id),
    )
    db.commit()
    if cursor.rowcount == 0:
        return False, "Черновик не найден."
    return True, None


def delete_draft(draft_id):
    db = get_db()
    cursor = db.execute("DELETE FROM schedule_drafts WHERE id = ?", (draft_id,))
    db.commit()
    return cursor.rowcount > 0


def publish_draft(draft_id):
    """Replace the live schedule with this draft. The draft itself stays editable."""
    db = get_db()
    draft = db.execute(
        "SELECT id, name FROM schedule_drafts WHERE id = ?",
        (draft_id,),
    ).fetchone()
    if draft is None:
        return False, "Черновик не найден.", 0

    rows = db.execute(
        f"""
        SELECT {_LESSON_COLUMNS}
        FROM draft_lessons
        WHERE draft_id = ?
        ORDER BY week, weekday, period, id
        """,
        (draft_id,),
    ).fetchall()

    try:
        db.execute("BEGIN")
        db.execute("DELETE FROM lessons")
        if rows:
            db.executemany(
                f"""
                INSERT INTO lessons ({_LESSON_COLUMNS})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        row["group_id"],
                        row["teacher_id"],
                        row["teacher2_id"],
                        row["subject_id"],
                        row["classroom_id"],
                        row["classroom2_id"],
                        row["weekday"],
                        row["period"],
                        row["week"],
                        row["lesson_type"],
                        row["note"],
                    )
                    for row in rows
                ],
            )
        db.execute(
            "UPDATE schedule_drafts SET updated_at = datetime('now') WHERE id = ?",
            (draft_id,),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return True, None, len(rows)
