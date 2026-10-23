from flask import Blueprint, jsonify, request

from app.routes.lessons import require_admin
from app.services.draft_service import (
    create_draft,
    delete_draft,
    get_draft,
    list_drafts,
    publish_draft,
    rename_draft,
)
from app.services.lesson_service import (
    copy_week,
    create_lesson,
    delete_lesson,
    list_lessons,
    update_lesson,
)


drafts_bp = Blueprint("drafts", __name__)


def _missing_draft():
    return jsonify({"error": "Черновик не найден."}), 404


def _lesson_error(message):
    status = 409 if message.startswith("Конфликт:") else 400
    if message == "Занятие не найдено.":
        status = 404
    return jsonify({"error": message}), status


@drafts_bp.get("/drafts")
def get_drafts():
    error = require_admin()
    if error:
        return error
    return jsonify(list_drafts())


@drafts_bp.post("/drafts")
def add_draft():
    error = require_admin()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    source = str(data.get("source") or "current").strip()
    if source not in {"current", "empty"}:
        return jsonify({"error": "Источник черновика: current или empty."}), 400

    draft_id, message = create_draft(data.get("name"), copy_current=source == "current")
    if message:
        return jsonify({"error": message}), 400

    draft = get_draft(draft_id)
    return jsonify(draft), 201


@drafts_bp.put("/drafts/<int:draft_id>")
def edit_draft(draft_id):
    error = require_admin()
    if error:
        return error

    data = request.get_json(silent=True) or {}
    ok, message = rename_draft(draft_id, data.get("name"))
    if not ok:
        status = 404 if message == "Черновик не найден." else 400
        return jsonify({"error": message}), status
    return jsonify(get_draft(draft_id))


@drafts_bp.delete("/drafts/<int:draft_id>")
def remove_draft(draft_id):
    error = require_admin()
    if error:
        return error

    if not delete_draft(draft_id):
        return _missing_draft()
    return jsonify({"ok": True})


@drafts_bp.post("/drafts/<int:draft_id>/publish")
def publish(draft_id):
    error = require_admin()
    if error:
        return error

    try:
        ok, message, count = publish_draft(draft_id)
    except Exception:
        return jsonify({"error": "Не удалось заменить расписание. Попробуйте ещё раз."}), 500

    if not ok:
        return jsonify({"error": message}), 404
    return jsonify({"ok": True, "lessons": count})


@drafts_bp.get("/drafts/<int:draft_id>/lessons")
def get_draft_lessons(draft_id):
    error = require_admin()
    if error:
        return error
    if get_draft(draft_id) is None:
        return _missing_draft()

    return jsonify(
        list_lessons(
            request.args.get("week", type=int),
            request.args.get("group_id", type=int),
            draft_id=draft_id,
        )
    )


@drafts_bp.post("/drafts/<int:draft_id>/lessons")
def add_draft_lesson(draft_id):
    error = require_admin()
    if error:
        return error
    if get_draft(draft_id) is None:
        return _missing_draft()

    lesson_id, message = create_lesson(request.get_json(silent=True) or {}, draft_id=draft_id)
    if message:
        return _lesson_error(message)
    return jsonify({"id": lesson_id}), 201


@drafts_bp.put("/drafts/<int:draft_id>/lessons/<int:lesson_id>")
def edit_draft_lesson(draft_id, lesson_id):
    error = require_admin()
    if error:
        return error
    if get_draft(draft_id) is None:
        return _missing_draft()

    ok, message = update_lesson(
        lesson_id,
        request.get_json(silent=True) or {},
        draft_id=draft_id,
    )
    if not ok:
        return _lesson_error(message)
    return jsonify({"ok": True})


@drafts_bp.delete("/drafts/<int:draft_id>/lessons/<int:lesson_id>")
def remove_draft_lesson(draft_id, lesson_id):
    error = require_admin()
    if error:
        return error
    if get_draft(draft_id) is None:
        return _missing_draft()

    if not delete_lesson(lesson_id, draft_id=draft_id):
        return jsonify({"error": "Занятие не найдено."}), 404
    return jsonify({"ok": True})


@drafts_bp.post("/drafts/<int:draft_id>/lessons/copy-week")
def copy_draft_week(draft_id):
    error = require_admin()
    if error:
        return error
    if get_draft(draft_id) is None:
        return _missing_draft()

    data = request.get_json(silent=True) or {}
    try:
        source_week = int(data.get("source_week"))
        target_week = int(data.get("target_week"))
    except (TypeError, ValueError):
        return jsonify({"error": "Укажите исходную и целевую недели."}), 400

    try:
        ok, message, count, removed = copy_week(
            source_week,
            target_week,
            draft_id=draft_id,
        )
    except Exception:
        return jsonify({"error": "Не удалось скопировать расписание. Попробуйте ещё раз."}), 500

    if not ok:
        return jsonify({"error": message}), 409
    return jsonify({"ok": True, "copied": count, "removed": removed})
