from flask import Blueprint, jsonify, request

from app.routes.lessons import require_admin
from app.services.substitution_service import (
    create_sheet,
    delete_sheet,
    get_notify_chat,
    get_sheet,
    list_sheets,
    publish_sheet,
    resend_notice,
    set_notify_chat,
    unpublish_sheet,
    update_sheet,
)


substitutions_bp = Blueprint("substitutions", __name__)


def _error(message, status=400):
    if message == "Лист замены не найден.":
        status = 404
    return jsonify({"error": message}), status


@substitutions_bp.get("/substitutions")
def get_substitutions():
    error = require_admin()
    if error:
        return error
    return jsonify(list_sheets())


@substitutions_bp.post("/substitutions")
def add_substitution():
    error = require_admin()
    if error:
        return error
    sheet, message = create_sheet(request.get_json(silent=True) or {})
    if message:
        return _error(message)
    return jsonify(sheet), 201


@substitutions_bp.get("/substitutions/notify-chat")
def read_notify_chat():
    error = require_admin()
    if error:
        return error
    return jsonify(get_notify_chat())


@substitutions_bp.put("/substitutions/notify-chat")
def write_notify_chat():
    error = require_admin()
    if error:
        return error
    data = request.get_json(silent=True) or {}
    saved, message = set_notify_chat(data.get("chat_id"))
    if message:
        return _error(message)
    return jsonify(saved)


@substitutions_bp.get("/substitutions/<int:sheet_id>")
def read_substitution(sheet_id):
    error = require_admin()
    if error:
        return error
    sheet = get_sheet(sheet_id)
    if sheet is None:
        return _error("Лист замены не найден.")
    return jsonify(sheet)


@substitutions_bp.put("/substitutions/<int:sheet_id>")
def edit_substitution(sheet_id):
    error = require_admin()
    if error:
        return error
    sheet, message = update_sheet(sheet_id, request.get_json(silent=True) or {})
    if message:
        return _error(message)
    return jsonify(sheet)


@substitutions_bp.delete("/substitutions/<int:sheet_id>")
def remove_substitution(sheet_id):
    error = require_admin()
    if error:
        return error
    ok, message = delete_sheet(sheet_id)
    if not ok:
        return _error(message)
    return jsonify({"ok": True})


@substitutions_bp.post("/substitutions/<int:sheet_id>/publish")
def publish_substitution(sheet_id):
    error = require_admin()
    if error:
        return error
    result, message = publish_sheet(sheet_id)
    if message:
        return _error(message)
    return jsonify(result)


@substitutions_bp.post("/substitutions/<int:sheet_id>/unpublish")
def unpublish_substitution(sheet_id):
    error = require_admin()
    if error:
        return error
    sheet, message = unpublish_sheet(sheet_id)
    if message:
        return _error(message)
    return jsonify(sheet)


@substitutions_bp.post("/substitutions/<int:sheet_id>/notify")
def notify_substitution(sheet_id):
    error = require_admin()
    if error:
        return error
    result, message = resend_notice(sheet_id)
    if message:
        return _error(message)
    return jsonify(result)
