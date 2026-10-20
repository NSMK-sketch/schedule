import sqlite3
import tempfile
from pathlib import Path

from flask import Blueprint, jsonify, request, session

from app.database import get_db
from app.services.import_service import (
    clear_directory,
    import_classrooms,
    import_groups,
    import_teachers,
)


reference_bp = Blueprint("reference", __name__)

TABLES = {
    "groups": "groups_ref",
    "teachers": "teachers",
    "subjects": "subjects",
    "classrooms": "classrooms",
}

IMPORTABLE = {"groups", "teachers", "classrooms"}


def require_login():
    if "user_id" not in session:
        return jsonify({"error": "Требуется авторизация."}), 401
    return None


def admin_only():
    error = require_login()
    if error:
        return error
    if session.get("role") != "admin":
        return jsonify({"error": "Только администратор может менять справочники."}), 403
    return None


def _required_text(data, field, title):
    value = data.get(field)
    if value is None or not str(value).strip():
        raise ValueError(f"Не заполнено обязательное поле: {title}.")
    return str(value).strip()


def _optional_text(data, field, default=""):
    value = data.get(field)
    if value is None:
        return default
    return str(value).strip()


def _short_name_from_full(full_name):
    return "".join(part[0].upper() for part in full_name.split() if part)[:4]


def _serialize_group(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "speciality": row["speciality"] or "",
        "course": row["course"] or 1,
    }


def _serialize_teacher(row):
    return {
        "id": row["id"],
        "full_name": row["full_name"],
        "short_name": row["short_name"],
        "color": row["color"],
    }


def _serialize_subject(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "short_name": row["short_name"] or "",
        "color": row["color"],
    }


def _serialize_classroom(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "room_type": row["room_type"] or "",
        "seats": row["seats"],
    }


@reference_bp.get("/bootstrap")
def bootstrap():
    error = require_login()
    if error:
        return error

    db = get_db()
    return jsonify(
        {
            "groups": [
                _serialize_group(row)
                for row in db.execute(
                    "SELECT * FROM groups_ref ORDER BY name"
                )
            ],
            "teachers": [
                _serialize_teacher(row)
                for row in db.execute(
                    "SELECT * FROM teachers ORDER BY full_name"
                )
            ],
            "subjects": [
                _serialize_subject(row)
                for row in db.execute("SELECT * FROM subjects ORDER BY name")
            ],
            "classrooms": [
                _serialize_classroom(row)
                for row in db.execute(
                    "SELECT * FROM classrooms ORDER BY name"
                )
            ],
            "teacher_subjects": [
                dict(row)
                for row in db.execute(
                    "SELECT teacher_id, subject_id FROM teacher_subjects"
                )
            ],
        }
    )


@reference_bp.get("/groups")
def list_groups():
    error = require_login()
    if error:
        return error
    db = get_db()
    return jsonify(
        [
            _serialize_group(row)
            for row in db.execute("SELECT * FROM groups_ref ORDER BY name")
        ]
    )


def _save_upload(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    filename = Path(file_storage.filename).name
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Нужен файл в формате .xlsx.")
    suffix = Path(filename).suffix or ".xlsx"
    handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        file_storage.save(handle.name)
    finally:
        handle.close()
    return Path(handle.name)


def _run_import(name):
    error = admin_only()
    if error:
        return error

    if name not in IMPORTABLE:
        return jsonify({"error": "Импорт для этого справочника не поддерживается."}), 404

    temp_path = None
    try:
        if "file" in request.files and request.files["file"].filename:
            temp_path = _save_upload(request.files["file"])

        if name == "groups":
            result = import_groups(temp_path)
        elif name == "teachers":
            result = import_teachers(temp_path)
        else:
            result = import_classrooms(temp_path)
        return jsonify(result)
    except FileNotFoundError as exc:
        return jsonify({"error": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception:
        get_db().rollback()
        return jsonify(
            {"error": "Не удалось импортировать файл. Проверьте формат Excel."}
        ), 500
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


@reference_bp.post("/groups/import")
def import_groups_route():
    return _run_import("groups")


@reference_bp.post("/teachers/import")
def import_teachers_route():
    return _run_import("teachers")


@reference_bp.post("/classrooms/import")
def import_classrooms_route():
    return _run_import("classrooms")


@reference_bp.delete("/references/<name>/all")
@reference_bp.delete("/<name>/all")
def clear_reference(name):
    error = admin_only()
    if error:
        return error

    if name not in TABLES:
        return jsonify({"error": "Неизвестный справочник."}), 404

    try:
        return jsonify(clear_directory(name))
    except ValueError as exc:
        get_db().rollback()
        return jsonify({"error": str(exc)}), 400
    except sqlite3.IntegrityError:
        get_db().rollback()
        return jsonify({"error": "Не удалось очистить справочник."}), 409
    except Exception:
        get_db().rollback()
        return jsonify({"error": "Не удалось очистить справочник. Попробуйте ещё раз."}), 500


def _create(name, data):
    db = get_db()

    if name == "teachers":
        full_name = _required_text(data, "full_name", "ФИО")
        short_name = _optional_text(data, "short_name") or _short_name_from_full(
            full_name
        )
        color = _optional_text(data, "color", "#4f46e5") or "#4f46e5"
        return db.execute(
            "INSERT INTO teachers (full_name, short_name, color) VALUES (?, ?, ?)",
            (full_name, short_name, color),
        ).lastrowid

    if name == "subjects":
        value = _required_text(data, "name", "название")
        short_name = _optional_text(data, "short_name")
        if not short_name:
            short_name = value[:6].upper()
        color = _optional_text(data, "color", "#6366f1") or "#6366f1"
        return db.execute(
            "INSERT INTO subjects (name, short_name, color) VALUES (?, ?, ?)",
            (value, short_name, color),
        ).lastrowid

    if name == "groups":
        value = _required_text(data, "name", "название группы")
        speciality = _optional_text(data, "speciality")
        try:
            course = int(data.get("course") or 1)
        except (TypeError, ValueError) as exc:
            raise ValueError("Курс должен быть числом от 1 до 6.") from exc
        if course not in range(1, 7):
            raise ValueError("Курс должен быть числом от 1 до 6.")
        return db.execute(
            "INSERT INTO groups_ref (name, speciality, course) VALUES (?, ?, ?)",
            (value, speciality, course),
        ).lastrowid

    if name == "classrooms":
        value = _required_text(data, "name", "номер аудитории")
        room_type = _optional_text(data, "room_type")
        seats = data.get("seats")
        if seats in (None, ""):
            seats = None
        else:
            try:
                seats = int(seats)
            except (TypeError, ValueError) as exc:
                raise ValueError("Количество мест должно быть числом.") from exc
            if seats < 0:
                raise ValueError("Количество мест не может быть отрицательным.")
        return db.execute(
            "INSERT INTO classrooms (name, room_type, seats) VALUES (?, ?, ?)",
            (value, room_type, seats),
        ).lastrowid

    raise ValueError("Неизвестный справочник.")


def _update(name, item_id, data):
    db = get_db()
    table = TABLES[name]
    existing = db.execute(
        f"SELECT * FROM {table} WHERE id = ?", (item_id,)
    ).fetchone()
    if existing is None:
        return False

    if name == "teachers":
        full_name = _required_text(data, "full_name", "ФИО")
        short_name = _optional_text(data, "short_name") or _short_name_from_full(
            full_name
        )
        color = _optional_text(data, "color", existing["color"]) or existing["color"]
        db.execute(
            """
            UPDATE teachers
            SET full_name = ?, short_name = ?, color = ?
            WHERE id = ?
            """,
            (full_name, short_name, color, item_id),
        )
        return True

    if name == "subjects":
        value = _required_text(data, "name", "название")
        short_name = _optional_text(data, "short_name") or existing["short_name"] or value[:6].upper()
        color = _optional_text(data, "color", existing["color"]) or existing["color"]
        db.execute(
            """
            UPDATE subjects
            SET name = ?, short_name = ?, color = ?
            WHERE id = ?
            """,
            (value, short_name, color, item_id),
        )
        return True

    if name == "groups":
        value = _required_text(data, "name", "название группы")
        speciality = _optional_text(data, "speciality", existing["speciality"] or "")
        try:
            course = int(data.get("course", existing["course"] or 1))
        except (TypeError, ValueError) as exc:
            raise ValueError("Курс должен быть числом от 1 до 6.") from exc
        if course not in range(1, 7):
            raise ValueError("Курс должен быть числом от 1 до 6.")
        db.execute(
            """
            UPDATE groups_ref
            SET name = ?, speciality = ?, course = ?
            WHERE id = ?
            """,
            (value, speciality, course, item_id),
        )
        return True

    if name == "classrooms":
        value = _required_text(data, "name", "номер аудитории")
        room_type = _optional_text(data, "room_type", existing["room_type"] or "")
        seats = data.get("seats", existing["seats"])
        if seats in (None, ""):
            seats = None
        else:
            try:
                seats = int(seats)
            except (TypeError, ValueError) as exc:
                raise ValueError("Количество мест должно быть числом.") from exc
            if seats < 0:
                raise ValueError("Количество мест не может быть отрицательным.")
        db.execute(
            """
            UPDATE classrooms
            SET name = ?, room_type = ?, seats = ?
            WHERE id = ?
            """,
            (value, room_type, seats, item_id),
        )
        return True

    raise ValueError("Неизвестный справочник.")


@reference_bp.post("/references/<name>")
@reference_bp.post("/<name>")
def create_reference(name):
    error = admin_only()
    if error:
        return error

    if name not in TABLES:
        return jsonify({"error": "Неизвестный справочник."}), 404

    data = request.get_json(silent=True) or {}

    try:
        item_id = _create(name, data)
        get_db().commit()
        return jsonify({"id": item_id}), 201
    except ValueError as exc:
        get_db().rollback()
        return jsonify({"error": str(exc)}), 400
    except sqlite3.IntegrityError:
        get_db().rollback()
        return jsonify({"error": "Такая запись уже существует."}), 409


@reference_bp.put("/references/<name>/<int:item_id>")
@reference_bp.put("/<name>/<int:item_id>")
def update_reference(name, item_id):
    error = admin_only()
    if error:
        return error

    if name not in TABLES:
        return jsonify({"error": "Неизвестный справочник."}), 404

    data = request.get_json(silent=True) or {}

    try:
        updated = _update(name, item_id, data)
        if not updated:
            return jsonify({"error": "Запись не найдена."}), 404
        get_db().commit()
        return jsonify({"ok": True})
    except ValueError as exc:
        get_db().rollback()
        return jsonify({"error": str(exc)}), 400
    except sqlite3.IntegrityError:
        get_db().rollback()
        return jsonify({"error": "Такая запись уже существует."}), 409


@reference_bp.put("/teachers/<int:teacher_id>/subjects")
def update_teacher_subjects(teacher_id):
    error = admin_only()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    subject_ids = data.get("subject_ids")
    if not isinstance(subject_ids, list):
        return jsonify({"error": "Список дисциплин указан неверно."}), 400

    db = get_db()
    teacher = db.execute(
        "SELECT id FROM teachers WHERE id = ?", (teacher_id,)
    ).fetchone()
    if teacher is None:
        return jsonify({"error": "Преподаватель не найден."}), 404

    try:
        normalized_ids = sorted({int(subject_id) for subject_id in subject_ids})
    except (TypeError, ValueError):
        return jsonify({"error": "Идентификаторы дисциплин указаны неверно."}), 400

    if normalized_ids:
        placeholders = ",".join("?" for _ in normalized_ids)
        count = db.execute(
            f"SELECT COUNT(*) FROM subjects WHERE id IN ({placeholders})",
            normalized_ids,
        ).fetchone()[0]
        if count != len(normalized_ids):
            return jsonify({"error": "Одна или несколько дисциплин не найдены."}), 400

    db.execute("DELETE FROM teacher_subjects WHERE teacher_id = ?", (teacher_id,))
    db.executemany(
        "INSERT INTO teacher_subjects (teacher_id, subject_id) VALUES (?, ?)",
        [(teacher_id, subject_id) for subject_id in normalized_ids],
    )
    db.commit()

    return jsonify({"ok": True, "subject_ids": normalized_ids})


@reference_bp.delete("/references/<name>/<int:item_id>")
@reference_bp.delete("/<name>/<int:item_id>")
def delete_reference(name, item_id):
    error = admin_only()
    if error:
        return error

    if name not in TABLES:
        return jsonify({"error": "Неизвестный справочник."}), 404

    db = get_db()
    existing = db.execute(
        f"SELECT id FROM {TABLES[name]} WHERE id = ?",
        (item_id,),
    ).fetchone()
    if existing is None:
        return jsonify({"error": "Запись не найдена."}), 404

    try:
        removed_lessons = 0

        if name == "groups":
            removed_lessons = db.execute(
                "DELETE FROM lessons WHERE group_id = ?", (item_id,)
            ).rowcount
        elif name == "teachers":
            removed_lessons = db.execute(
                "DELETE FROM lessons WHERE teacher_id = ?", (item_id,)
            ).rowcount
            # Subgroup-only: drop second teacher, keep the lesson
            db.execute(
                """
                UPDATE lessons
                SET teacher2_id = NULL, classroom2_id = NULL
                WHERE teacher2_id = ?
                """,
                (item_id,),
            )
            db.execute(
                "DELETE FROM teacher_subjects WHERE teacher_id = ?", (item_id,)
            )
        elif name == "subjects":
            removed_lessons = db.execute(
                "DELETE FROM lessons WHERE subject_id = ?", (item_id,)
            ).rowcount
            db.execute(
                "DELETE FROM teacher_subjects WHERE subject_id = ?", (item_id,)
            )
        elif name == "classrooms":
            # Keep lessons, just unlink the room
            db.execute(
                "UPDATE lessons SET classroom_id = NULL WHERE classroom_id = ?",
                (item_id,),
            )
            db.execute(
                "UPDATE lessons SET classroom2_id = NULL WHERE classroom2_id = ?",
                (item_id,),
            )

        cursor = db.execute(
            f"DELETE FROM {TABLES[name]} WHERE id = ?",
            (item_id,),
        )
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        return jsonify(
            {"error": "Нельзя удалить запись: она используется в расписании."}
        ), 409

    if cursor.rowcount == 0:
        return jsonify({"error": "Запись не найдена."}), 404

    return jsonify({"ok": True, "removed_lessons": removed_lessons})
