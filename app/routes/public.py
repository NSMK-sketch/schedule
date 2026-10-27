"""Public read-only API for the student schedule page."""

from flask import Blueprint, current_app, jsonify, request

from app.database import get_db
from app.services.lesson_service import list_lessons
from app.services.max_init_data import validate_init_data
from app.services.substitution_service import substitutions_for_group, substitutions_for_teacher


public_bp = Blueprint("public", __name__)


def _serialize_group(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "speciality": row["speciality"] or "",
        "course": row["course"] or 1,
    }


def _serialize_public_lesson(row):
    return {
        "id": row["id"],
        "week": row["week"],
        "weekday": row["weekday"],
        "period": row["period"],
        "lesson_type": row["lesson_type"] or "",
        "note": row["note"] or "",
        "subject_name": row["subject_name"],
        "subject_short": row["subject_short"],
        "subject_color": row["subject_color"] or row["teacher_color"] or "#2878d6",
        "teacher_name": row["teacher_name"],
        "teacher_short": row["teacher_short"],
        "teacher2_name": row["teacher2_name"],
        "teacher2_short": row["teacher2_short"],
        "classroom_name": row["classroom_name"],
        "classroom2_name": row["classroom2_name"],
        "group_id": row["group_id"],
        "group_name": row["group_name"],
    }


@public_bp.get("/groups")
def public_groups():
    db = get_db()
    rows = db.execute(
        """
        SELECT id, name, speciality, course
        FROM groups_ref
        ORDER BY course, name
        """
    ).fetchall()
    return jsonify([_serialize_group(row) for row in rows])


@public_bp.get("/teachers")
def public_teachers():
    db = get_db()
    rows = db.execute(
        """
        SELECT id, full_name, short_name
        FROM teachers
        ORDER BY full_name
        """
    ).fetchall()
    return jsonify(
        [
            {
                "id": row["id"],
                "full_name": row["full_name"],
                "short_name": row["short_name"] or "",
            }
            for row in rows
        ]
    )


@public_bp.get("/teacher-schedule")
def public_teacher_schedule():
    teacher_id = request.args.get("teacher_id", type=int)
    week = request.args.get("week", type=int)
    if not teacher_id:
        return jsonify({"error": "Укажите преподавателя."}), 400
    if week not in (1, 2, None):
        return jsonify({"error": "Неделя должна быть 1 или 2."}), 400

    changes = substitutions_for_teacher(teacher_id)
    if changes is None:
        return jsonify({"error": "Преподаватель не найден."}), 404

    lessons = []
    for item in list_lessons(week=week, teacher_id=teacher_id):
        payload = _serialize_public_lesson(item)
        secondary = (
            item["teacher2_id"] is not None
            and int(item["teacher2_id"]) == teacher_id
            and int(item["teacher_id"]) != teacher_id
        )
        if secondary and item["classroom2_name"]:
            payload["classroom_name"] = item["classroom2_name"]
            payload["classroom2_name"] = None
        lessons.append(payload)

    return jsonify(
        {
            "teacher": changes["teacher"],
            "week": week,
            "lessons": lessons,
            "substitutions": changes["current"],
        }
    )


@public_bp.get("/schedule")
def public_schedule():
    group_id = request.args.get("group_id", type=int)
    week = request.args.get("week", type=int)

    if not group_id:
        return jsonify({"error": "Укажите группу."}), 400
    if week not in (1, 2, None):
        return jsonify({"error": "Неделя должна быть 1 или 2."}), 400

    db = get_db()
    group = db.execute(
        """
        SELECT id, name, speciality, course
        FROM groups_ref
        WHERE id = ?
        """,
        (group_id,),
    ).fetchone()
    if group is None:
        return jsonify({"error": "Группа не найдена."}), 404

    lessons = list_lessons(week=week, group_id=group_id)
    changes = substitutions_for_group(group["id"], group["name"])
    return jsonify(
        {
            "group": _serialize_group(group),
            "week": week,
            "lessons": [_serialize_public_lesson(item) for item in lessons],
            "substitutions": changes["current"],
            "upcoming_substitutions": changes["upcoming"],
        }
    )


@public_bp.post("/max/session")
def max_session():
    payload = request.get_json(silent=True) or {}
    init_data = payload.get("init_data") or payload.get("initData") or ""
    if not isinstance(init_data, str) or not init_data.strip():
        return jsonify({"ok": False, "error": "Нет данных запуска MAX."}), 400

    token = current_app.config.get("MAX_BOT_TOKEN") or ""
    if not token:
        return jsonify({"ok": False, "error": "Бот MAX не настроен."}), 503

    parsed = validate_init_data(init_data, token)
    if parsed is None:
        return jsonify(
            {"ok": False, "error": "Не удалось подтвердить запуск из MAX."}
        ), 401

    return jsonify({"ok": True, "start_param": parsed.get("start_param") or ""})
