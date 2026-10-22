from flask import Blueprint, jsonify, request, session

from app.services.settings import get_max_settings, reset_install, update_max_settings


settings_bp = Blueprint("settings", __name__)


def _require_admin():
    if "user_id" not in session:
        return jsonify({"error": "Требуется авторизация."}), 401
    if session.get("role") != "admin":
        return jsonify({"error": "Недостаточно прав."}), 403
    return None


@settings_bp.get("/max")
def max_settings():
    denied = _require_admin()
    if denied:
        return denied
    return jsonify(get_max_settings())


@settings_bp.put("/max")
def save_max_settings():
    denied = _require_admin()
    if denied:
        return denied
    payload, code = update_max_settings(request.get_json(silent=True) or {})
    return jsonify(payload), code


@settings_bp.post("/reset-install")
def reset_install_route():
    denied = _require_admin()
    if denied:
        return denied
    payload, code = reset_install(request.get_json(silent=True) or {})
    return jsonify(payload), code
