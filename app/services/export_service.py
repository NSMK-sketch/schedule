"""Export schedule to Excel by optional group filter."""

from __future__ import annotations

from app.database import get_db
from app.services.lesson_service import DAYS, list_lessons
from app.services.xlsx_writer import (
    STYLE_DAY,
    STYLE_HEADER,
    STYLE_PERIOD,
    STYLE_WRAP,
    build_xlsx,
    cell,
    rich_cell,
)


def _list_groups(group_ids: list[int] | None) -> list[dict]:
    db = get_db()
    if group_ids:
        placeholders = ",".join("?" for _ in group_ids)
        rows = db.execute(
            f"""
            SELECT id, name, speciality, course
            FROM groups_ref
            WHERE id IN ({placeholders})
            ORDER BY course, name
            """,
            group_ids,
        ).fetchall()
        by_id = {row["id"]: dict(row) for row in rows}
        return [by_id[gid] for gid in group_ids if gid in by_id]

    rows = db.execute(
        """
        SELECT id, name, speciality, course
        FROM groups_ref
        ORDER BY course, name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _lesson_cell(lesson: dict | None):
    if not lesson:
        return None

    subject = (lesson.get("subject_name") or "").strip() or "Предмет не назначен"
    teacher1 = (lesson.get("teacher_name") or lesson.get("teacher_short") or "").strip()
    teacher2 = ""
    if lesson.get("teacher2_id"):
        teacher2 = (
            lesson.get("teacher2_name") or lesson.get("teacher2_short") or ""
        ).strip()
    teacher = f"{teacher1} / {teacher2}" if teacher2 else teacher1

    rooms = []
    if lesson.get("classroom_name"):
        rooms.append(str(lesson["classroom_name"]))
    if lesson.get("teacher2_id") and lesson.get("classroom2_name"):
        rooms.append(str(lesson["classroom2_name"]))
    room = f"ауд. {' / '.join(rooms)}" if rooms else ""

    runs = [{"text": subject, "bold": True, "size": 12}]
    if teacher:
        runs.append({"text": f"\n{teacher}", "bold": False, "size": 10})
    if room:
        runs.append({"text": f"\n{room}", "bold": False, "size": 9})
    return rich_cell(runs, style=STYLE_WRAP)


def _board_rows(
    groups: list[dict],
    lessons: list[dict],
    week: int,
    *,
    compact: bool = False,
) -> list[list]:
    week_lessons = [lesson for lesson in lessons if int(lesson["week"]) == week]
    if compact:
        used_ids = {int(lesson["group_id"]) for lesson in week_lessons}
        groups = [group for group in groups if int(group["id"]) in used_ids]

    if not groups:
        return [
            [cell("День", STYLE_HEADER), cell("Пара", STYLE_HEADER)],
            [cell("Занятий нет", STYLE_DAY), None],
        ]

    header = [
        cell("День", STYLE_HEADER),
        cell("Пара", STYLE_HEADER),
    ]
    header.extend(cell(group["name"], STYLE_HEADER) for group in groups)
    rows: list[list] = [header]

    index = {
        (
            int(lesson["weekday"]),
            int(lesson["period"]),
            int(lesson["group_id"]),
        ): lesson
        for lesson in week_lessons
    }

    for weekday in range(1, 7):
        periods = []
        for period in range(1, 5):
            has_lesson = any(
                (weekday, period, int(group["id"])) in index for group in groups
            )
            if not compact or has_lesson:
                periods.append(period)
        if not periods:
            continue

        first = True
        for period in periods:
            day_value = DAYS.get(weekday, str(weekday)) if first else ""
            first = False
            row = [
                cell(day_value, STYLE_DAY) if day_value else None,
                cell(str(period), STYLE_PERIOD),
            ]
            for group in groups:
                lesson = index.get((weekday, period, int(group["id"])))
                row.append(_lesson_cell(lesson))
            rows.append(row)

    return rows


def _flat_rows(groups: list[dict], lessons: list[dict]) -> list[list]:
    group_names = {int(group["id"]): group["name"] for group in groups}
    allowed = set(group_names)
    header = [
        cell(title, STYLE_HEADER)
        for title in (
            "Неделя",
            "День",
            "Пара",
            "Группа",
            "Дисциплина",
            "Преподаватель",
            "Преподаватель 2",
            "Аудитория",
            "Аудитория 2",
            "Тип",
        )
    ]
    rows: list[list] = [header]

    filtered = [
        lesson for lesson in lessons if int(lesson["group_id"]) in allowed
    ]
    filtered.sort(
        key=lambda item: (
            int(item["week"]),
            int(item["weekday"]),
            int(item["period"]),
            group_names.get(int(item["group_id"]), ""),
        )
    )

    for lesson in filtered:
        teacher2 = (
            (lesson.get("teacher2_name") or "") if lesson.get("teacher2_id") else ""
        )
        room2 = (
            (lesson.get("classroom2_name") or "") if lesson.get("teacher2_id") else ""
        )
        rows.append(
            [
                cell(str(lesson["week"])),
                cell(DAYS.get(int(lesson["weekday"]), str(lesson["weekday"]))),
                cell(str(lesson["period"]), STYLE_PERIOD),
                cell(group_names.get(int(lesson["group_id"]), ""), STYLE_HEADER),
                cell(lesson.get("subject_name") or "", STYLE_HEADER),
                cell(lesson.get("teacher_name") or ""),
                cell(teacher2),
                cell(lesson.get("classroom_name") or ""),
                cell(room2),
                cell(lesson.get("lesson_type") or ""),
            ]
        )
    return rows


def _lesson_matches_export_filters(
    lesson: dict,
    *,
    teacher_id: int | None,
    subject_id: int | None,
    query: str,
) -> bool:
    if teacher_id is not None:
        primary = lesson.get("teacher_id")
        secondary = lesson.get("teacher2_id")
        if int(primary or 0) != teacher_id and int(secondary or 0) != teacher_id:
            return False
    if subject_id is not None and int(lesson.get("subject_id") or 0) != subject_id:
        return False
    if not query:
        return True
    haystack = " ".join(
        str(lesson.get(key) or "")
        for key in (
            "subject_name",
            "subject_short",
            "group_name",
            "teacher_name",
            "teacher_short",
            "teacher2_name",
            "teacher2_short",
            "classroom_name",
            "classroom2_name",
        )
    ).casefold()
    return query.casefold() in haystack


def _filter_label(
    *,
    teacher_id: int | None,
    subject_id: int | None,
    query: str,
) -> str:
    db = get_db()
    parts: list[str] = []
    if teacher_id is not None:
        row = db.execute(
            "SELECT full_name FROM teachers WHERE id = ?", (teacher_id,)
        ).fetchone()
        if row:
            parts.append(f"преподаватель: {row['full_name']}")
    if subject_id is not None:
        row = db.execute(
            "SELECT name FROM subjects WHERE id = ?", (subject_id,)
        ).fetchone()
        if row:
            parts.append(f"предмет: {row['name']}")
    if query:
        parts.append(f"поиск: {query}")
    return " · ".join(parts)


def export_schedule_xlsx(
    group_ids: list[int] | None = None,
    *,
    teacher_id: int | None = None,
    subject_id: int | None = None,
    query: str = "",
    draft_id: int | None = None,
) -> tuple[bytes, str]:
    """Return (xlsx_bytes, filename) for filtered schedule."""
    groups = _list_groups(group_ids)
    if not groups:
        raise ValueError("Нет групп для экспорта по выбранным фильтрам.")

    slot_filters = teacher_id is not None or subject_id is not None or bool(query)
    lessons = list_lessons(draft_id=draft_id)
    allowed = {int(group["id"]) for group in groups}
    lessons = [
        lesson
        for lesson in lessons
        if int(lesson["group_id"]) in allowed
        and _lesson_matches_export_filters(
            lesson,
            teacher_id=teacher_id,
            subject_id=subject_id,
            query=query or "",
        )
    ]

    if slot_filters:
        used_ids = {int(lesson["group_id"]) for lesson in lessons}
        groups = [group for group in groups if int(group["id"]) in used_ids]

    if not groups or not lessons:
        raise ValueError("Нет занятий по выбранным фильтрам.")

    compact = slot_filters or len(groups) <= 6
    filter_note = _filter_label(
        teacher_id=teacher_id, subject_id=subject_id, query=query or ""
    )

    board_widths = [12.0, 8.0] + [22.0] * max(len(groups), 1)
    sheets: list[tuple[str, list[list]]] = []

    if filter_note:
        info_rows = [
            [cell("Фильтр", STYLE_HEADER), cell(filter_note, STYLE_WRAP)],
            [
                cell("Групп", STYLE_HEADER),
                cell(str(len(groups))),
                cell("Занятий", STYLE_HEADER),
                cell(str(len(lessons))),
            ],
        ]
        sheets.append(("Фильтр", info_rows))

    sheets.extend(
        [
            ("1 неделя", _board_rows(groups, lessons, 1, compact=compact)),
            ("2 неделя", _board_rows(groups, lessons, 2, compact=compact)),
            ("Список", _flat_rows(groups, lessons)),
        ]
    )
    payload = build_xlsx(
        sheets,
        column_widths=board_widths,
        row_height=40 if compact else 48,
    )

    if len(groups) == 1:
        filename = f"расписание_{groups[0]['name']}.xlsx"
    elif slot_filters:
        filename = f"расписание_фильтр_{len(groups)}_групп.xlsx"
    elif group_ids:
        filename = f"расписание_{len(groups)}_групп.xlsx"
    else:
        filename = "расписание_все_группы.xlsx"
    if draft_id is not None:
        filename = f"черновик_{filename}"

    filename = (
        filename.replace("/", "-")
        .replace("\\", "-")
        .replace(":", "-")
        .replace("*", "")
        .replace("?", "")
        .replace('"', "")
        .replace("<", "")
        .replace(">", "")
        .replace("|", "-")
    )
    return payload, filename
