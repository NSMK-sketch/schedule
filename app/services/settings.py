"""First-run installation and settings stored in the database."""

import logging
import os
import re
import secrets
import sqlite3
from urllib.parse import urlparse

from flask import current_app
from werkzeug.security import generate_password_hash

from app.database import get_db
from app.services.max_client import MaxApiError, MaxClient


logger = logging.getLogger(__name__)

_USERNAME = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
_UPDATE_TYPES = ["bot_started", "message_created"]

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


def _save_settings(db, values):
    for key, value in values.items():
        if not value:
            continue
        db.execute(
            """
            INSERT INTO app_settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


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

    url_error = _public_url_error(public_url)
    if url_error:
        return {"error": url_error}, 400
    if token and (any(char.isspace() for char in token) or not 10 <= len(token) <= 512):
        return {"error": "Похоже, токен бота скопирован не целиком."}, 400
    if public_url and not token and not current_app.config.get("MAX_BOT_TOKEN"):
        return {
            "error": "Адрес сайта имеет смысл вместе с токеном бота."
        }, 400

    webhook_url = ""
    miniapp_url = ""
    webhook_secret = ""
    bot_username = ""
    bot_user_id = None
    effective_token = token or str(current_app.config.get("MAX_BOT_TOKEN") or "").strip()

    if token:
        client = MaxClient(
            token,
            current_app.config.get("MAX_API_BASE") or "https://platform-api2.max.ru",
        )
        try:
            me = client.get_me()
        except MaxApiError:
            logger.warning("MAX rejected the token during setup")
            return {"error": "MAX не принял токен. Проверьте его в кабинете бота."}, 400
        except OSError:
            logger.exception("MAX was unreachable during setup")
            return {"error": "Не удалось связаться с MAX. Проверьте сеть."}, 400
        if not isinstance(me, dict) or not me.get("is_bot"):
            return {"error": "MAX вернул неожиданный ответ на токен."}, 400
        bot_username = str(me.get("username") or "").strip()
        bot_user_id = me.get("user_id")
        if public_url:
            webhook_url = public_url + "/max/webhook"
            miniapp_url = public_url
            webhook_secret = secrets.token_urlsafe(32)
            try:
                client.subscribe(webhook_url, webhook_secret, _UPDATE_TYPES)
            except MaxApiError:
                logger.warning("MAX webhook subscription failed during setup")
                return {
                    "error": (
                        "Токен верный, но вебхук не подписался. "
                        "Проверьте, что сайт открыт по HTTPS на порту 443, "
                        "или оставьте адрес пустым."
                    )
                }, 400
            except OSError:
                logger.exception("MAX webhook subscription failed during setup")
                return {"error": "Не удалось связаться с MAX. Проверьте сеть."}, 400

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
                "max_bot_token": token,
                "max_webhook_url": webhook_url,
                "max_webhook_secret": webhook_secret,
                "max_miniapp_url": miniapp_url,
                "max_bot_username": bot_username,
                "public_url": public_url,
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
        current_app.config["MAX_BOT_TOKEN"] = token
    if webhook_url:
        current_app.config["MAX_WEBHOOK_URL"] = webhook_url
        current_app.config["MAX_WEBHOOK_SECRET"] = webhook_secret
        current_app.config["MAX_MINIAPP_URL"] = miniapp_url
    if bot_username:
        current_app.config["MAX_BOT_USERNAME"] = bot_username
    if bot_user_id:
        current_app.config["MAX_BOT_USER_ID"] = bot_user_id
    if effective_token:
        from app.services.max_bot import start_bot

        start_bot(current_app._get_current_object())

    return {
        "ok": True,
        "id": user[0],
        "username": user[1],
        "role": user[2],
        "bot_connected": bool(effective_token),
    }, 200
