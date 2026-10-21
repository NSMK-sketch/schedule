"""Validate mini-app launch data from MAX Bridge.

Algorithm: https://dev.max.ru/docs/webapps/validation
"""

import hmac
import hashlib
import time
from urllib.parse import parse_qsl, unquote


MAX_INIT_DATA_AGE = 3600


def extract_web_app_data(raw):
    """Return the inner WebAppData string.

    window.WebApp.initData is that string itself. A full launch URL keeps it
    in the hash as WebAppData=...
    """
    text = str(raw or "").strip()
    if "WebAppData=" not in text:
        return text
    fragment = text.split("#", 1)[-1]
    values = [value for key, value in parse_qsl(fragment, keep_blank_values=True) if key == "WebAppData"]
    if len(values) != 1:
        return ""
    return values[0]


def validate_init_data(raw, bot_token, *, now=None, max_age=MAX_INIT_DATA_AGE):
    """Return decoded launch params when the signature is valid."""
    init_data = extract_web_app_data(raw)
    token = str(bot_token or "")
    if not init_data or not token:
        return None

    pairs = []
    for part in init_data.split("&"):
        if not part or "=" not in part:
            return None
        key, value = part.split("=", 1)
        if not key:
            return None
        pairs.append([key, value])

    keys = [key for key, _value in pairs]
    if len(keys) != len(set(keys)):
        return None
    if keys.count("hash") != 1:
        return None

    for pair in pairs:
        pair[1] = unquote(pair[1])

    original_hash = next(value for key, value in pairs if key == "hash")
    signed = sorted((key, value) for key, value in pairs if key != "hash")
    launch_params = "\n".join(f"{key}={value}" for key, value in signed)

    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    signature = hmac.new(
        secret_key,
        launch_params.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, original_hash.lower()):
        return None

    auth_values = [value for key, value in signed if key == "auth_date"]
    if len(auth_values) != 1:
        return None
    try:
        auth_date = int(auth_values[0])
    except ValueError:
        return None

    current = time.time() if now is None else now
    if current - auth_date > max_age:
        return None

    return {key: value for key, value in signed}
