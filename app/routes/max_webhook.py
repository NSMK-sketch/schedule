"""Webhook endpoint for MAX bot updates."""

import hmac
import logging

from flask import Blueprint, current_app, jsonify, request

from app.services.max_bot import (
    build_reply,
    remember_bot,
    resolve_web_app,
    schedule_requested,
)
from app.services.max_client import MaxApiError, MaxClient


logger = logging.getLogger(__name__)

max_webhook_bp = Blueprint("max_webhook", __name__)


def _secret_matches(expected, provided):
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))


@max_webhook_bp.post("/webhook")
def max_webhook():
    expected = current_app.config.get("MAX_WEBHOOK_SECRET") or ""
    provided = request.headers.get("X-Max-Bot-Api-Secret", "")
    if not _secret_matches(expected, provided):
        return jsonify({"ok": False}), 403

    update = request.get_json(silent=True) or {}
    if not schedule_requested(update):
        return jsonify({"ok": True})

    token = current_app.config.get("MAX_BOT_TOKEN") or ""
    if not token:
        return jsonify({"ok": True})

    miniapp_url = current_app.config.get("MAX_MINIAPP_URL") or ""
    username = current_app.config.get("MAX_BOT_USERNAME") or ""
    bot_user_id = current_app.config.get("MAX_BOT_USER_ID")
    client = MaxClient(
        token,
        current_app.config.get("MAX_API_BASE") or "https://platform-api2.max.ru",
    )
    if not resolve_web_app(miniapp_url, username) or not bot_user_id:
        try:
            username, bot_user_id = remember_bot(current_app, client)
        except (MaxApiError, OSError):
            logger.exception("MAX bot profile was not loaded")
            return jsonify({"ok": True})

    reply = build_reply(update, miniapp_url, username, bot_user_id)
    if reply:
        try:
            client.send_message(
                user_id=reply["user_id"],
                chat_id=reply["chat_id"],
                text=reply["text"],
                attachments=reply["attachments"],
            )
        except (MaxApiError, OSError):
            logger.exception("MAX webhook reply failed")
    return jsonify({"ok": True})
