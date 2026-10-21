from flask import Blueprint, jsonify, request, session

from app.services.settings import has_admin, perform_install


setup_bp = Blueprint("setup", __name__)


@setup_bp.get("/status")
def status():
    return jsonify({"installed": has_admin()})


@setup_bp.post("")
def setup():
    if has_admin():
        return jsonify({"error": "Установка уже выполнена."}), 409

    payload, code = perform_install(request.get_json(silent=True) or {})
    if code == 200:
        session.clear()
        session.update(
            user_id=payload["id"],
            username=payload["username"],
            role=payload["role"],
        )
    return jsonify(payload), code
