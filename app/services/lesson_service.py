from app.database import get_db


DAYS = {
    1: "Понедельник",
    2: "Вторник",
    3: "Среда",
    4: "Четверг",
    5: "Пятница",
    6: "Суббота",
}


def _lesson_table(draft_id):
    if draft_id is None:
        return "lessons"
    return "draft_lessons"


def _lesson_source(draft_id):
    """FROM-clause. Draft rows are aliased as lessons so the select list stays shared."""
    if draft_id is None:
        return "lessons"
    return "draft_lessons AS lessons"


def _touch_draft(db, draft_id):
    if draft_id is None:
        return
    db.execute(
        "UPDATE schedule_drafts SET updated_at = datetime('now') WHERE id = ?",
        (int(draft_id),),
    )


def list_lessons(week=None, group_id=None, draft_id=None, teacher_id=None):
    query = f"""
        SELECT
            lessons.*,
            groups_ref.name AS group_name,
            groups_ref.speciality AS group_speciality,
            groups_ref.course AS group_course,
            teachers.full_name AS teacher_name,
            teachers.short_name AS teacher_short,
            teachers.color AS teacher_color,
            teachers2.full_name AS teacher2_name,
            teachers2.short_name AS teacher2_short,
            teachers2.color AS teacher2_color,
            subjects.name AS subject_name,
            subjects.short_name AS subject_short,
            subjects.color AS subject_color,
            classrooms.name AS classroom_name,
            classrooms2.name AS classroom2_name
        FROM {_lesson_source(draft_id)}
        JOIN groups_ref ON groups_ref.id = lessons.group_id
        JOIN teachers ON teachers.id = lessons.teacher_id
        LEFT JOIN teachers AS teachers2 ON teachers2.id = lessons.teacher2_id
        LEFT JOIN subjects ON subjects.id = lessons.subject_id
        LEFT JOIN classrooms ON classrooms.id = lessons.classroom_id
        LEFT JOIN classrooms AS classrooms2 ON classrooms2.id = lessons.classroom2_id
        WHERE 1 = 1
    """
    params = []

    if draft_id is not None:
        query += " AND lessons.draft_id = ?"
        params.append(int(draft_id))

    if week in (1, 2):
        query += " AND lessons.week = ?"
        params.append(week)

    if group_id:
        query += " AND lessons.group_id = ?"
        params.append(group_id)

    if teacher_id:
        query += " AND (lessons.teacher_id = ? OR lessons.teacher2_id = ?)"
        params.extend((int(teacher_id), int(teacher_id)))

    query += " ORDER BY lessons.week, lessons.weekday, lessons.period, lessons.id"
    return [dict(row) for row in get_db().execute(query, params)]


def validate_lesson(data):
    required = {
        "week": "неделю",
        "weekday": "день недели",
        "period": "номер пары",
        "group_id": "группу",
        "teacher_id": "преподавателя",
    }

    for field, title in required.items():
        value = data.get(field)
        if value is None or value == "" or (isinstance(value, str) and not value.strip()):
            return f"Не заполнено поле: {title}."

    try:
        week = int(data["week"])
        weekday = int(data["weekday"])
        period = int(data["period"])
        int(data["group_id"])
        teacher_id = int(data["teacher_id"])
        if data.get("subject_id") not in (None, ""):
            int(data["subject_id"])
        teacher2_id = None
        if data.get("teacher2_id") not in (None, ""):
            teacher2_id = int(data["teacher2_id"])
        if data.get("classroom_id") not in (None, ""):
            int(data["classroom_id"])
        if data.get("classroom2_id") not in (None, ""):
            int(data["classroom2_id"])
    except (TypeError, ValueError):
        return "Некорректно заполнены числовые поля занятия."

    if week not in (1, 2):
        return "Неделя должна быть 1 или 2."
    if weekday not in range(1, 7):
        return "День недели должен быть от 1 до 6."
    if period not in range(1, 5):
        return "Номер пары должен быть от 1 до 4."

    if teacher2_id is not None and teacher2_id == teacher_id:
        return "Для подгрупп нужны два разных преподавателя."

    if data.get("classroom2_id") not in (None, "") and data.get("teacher2_id") in (
        None,
        "",
    ):
        return "Вторая аудитория указана без второго преподавателя."

    lesson_type = str(data.get("lesson_type", "Лекция")).strip()
    if not lesson_type:
        return "Не заполнен тип занятия."

    return None


def conflict_message(data, exclude_id=None, draft_id=None):
    """Return a human-readable conflict that names the colliding resource.

    Group / teacher / classroom conflicts apply even if subject is not chosen yet.
    Teachers and classrooms are checked against both primary and subgroup slots.
    """
    db = get_db()
    week = int(data["week"])
    weekday = int(data["weekday"])
    period = int(data["period"])
    group_id = int(data["group_id"])
    teacher_id = int(data["teacher_id"])
    teacher2_id = (
        int(data["teacher2_id"])
        if data.get("teacher2_id") not in (None, "")
        else None
    )
    classroom_id = (
        int(data["classroom_id"])
        if data.get("classroom_id") not in (None, "")
        else None
    )
    classroom2_id = (
        int(data["classroom2_id"])
        if data.get("classroom2_id") not in (None, "")
        else None
    )

    def _find(extra_sql, params, label_builder):
        query = f"""
            SELECT
                lessons.id,
                groups_ref.name AS group_name,
                teachers.full_name AS teacher_name,
                teachers2.full_name AS teacher2_name,
                classrooms.name AS classroom_name,
                classrooms2.name AS classroom2_name
            FROM {_lesson_source(draft_id)}
            JOIN groups_ref ON groups_ref.id = lessons.group_id
            JOIN teachers ON teachers.id = lessons.teacher_id
            LEFT JOIN teachers AS teachers2 ON teachers2.id = lessons.teacher2_id
            LEFT JOIN classrooms ON classrooms.id = lessons.classroom_id
            LEFT JOIN classrooms AS classrooms2 ON classrooms2.id = lessons.classroom2_id
            WHERE lessons.week = ?
              AND lessons.weekday = ?
              AND lessons.period = ?
              AND {extra_sql}
        """
        values = [week, weekday, period, *params]
        if draft_id is not None:
            query += " AND lessons.draft_id = ?"
            values.append(int(draft_id))
        if exclude_id:
            query += " AND lessons.id != ?"
            values.append(exclude_id)
        query += " LIMIT 1"
        row = db.execute(query, values).fetchone()
        if not row:
            return None
        return label_builder(row)

    day_name = DAYS.get(weekday, str(weekday))
    slot = f"{day_name}, {period} пара, {week}-я неделя"

    group_conflict = _find(
        "lessons.group_id = ?",
        [group_id],
        lambda row: (
            f"Конфликт: группа «{row['group_name']}» уже занята ({slot})."
        ),
    )
    if group_conflict:
        return group_conflict

    def teacher_busy(tid, label_name=None):
        return _find(
            "(lessons.teacher_id = ? OR lessons.teacher2_id = ?)",
            [tid, tid],
            lambda row: (
                f"Конфликт: преподаватель «{label_name or row['teacher_name']}» уже ведёт занятие "
                f"у группы «{row['group_name']}» ({slot})."
            ),
        )

    # Resolve display names for clearer messages when checking teacher2
    teacher_row = db.execute(
        "SELECT full_name FROM teachers WHERE id = ?", (teacher_id,)
    ).fetchone()
    teacher_name = teacher_row["full_name"] if teacher_row else str(teacher_id)

    teacher_conflict = teacher_busy(teacher_id, teacher_name)
    if teacher_conflict:
        return teacher_conflict

    if teacher2_id is not None:
        teacher2_row = db.execute(
            "SELECT full_name FROM teachers WHERE id = ?", (teacher2_id,)
        ).fetchone()
        teacher2_name = (
            teacher2_row["full_name"] if teacher2_row else str(teacher2_id)
        )
        teacher2_conflict = teacher_busy(teacher2_id, teacher2_name)
        if teacher2_conflict:
            return teacher2_conflict

    def room_busy(rid, room_label=None):
        return _find(
            "(lessons.classroom_id = ? OR lessons.classroom2_id = ?)",
            [rid, rid],
            lambda row: (
                f"Конфликт: аудитория «{room_label or row['classroom_name']}» уже занята "
                f"группой «{row['group_name']}» ({slot})."
            ),
        )

    if classroom_id is not None:
        room_row = db.execute(
            "SELECT name FROM classrooms WHERE id = ?", (classroom_id,)
        ).fetchone()
        room_name = room_row["name"] if room_row else str(classroom_id)
        room_conflict = room_busy(classroom_id, room_name)
        if room_conflict:
            return room_conflict

    if classroom2_id is not None:
        if classroom_id is not None and classroom2_id == classroom_id:
            return (
                f"Конфликт: аудитория уже указана для обеих подгрупп ({slot})."
            )
        room2_row = db.execute(
            "SELECT name FROM classrooms WHERE id = ?", (classroom2_id,)
        ).fetchone()
        room2_name = room2_row["name"] if room2_row else str(classroom2_id)
        room2_conflict = room_busy(classroom2_id, room2_name)
        if room2_conflict:
            return room2_conflict

    return None


def _optional_int(value):
    if value in (None, ""):
        return None
    return int(value)


def _normalize(data):
    result = dict(data)
    result["week"] = int(result["week"])
    result["weekday"] = int(result["weekday"])
    result["period"] = int(result["period"])
    result["group_id"] = int(result["group_id"])
    result["teacher_id"] = int(result["teacher_id"])
    result["teacher2_id"] = _optional_int(result.get("teacher2_id"))
    result["subject_id"] = _optional_int(result.get("subject_id"))
    result["classroom_id"] = _optional_int(result.get("classroom_id"))
    result["classroom2_id"] = _optional_int(result.get("classroom2_id"))
    if result["teacher2_id"] is None:
        result["classroom2_id"] = None
    result["lesson_type"] = str(result.get("lesson_type", "Лекция")).strip()
    result["note"] = str(result.get("note", "")).strip()
    return result


def _ensure_teacher_subject(db, teacher_id, subject_id):
    if subject_id is None:
        return None
    assignment = db.execute(
        "SELECT 1 FROM teacher_subjects WHERE teacher_id = ? AND subject_id = ?",
        (teacher_id, subject_id),
    ).fetchone()
    if assignment is None:
        return "Выбранная дисциплина не привязана к этому преподавателю."
    return None


def _ensure_teachers_exist(db, teacher_id, teacher2_id):
    row = db.execute("SELECT id FROM teachers WHERE id = ?", (teacher_id,)).fetchone()
    if row is None:
        return "Преподаватель не найден."
    if teacher2_id is not None:
        row2 = db.execute(
            "SELECT id FROM teachers WHERE id = ?", (teacher2_id,)
        ).fetchone()
        if row2 is None:
            return "Второй преподаватель не найден."
    return None


def create_lesson(data, draft_id=None):
    force = bool(data.get("force"))
    error = validate_lesson(data)
    if error:
        return None, error

    data = _normalize(data)

    db = get_db()
    exists_error = _ensure_teachers_exist(db, data["teacher_id"], data["teacher2_id"])
    if exists_error:
        return None, exists_error

    assignment_error = _ensure_teacher_subject(db, data["teacher_id"], data["subject_id"])
    if assignment_error:
        return None, assignment_error

    if data["teacher2_id"] is not None:
        assignment2 = _ensure_teacher_subject(
            db, data["teacher2_id"], data["subject_id"]
        )
        if assignment2:
            return None, (
                "Выбранная дисциплина не привязана ко второму преподавателю."
            )

    if not force:
        conflict = conflict_message(data, draft_id=draft_id)
        if conflict:
            return None, conflict

    table = _lesson_table(draft_id)
    if draft_id is None:
        cursor = db.execute(
            f"""
            INSERT INTO {table} (
                group_id, teacher_id, teacher2_id, subject_id,
                classroom_id, classroom2_id,
                weekday, period, week, lesson_type, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                data["group_id"],
                data["teacher_id"],
                data["teacher2_id"],
                data["subject_id"],
                data["classroom_id"],
                data["classroom2_id"],
                data["weekday"],
                data["period"],
                data["week"],
                data["lesson_type"],
                data["note"],
            ),
        )
    else:
        cursor = db.execute(
            f"""
            INSERT INTO {table} (
                draft_id, group_id, teacher_id, teacher2_id, subject_id,
                classroom_id, classroom2_id,
                weekday, period, week, lesson_type, note
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(draft_id),
                data["group_id"],
                data["teacher_id"],
                data["teacher2_id"],
                data["subject_id"],
                data["classroom_id"],
                data["classroom2_id"],
                data["weekday"],
                data["period"],
                data["week"],
                data["lesson_type"],
                data["note"],
            ),
        )
    _touch_draft(db, draft_id)
    db.commit()
    return cursor.lastrowid, None


def _lesson_exists(db, lesson_id, draft_id):
    table = _lesson_table(draft_id)
    if draft_id is None:
        return db.execute(
            f"SELECT id FROM {table} WHERE id = ?",
            (lesson_id,),
        ).fetchone()
    return db.execute(
        f"SELECT id FROM {table} WHERE id = ? AND draft_id = ?",
        (lesson_id, int(draft_id)),
    ).fetchone()


def update_lesson(lesson_id, data, draft_id=None):
    force = bool(data.get("force"))
    if not _lesson_exists(get_db(), lesson_id, draft_id):
        return False, "Занятие не найдено."

    error = validate_lesson(data)
    if error:
        return False, error

    data = _normalize(data)

    db = get_db()
    exists_error = _ensure_teachers_exist(db, data["teacher_id"], data["teacher2_id"])
    if exists_error:
        return False, exists_error

    assignment_error = _ensure_teacher_subject(db, data["teacher_id"], data["subject_id"])
    if assignment_error:
        return False, assignment_error

    if data["teacher2_id"] is not None:
        assignment2 = _ensure_teacher_subject(
            db, data["teacher2_id"], data["subject_id"]
        )
        if assignment2:
            return False, (
                "Выбранная дисциплина не привязана ко второму преподавателю."
            )

    if not force:
        conflict = conflict_message(data, lesson_id, draft_id=draft_id)
        if conflict:
            return False, conflict

    table = _lesson_table(draft_id)
    where = "id = ?"
    params = [
        data["group_id"],
        data["teacher_id"],
        data["teacher2_id"],
        data["subject_id"],
        data["classroom_id"],
        data["classroom2_id"],
        data["weekday"],
        data["period"],
        data["week"],
        data["lesson_type"],
        data["note"],
        lesson_id,
    ]
    if draft_id is not None:
        where += " AND draft_id = ?"
        params.append(int(draft_id))

    db.execute(
        f"""
        UPDATE {table}
        SET group_id = ?, teacher_id = ?, teacher2_id = ?, subject_id = ?,
            classroom_id = ?, classroom2_id = ?,
            weekday = ?, period = ?, week = ?, lesson_type = ?, note = ?
        WHERE {where}
        """,
        params,
    )
    _touch_draft(db, draft_id)
    db.commit()
    return True, None


def delete_lesson(lesson_id, draft_id=None):
    db = get_db()
    table = _lesson_table(draft_id)
    if draft_id is None:
        cursor = db.execute(f"DELETE FROM {table} WHERE id = ?", (lesson_id,))
    else:
        cursor = db.execute(
            f"DELETE FROM {table} WHERE id = ? AND draft_id = ?",
            (lesson_id, int(draft_id)),
        )
    if cursor.rowcount:
        _touch_draft(db, draft_id)
    db.commit()
    return cursor.rowcount > 0


def copy_week(source_week, target_week, draft_id=None):
    """Copy all lessons from one week onto another, overwriting the target week."""
    if source_week not in (1, 2) or target_week not in (1, 2):
        return False, "Неделя должна быть 1 или 2.", 0, 0

    if source_week == target_week:
        return False, "Нельзя копировать расписание на ту же неделю.", 0, 0

    db = get_db()
    table = _lesson_table(draft_id)
    draft_sql = ""
    params = [source_week]
    if draft_id is not None:
        draft_sql = " AND draft_id = ?"
        params.append(int(draft_id))
    lessons = db.execute(
        f"""
        SELECT
            group_id, teacher_id, teacher2_id, subject_id,
            classroom_id, classroom2_id,
            weekday, period, lesson_type, note
        FROM {table}
        WHERE week = ?{draft_sql}
        ORDER BY weekday, period, id
        """,
        params,
    ).fetchall()

    if not lessons:
        return False, f"В {source_week}-й неделе нет занятий для копирования.", 0, 0

    try:
        db.execute("BEGIN")
        if draft_id is None:
            removed = db.execute(
                f"DELETE FROM {table} WHERE week = ?",
                (target_week,),
            ).rowcount
            db.executemany(
                f"""
                INSERT INTO {table} (
                    group_id, teacher_id, teacher2_id, subject_id,
                    classroom_id, classroom2_id,
                    weekday, period, week, lesson_type, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        lesson["group_id"],
                        lesson["teacher_id"],
                        lesson["teacher2_id"],
                        lesson["subject_id"],
                        lesson["classroom_id"],
                        lesson["classroom2_id"],
                        lesson["weekday"],
                        lesson["period"],
                        target_week,
                        lesson["lesson_type"],
                        lesson["note"],
                    )
                    for lesson in lessons
                ],
            )
        else:
            removed = db.execute(
                f"DELETE FROM {table} WHERE week = ? AND draft_id = ?",
                (target_week, int(draft_id)),
            ).rowcount
            db.executemany(
                f"""
                INSERT INTO {table} (
                    draft_id, group_id, teacher_id, teacher2_id, subject_id,
                    classroom_id, classroom2_id,
                    weekday, period, week, lesson_type, note
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        int(draft_id),
                        lesson["group_id"],
                        lesson["teacher_id"],
                        lesson["teacher2_id"],
                        lesson["subject_id"],
                        lesson["classroom_id"],
                        lesson["classroom2_id"],
                        lesson["weekday"],
                        lesson["period"],
                        target_week,
                        lesson["lesson_type"],
                        lesson["note"],
                    )
                    for lesson in lessons
                ],
            )
        _touch_draft(db, draft_id)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return True, None, len(lessons), removed
