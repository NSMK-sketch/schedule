"""Import groups/teachers from Excel into reference tables."""

from __future__ import annotations

from pathlib import Path

from app.database import get_db
from app.services.xlsx_reader import (
    parse_classrooms_rows,
    parse_groups_rows,
    parse_teachers_rows,
    read_xlsx_rows,
)


BASE_DIR = Path(__file__).resolve().parent.parent.parent

DEFAULT_IMPORT_FILES = {
    "groups": BASE_DIR / "Группы.xlsx",
    "teachers": BASE_DIR / "Сотрудники.xlsx",
    "classrooms": BASE_DIR / "Перечень аудиторий.xlsx",
}

TEACHER_COLORS = [
    "#3B82F6",
    "#22C55E",
    "#EAB308",
    "#A855F7",
    "#EF4444",
    "#0EA5E9",
    "#F97316",
    "#14B8A6",
    "#EC4899",
    "#6366F1",
]


def _short_name_from_full(full_name: str) -> str:
    return "".join(part[0].upper() for part in full_name.split() if part)[:4]


def resolve_import_path(name: str, uploaded_path: Path | None = None) -> Path:
    if uploaded_path is not None:
        return uploaded_path
    path = DEFAULT_IMPORT_FILES.get(name)
    if path is None:
        raise ValueError("Импорт для этого справочника не поддерживается.")
    if not path.is_file():
        raise FileNotFoundError(
            f"Файл «{path.name}» не найден в папке проекта schedule."
        )
    return path


def import_groups(path: Path | None = None) -> dict:
    file_path = resolve_import_path("groups", path)
    items = parse_groups_rows(read_xlsx_rows(file_path))
    db = get_db()

    existing = {
        row["name"].casefold(): row["id"]
        for row in db.execute("SELECT id, name FROM groups_ref")
    }

    created = 0
    updated = 0
    skipped = 0

    for item in items:
        key = item["name"].casefold()
        if key in existing:
            db.execute(
                """
                UPDATE groups_ref
                SET name = ?, speciality = ?, course = ?
                WHERE id = ?
                """,
                (item["name"], item["speciality"], item["course"], existing[key]),
            )
            updated += 1
        else:
            db.execute(
                """
                INSERT INTO groups_ref (name, speciality, course)
                VALUES (?, ?, ?)
                """,
                (item["name"], item["speciality"], item["course"]),
            )
            created += 1

    db.commit()
    return {
        "ok": True,
        "source": file_path.name,
        "total": len(items),
        "created": created,
        "updated": updated,
        "skipped": skipped,
    }


def import_teachers(path: Path | None = None) -> dict:
    file_path = resolve_import_path("teachers", path)
    items = parse_teachers_rows(read_xlsx_rows(file_path))
    db = get_db()

    existing = {
        row["full_name"].casefold(): dict(row)
        for row in db.execute("SELECT id, full_name, short_name, color FROM teachers")
    }

    created = 0
    updated = 0
    color_index = 0

    for item in items:
        key = item["full_name"].casefold()
        short_name = _short_name_from_full(item["full_name"])
        if key in existing:
            db.execute(
                """
                UPDATE teachers
                SET full_name = ?, short_name = ?
                WHERE id = ?
                """,
                (item["full_name"], short_name or existing[key]["short_name"], existing[key]["id"]),
            )
            updated += 1
        else:
            color = TEACHER_COLORS[color_index % len(TEACHER_COLORS)]
            color_index += 1
            db.execute(
                """
                INSERT INTO teachers (full_name, short_name, color)
                VALUES (?, ?, ?)
                """,
                (item["full_name"], short_name or "ПРП", color),
            )
            created += 1

    db.commit()
    return {
        "ok": True,
        "source": file_path.name,
        "total": len(items),
        "created": created,
        "updated": updated,
        "skipped": 0,
    }


def import_classrooms(path: Path | None = None) -> dict:
    file_path = resolve_import_path("classrooms", path)
    items = parse_classrooms_rows(read_xlsx_rows(file_path))
    db = get_db()

    existing = {
        row["name"].casefold(): row["id"]
        for row in db.execute("SELECT id, name FROM classrooms")
    }

    created = 0
    updated = 0

    for item in items:
        key = item["name"].casefold()
        if key in existing:
            db.execute(
                """
                UPDATE classrooms
                SET name = ?, room_type = ?
                WHERE id = ?
                """,
                (item["name"], item["room_type"], existing[key]),
            )
            updated += 1
        else:
            db.execute(
                """
                INSERT INTO classrooms (name, room_type, seats)
                VALUES (?, ?, ?)
                """,
                (item["name"], item["room_type"], item["seats"]),
            )
            created += 1

    db.commit()
    return {
        "ok": True,
        "source": file_path.name,
        "total": len(items),
        "created": created,
        "updated": updated,
        "skipped": 0,
    }


def clear_directory(name: str) -> dict:
    """Delete every row in a reference table (and related schedule links)."""
    db = get_db()

    if name == "groups":
        # Every lesson references a group — clearing groups clears the schedule.
        removed_lessons = db.execute("DELETE FROM lessons").rowcount
        removed_items = db.execute("DELETE FROM groups_ref").rowcount
    elif name == "teachers":
        removed_lessons = db.execute("DELETE FROM lessons").rowcount
        db.execute("DELETE FROM teacher_subjects")
        removed_items = db.execute("DELETE FROM teachers").rowcount
    elif name == "subjects":
        removed_lessons = db.execute(
            "DELETE FROM lessons WHERE subject_id IS NOT NULL"
        ).rowcount
        db.execute("DELETE FROM teacher_subjects")
        removed_items = db.execute("DELETE FROM subjects").rowcount
    elif name == "classrooms":
        db.execute(
            "UPDATE lessons SET classroom_id = NULL WHERE classroom_id IS NOT NULL"
        )
        db.execute(
            "UPDATE lessons SET classroom2_id = NULL WHERE classroom2_id IS NOT NULL"
        )
        removed_items = db.execute("DELETE FROM classrooms").rowcount
        removed_lessons = 0
    else:
        raise ValueError("Неизвестный справочник.")

    db.commit()
    return {
        "ok": True,
        "removed_items": removed_items,
        "removed_lessons": removed_lessons,
    }
