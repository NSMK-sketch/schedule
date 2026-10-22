"""First-run installation and settings stored in the database."""

import logging
import os
import re
import secrets
import sqlite3
from urllib.parse import urlparse

from flask import current_app, session
from werkzeug.security import check_password_hash, generate_password_hash

from app.database import get_db
from app.services.max_client import MaxApiError, MaxClient


logger = logging.getLogger(__name__)

_USERNAME = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
_UPDATE_TYPES = ["bot_started", "message_created"]
_MAX_SETTING_KEYS = (
    "max_bot_token",
    "max_webhook_url",
    "max_webhook_secret",
    "max_miniapp_url",
    "max_bot_username",
    "public_url",
)

_SETTING_TO_CONFIG = {
    "max_bot_token": "MAX_BOT_TOKEN",
    "max_webhook_url": "MAX_WEBHOOK_URL",
    "max_webhook_secret": "MAX_WEBHOOK_SECRET",
    "max_miniapp_url": "MAX_MINIAPP_URL",
    "max_bot_username": "MAX_BOT_USERNAME",
}


def has_admin():
    row = get_db().execute(
        "SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"
    ).fetchone()
    return row is not None


def apply_stored_settings(app):
    """Fill empty config values from the database. Environment wins."""
    path = app.config.get("DATABASE")
    if not path or not os.path.isfile(path):
        return
    db = sqlite3.connect(path)
    try:
        rows = db.execute("SELECT key, value FROM app_settings").fetchall()
    except sqlite3.OperationalError:
        return
    finally:
        db.close()

    stored = {key: value for key, value in rows}
    for setting_key, config_key in _SETTING_TO_CONFIG.items():
        if str(app.config.get(config_key) or "").strip():
            continue
        value = str(stored.get(setting_key) or "").strip()
        if value:
            app.config[config_key] = value


def _save_settings(db, values, *, skip_empty=True):
    for key, value in values.items():
        value = "" if value is None else str(value)
        if skip_empty and not value:
            continue
        if not value:
            db.execute("DELETE FROM app_settings WHERE key = ?", (key,))
            continue
        db.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def _stored_settings():
    rows = get_db().execute("SELECT key, value FROM app_settings").fetchall()
    return {row["key"]: row["value"] for row in rows}


def _mask_token(token):
    token = str(token or "").strip()
    if not token:
        return ""
    if len(token) <= 8:
        return "•" * len(token)
    return f"{'•' * 8}{token[-4:]}"


def _verify_admin_password(password):
    if session.get("role") != "admin" or "user_id" not in session:
        return None, ({"error": "Нужны права администратора."}, 403)
    password = str(password or "")
    if not password:
        return None, ({"error": "Введите текущий пароль администратора."}, 400)
    user = get_db().execute(
        "SELECT id, username, password_hash, role FROM users WHERE id = ?",
        (session["user_id"],),
    ).fetchone()
    if (
        user is None
        or user["role"] != "admin"
        or not check_password_hash(user["password_hash"], password)
    ):
        return None, ({"error": "Неверный пароль администратора."}, 401)
    return user, None


def _configure_max(token, public_url, *, keep_secret=""):
    """Validate token/url and return settings dict or (error, status)."""
    url_error = _public_url_error(public_url)
    if url_error:
        return None, ({"error": url_error}, 400)
    if token and (any(char.isspace() for char in token) or not 10 <= len(token) <= 512):
        return None, ({"error": "Похоже, токен бота скопирован не целиком."}, 400)
    if public_url and not token:
        return None, ({"error": "Адрес сайта имеет смысл вместе с токеном бота."}, 400)

    webhook_url = ""
    miniapp_url = ""
    webhook_secret = ""
    bot_username = ""
    bot_user_id = None

    if token:
        client = MaxClient(
            token,
            current_app.config.get("MAX_API_BASE") or "https://platform-api2.max.ru",
        )
        try:
            me = client.get_me()
        except MaxApiError:
            logger.warning("MAX rejected the token")
            return None, ({"error": "MAX не принял токен. Проверьте его в кабинете бота."}, 400)
        except OSError:
            logger.exception("MAX was unreachable")
            return None, ({"error": "Не удалось связаться с MAX. Проверьте сеть."}, 400)
        if not isinstance(me, dict) or not me.get("is_bot"):
            return None, ({"error": "MAX вернул неожиданный ответ на токен."}, 400)
        bot_username = str(me.get("username") or "").strip()
        bot_user_id = me.get("user_id")
        if public_url:
            webhook_url = public_url + "/max/webhook"
            miniapp_url = public_url
            webhook_secret = keep_secret or secrets.token_urlsafe(32)
            try:
                client.subscribe(webhook_url, webhook_secret, _UPDATE_TYPES)
            except MaxApiError:
                logger.warning("MAX webhook subscription failed")
                return None, (
                    {
                        "error": (
                            "Токен верный, но вебхук не подписался. "
                            "Проверьте, что сайт открыт по HTTPS на порту 443, "
                            "или оставьте адрес пустым."
                        )
                    },
                    400,
                )
            except OSError:
                logger.exception("MAX webhook subscription failed")
                return None, ({"error": "Не удалось связаться с MAX. Проверьте сеть."}, 400)

    return {
        "max_bot_token": token,
        "max_webhook_url": webhook_url,
        "max_webhook_secret": webhook_secret,
        "max_miniapp_url": miniapp_url,
        "max_bot_username": bot_username,
        "public_url": public_url,
        "bot_user_id": bot_user_id,
    }, None


def _apply_max_config(values):
    token = str(values.get("max_bot_token") or "").strip()
    current_app.config["MAX_BOT_TOKEN"] = token
    current_app.config["MAX_WEBHOOK_URL"] = str(values.get("max_webhook_url") or "")
    current_app.config["MAX_WEBHOOK_SECRET"] = str(values.get("max_webhook_secret") or "")
    current_app.config["MAX_MINIAPP_URL"] = str(values.get("max_miniapp_url") or "")
    current_app.config["MAX_BOT_USERNAME"] = str(values.get("max_bot_username") or "")
    bot_user_id = values.get("bot_user_id")
    if bot_user_id:
        current_app.config["MAX_BOT_USER_ID"] = bot_user_id
    if not token:
        return
    from app.services.max_bot import refresh_webhook, start_bot

    app = current_app._get_current_object()
    if current_app.config.get("MAX_WEBHOOK_URL"):
        try:
            refresh_webhook(app)
            return
        except Exception:
            logger.exception("Could not refresh MAX webhook after settings change")
    start_bot(app)


def _public_url_error(public_url):
    if not public_url:
        return None
    parsed = urlparse(public_url)
    if parsed.scheme == "http":
        return (
            "Для вебхука MAX нужен адрес https://. "
            "Оставьте поле пустым, если публичного адреса ещё нет."
        )
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
    ):
        return "Адрес сайта укажите без пути, например https://example.com."
    return None


def perform_install(data):
    """Create the first administrator. Returns (payload, status_code)."""
    username = str(data.get("username", "")).strip()
    password = str(data.get("password", ""))
    confirm = str(data.get("password_confirm", ""))
    token = str(data.get("max_bot_token", "")).strip()
    public_url = str(data.get("public_url", "")).strip().rstrip("/")

    if not _USERNAME.match(username):
        return {
            "error": "Логин: 3–32 символа, латиница, цифры, точка, _ или -."
        }, 400
    if password != confirm:
        return {"error": "Пароли не совпадают."}, 400
    if len(password) < 8 or len(password) > 128:
        return {"error": "Пароль должен быть от 8 до 128 символов."}, 400
    if password.lower() == username.lower():
        return {"error": "Пароль не должен совпадать с логином."}, 400

    effective_token = token or str(current_app.config.get("MAX_BOT_TOKEN") or "").strip()
    if public_url and not token and not effective_token:
        return {
            "error": "Адрес сайта имеет смысл вместе с токеном бота."
        }, 400

    max_values = {
        "max_bot_token": token,
        "max_webhook_url": "",
        "max_webhook_secret": "",
        "max_miniapp_url": "",
        "max_bot_username": "",
        "public_url": public_url,
        "bot_user_id": None,
    }
    if token:
        configured, error = _configure_max(token, public_url)
        if error:
            return error
        max_values = configured

    connection = sqlite3.connect(current_app.config["DATABASE"], timeout=5)
    try:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute(
            "SELECT 1 FROM users WHERE role = 'admin' LIMIT 1"
        ).fetchone():
            connection.rollback()
            return {"error": "Установка уже выполнена."}, 409
        connection.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
            (username, generate_password_hash(password)),
        )
        user = connection.execute(
            "SELECT id, username, role FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        _save_settings(
            connection,
            {
                key: max_values.get(key, "")
                for key in _MAX_SETTING_KEYS
            },
        )
        connection.commit()
    except sqlite3.Error:
        connection.rollback()
        logger.exception("Setup could not be saved")
        return {"error": "Не удалось сохранить установку."}, 500
    finally:
        connection.close()

    if token:
        _apply_max_config(max_values)
    elif effective_token:
        from app.services.max_bot import start_bot

        start_bot(current_app._get_current_object())

    return {
        "ok": True,
        "id": user[0],
        "username": user[1],
        "role": user[2],
        "bot_connected": bool(effective_token or token),
    }, 200


def get_max_settings():
    """Public view of MAX settings for the admin dialog."""
    stored = _stored_settings()
    token = (
        str(current_app.config.get("MAX_BOT_TOKEN") or "").strip()
        or str(stored.get("max_bot_token") or "").strip()
    )
    public_url = (
        str(stored.get("public_url") or "").strip()
        or str(current_app.config.get("MAX_MINIAPP_URL") or "").strip()
    )
    username = (
        str(current_app.config.get("MAX_BOT_USERNAME") or "").strip()
        or str(stored.get("max_bot_username") or "").strip()
    )
    return {
        "token_set": bool(token),
        "token_masked": _mask_token(token),
        "public_url": public_url,
        "bot_username": username,
        "webhook_url": str(
            current_app.config.get("MAX_WEBHOOK_URL")
            or stored.get("max_webhook_url")
            or ""
        ).strip(),
        "env_token_locked": bool(os.getenv("MAX_BOT_TOKEN", "").strip()),
    }


def update_max_settings(data):
    """Update MAX token/URL after verifying the admin password."""
    _, auth_error = _verify_admin_password(data.get("password"))
    if auth_error:
        return auth_error

    stored = _stored_settings()
    current_token = (
        str(current_app.config.get("MAX_BOT_TOKEN") or "").strip()
        or str(stored.get("max_bot_token") or "").strip()
    )
    token = str(data.get("max_bot_token", "")).strip()
    if not token or set(token) <= {"•", "*"} or token == _mask_token(current_token):
        token = current_token
    public_url = str(data.get("public_url", "")).strip().rstrip("/")

    if os.getenv("MAX_BOT_TOKEN", "").strip() and token != current_token:
        return {
            "error": "Токен задан переменной окружения MAX_BOT_TOKEN и меняется только там."
        }, 400

    keep_secret = ""
    if (
        public_url
        and token == current_token
        and public_url
        == str(stored.get("public_url") or current_app.config.get("MAX_MINIAPP_URL") or "").strip().rstrip("/")
    ):
        keep_secret = str(
            current_app.config.get("MAX_WEBHOOK_SECRET")
            or stored.get("max_webhook_secret")
            or ""
        ).strip()

    configured, error = _configure_max(token, public_url, keep_secret=keep_secret)
    if error:
        return error

    db = get_db()
    try:
        _save_settings(
            db,
            {key: configured.get(key, "") for key in _MAX_SETTING_KEYS},
            skip_empty=False,
        )
        db.commit()
    except sqlite3.Error:
        db.rollback()
        logger.exception("MAX settings could not be saved")
        return {"error": "Не удалось сохранить настройки."}, 500

    _apply_max_config(configured)
    return {
        "ok": True,
        "bot_connected": bool(token),
        "settings": get_max_settings(),
    }, 200


def reset_install(data):
    """Remove admin accounts so /admin shows the setup page again."""
    _, auth_error = _verify_admin_password(data.get("password"))
    if auth_error:
        return auth_error

    confirm = str(data.get("confirm", "")).strip().lower()
    if confirm not in {"сбросить", "reset", "yes"}:
        return {
            "error": 'Для подтверждения введите слово «сбросить».'
        }, 400

    db = get_db()
    try:
        db.execute("DELETE FROM users WHERE role = 'admin'")
        for key in _MAX_SETTING_KEYS:
            db.execute("DELETE FROM app_settings WHERE key = ?", (key,))
        db.commit()
    except sqlite3.Error:
        db.rollback()
        logger.exception("Install reset failed")
        return {"error": "Не удалось сбросить установку."}, 500

    for config_key in _SETTING_TO_CONFIG.values():
        if os.getenv(config_key, "").strip():
            continue
        current_app.config[config_key] = ""

    session.clear()
    return {"ok": True, "redirect": "/admin"}, 200
