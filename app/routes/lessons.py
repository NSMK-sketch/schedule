from flask import Blueprint, jsonify, request, session, send_file
from io import BytesIO

from app.services.export_service import export_schedule_xlsx
from app.services.lesson_service import (
    copy_week,
    create_lesson,
    delete_lesson,
    list_lessons,
    update_lesson,
)


lessons_bp = Blueprint("lessons", __name__)


def require_login():
    if "user_id" not in session:
        return jsonify({"error": "Требуется авторизация."}), 401
    return None


def require_admin():
    error = require_login()
    if error:
        return error
    if session.get("role") != "admin":
        return jsonify({"error": "Недостаточно прав. Изменять расписание может только администратор."}), 403
    return None


@lessons_bp.get("/lessons")
def get_lessons():
    error = require_login()
    if error:
        return error

    return jsonify(
        list_lessons(
            request.args.get("week", type=int),
            request.args.get("group_id", type=int),
        )
    )


@lessons_bp.get("/export/schedule.xlsx")
def export_schedule():
    error = require_login()
    if error:
        return error

    raw_groups = (request.args.get("groups") or "").strip()
    group_ids = None
    if raw_groups:
        try:
            group_ids = [
                int(part.strip())
                for part in raw_groups.split(",")
                if part.strip()
            ]
        except ValueError:
            return jsonify({"error": "Некорректный список групп."}), 400
        if not group_ids:
            group_ids = None

    teacher_id = request.args.get("teacher_id", type=int)
    subject_id = request.args.get("subject_id", type=int)
    query = (request.args.get("q") or "").strip()

    try:
        payload, filename = export_schedule_xlsx(
            group_ids,
            teacher_id=teacher_id,
            subject_id=subject_id,
            query=query,
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return send_file(
        BytesIO(payload),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


@lessons_bp.post("/lessons/copy-week")
def copy_lessons_to_week():
    error = require_admin()
    if error:
        return error

    data = request.get_json(silent=True) or {}

    try:
        source_week = int(data.get("source_week"))
        target_week = int(data.get("target_week"))
    except (TypeError, ValueError):
        return jsonify({"error": "Укажите исходную и целевую недели."}), 400

    try:
        ok, message, count, removed = copy_week(source_week, target_week)
    except Exception:
        return jsonify({"error": "Не удалось скопировать расписание. Попробуйте ещё раз."}), 500

    if not ok:
        return jsonify({"error": message}), 409

    return jsonify({"ok": True, "copied": count, "removed": removed})


@lessons_bp.post("/lessons")
def add_lesson():
    error = require_admin()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    lesson_id, message = create_lesson(data)
    if message:
        status = 409 if message.startswith("Конфликт:") else 400
        return jsonify({"error": message}), status

    return jsonify({"id": lesson_id}), 201


@lessons_bp.put("/lessons/<int:lesson_id>")
def edit_lesson(lesson_id):
    error = require_admin()
    if error:
        return error

    ok, message = update_lesson(lesson_id, request.get_json(silent=True) or {})
    if not ok:
        status = 409 if message.startswith("Конфликт:") else 400
        if message == "Занятие не найдено.":
            status = 404
        return jsonify({"error": message}), status

    return jsonify({"ok": True})


@lessons_bp.delete("/lessons/<int:lesson_id>")
def remove_lesson(lesson_id):
    error = require_admin()
    if error:
        return error

    if not delete_lesson(lesson_id):
        return jsonify({"error": "Занятие не найдено."}), 404

    return jsonify({"ok": True})
