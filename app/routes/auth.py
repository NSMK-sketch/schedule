from flask import Blueprint, jsonify, request, session
from werkzeug.security import check_password_hash

from app.database import get_db


auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/login")
def login():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))

    if not username or not password.strip():
        return jsonify({"error": "Логин и пароль не могут быть пустыми."}), 400

    user = get_db().execute(
        "SELECT id, username, password_hash, role FROM users WHERE username = ?",
        (username,),
    ).fetchone()

    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Неверный логин или пароль."}), 401

    session.clear()
    session.update(
        user_id=user["id"],
        username=user["username"],
        role=user["role"],
    )

    return jsonify(
        {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
        }
    )


@auth_bp.post("/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@auth_bp.get("/me")
def me():
    if "user_id" not in session:
        return jsonify({"authenticated": False})

    return jsonify(
        {
            "authenticated": True,
            "id": session["user_id"],
            "username": session["username"],
            "role": session["role"],
        }
    )
