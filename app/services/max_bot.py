"""MAX bot updates: greet the student and open the schedule mini-app."""

import os
import threading
import time

from app.services.max_client import MaxApiError, MaxClient

WELCOME_TEXT = (
    "Расписание НСМК.\n"
    "Нажмите кнопку, выберите свою группу — откроется расписание на учебные недели."
)
_COMMANDS = {"start", "старт", "расписание", "начать"}
_UPDATE_TYPES = ["bot_started", "message_created"]
_polling_started = False
_last_reply_at = {}
_REPLY_DEDUPE_SECONDS = 10


def resolve_web_app(miniapp_url, bot_username):
    """web_app is a bot username or a max.ru link, not the site URL.

    The HTTPS address of the mini-app is saved in the bot settings.
    """
    value = str(miniapp_url or "").strip()
    if value.startswith("https://max.ru/") or value.startswith("http://max.ru/"):
        return value
    if value and "://" not in value and " " not in value:
        return value
    return str(bot_username or "").strip()


def schedule_attachments(web_app, contact_id=None):
    button = {
        "type": "open_app",
        "text": "Открыть расписание",
        "web_app": web_app,
    }
    # contact_id is the bot's own user id. The client uses it to open that bot's mini-app.
    if contact_id not in (None, ""):
        button["contact_id"] = int(contact_id)
    return [
        {
            "type": "inline_keyboard",
            "payload": {"buttons": [[button]]},
        }
    ]


def _command(text):
    cleaned = " ".join(str(text or "").strip().lower().split())
    if cleaned.startswith("/"):
        cleaned = cleaned[1:]
    return cleaned.split("@", 1)[0].strip()


def _message_text(update):
    message = update.get("message") or {}
    body = message.get("body") or {}
    if isinstance(body, dict) and body.get("text"):
        return body.get("text") or ""
    return message.get("text") or ""


def _sender_is_bot(update):
    message = update.get("message") or {}
    sender = message.get("sender") or {}
    return bool(sender.get("is_bot"))


def _user_id(update):
    user = update.get("user") or {}
    if isinstance(user, dict) and user.get("user_id"):
        return user.get("user_id")
    message = update.get("message") or {}
    sender = message.get("sender") or {}
    if sender.get("user_id"):
        return sender.get("user_id")
    recipient = message.get("recipient") or {}
    return recipient.get("user_id")


def _chat_id(update):
    if update.get("chat_id"):
        return update.get("chat_id")
    message = update.get("message") or {}
    recipient = message.get("recipient") or {}
    return recipient.get("chat_id")


def schedule_requested(update):
    if not isinstance(update, dict):
        return False
    kind = update.get("update_type")
    if kind == "bot_started":
        return True
    if kind != "message_created" or _sender_is_bot(update):
        return False
    return _command(_message_text(update)) in _COMMANDS


def build_reply(update, miniapp_url="", bot_username="", bot_user_id=None):
    """Return a send_message payload, or None when the update needs no reply."""
    if not schedule_requested(update):
        return None

    web_app = resolve_web_app(miniapp_url, bot_username)
    user_id = _user_id(update)
    chat_id = _chat_id(update)
    if not web_app or (user_id is None and chat_id is None):
        return None
    return {
        "user_id": user_id,
        "chat_id": chat_id,
        "text": WELCOME_TEXT,
        "attachments": schedule_attachments(web_app, bot_user_id),
    }


def remember_bot(app, client):
    username = str(app.config.get("MAX_BOT_USERNAME") or "").strip()
    user_id = app.config.get("MAX_BOT_USER_ID")
    if username and user_id:
        return username, user_id
    me = client.get_me() or {}
    username = username or str(me.get("username") or "").strip()
    user_id = user_id or me.get("user_id")
    if username:
        app.config["MAX_BOT_USERNAME"] = username
    if user_id:
        app.config["MAX_BOT_USER_ID"] = user_id
    return username, user_id


def _reply_key(reply):
    return reply.get("chat_id") or reply.get("user_id")


def handle_update(update, client, miniapp_url="", bot_username="", bot_user_id=None):
    reply = build_reply(update, miniapp_url, bot_username, bot_user_id)
    if reply is None:
        return False
    key = _reply_key(reply)
    now = time.monotonic()
    previous = _last_reply_at.get(key)
    if previous is not None and now - previous < _REPLY_DEDUPE_SECONDS:
        return False
    client.send_message(
        user_id=reply["user_id"],
        chat_id=reply["chat_id"],
        text=reply["text"],
        attachments=reply["attachments"],
    )
    if key is not None:
        _last_reply_at[key] = now
    return True


def _should_start(app):
    if app.config.get("TESTING"):
        return False
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return False
    return bool(app.config.get("MAX_BOT_TOKEN"))


def _poll_loop(app, client):
    marker = None
    miniapp_url = app.config.get("MAX_MINIAPP_URL") or ""
    bot_username = ""
    bot_user_id = None
    while True:
        try:
            if not bot_username or not bot_user_id:
                bot_username, bot_user_id = remember_bot(app, client)
            data = client.get_updates(marker=marker, timeout=30, types=_UPDATE_TYPES)
            if data.get("marker") is not None:
                marker = data.get("marker")
            for update in data.get("updates") or []:
                try:
                    handle_update(
                        update, client, miniapp_url, bot_username, bot_user_id
                    )
                except MaxApiError as exc:
                    app.logger.error("MAX update was not delivered: %s", exc.detail or exc)
                except OSError:
                    app.logger.exception("MAX update was not delivered")
        except (MaxApiError, OSError, ValueError):
            app.logger.exception("MAX long polling failed")
            time.sleep(3)


def refresh_webhook(app):
    """Re-subscribe the webhook with the current token and secret."""
    token = str(app.config.get("MAX_BOT_TOKEN") or "").strip()
    webhook_url = str(app.config.get("MAX_WEBHOOK_URL") or "").strip()
    if not token or not webhook_url:
        return False
    client = MaxClient(
        token,
        app.config.get("MAX_API_BASE") or "https://platform-api2.max.ru",
    )
    client.subscribe(
        webhook_url,
        app.config.get("MAX_WEBHOOK_SECRET") or "",
        _UPDATE_TYPES,
    )
    remember_bot(app, client)
    app.logger.info("MAX webhook subscription updated")
    return True


def start_bot(app):
    """Subscribe to a webhook, or poll while developing. Never both."""
    global _polling_started
    if not _should_start(app):
        return
    if _polling_started:
        return

    client = MaxClient(
        app.config["MAX_BOT_TOKEN"],
        app.config.get("MAX_API_BASE") or "https://platform-api2.max.ru",
    )
    webhook_url = (app.config.get("MAX_WEBHOOK_URL") or "").strip()
    if webhook_url:
        try:
            client.subscribe(
                webhook_url,
                app.config.get("MAX_WEBHOOK_SECRET") or "",
                _UPDATE_TYPES,
            )
            remember_bot(app, client)
            app.logger.info("MAX webhook subscription updated")
        except (MaxApiError, OSError):
            app.logger.exception("MAX webhook subscription failed")
        _polling_started = True
        return

    thread = threading.Thread(
        target=_poll_loop,
        args=(app, client),
        name="max-long-polling",
        daemon=True,
    )
    thread.start()
    _polling_started = True
    print("MAX: бот слушает сообщения (long polling)", flush=True)
    app.logger.info("MAX long polling started")
