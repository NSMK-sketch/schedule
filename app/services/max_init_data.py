"""Validate mini-app launch data from MAX Bridge.

Algorithm: https://dev.max.ru/docs/webapps/validation

Field values are percent-decoded once, the same way parse_qsl and url.ParseQuery
do. A launch URL is reduced to its WebAppData value first. That parse already
decodes the parameter, so the inner text must not be decoded again when the
values are already plain. A second decode breaks the signature when a name or
photo URL still contains a percent-escape.
"""

import hmac
import hashlib
import logging
import time
from urllib.parse import parse_qsl


logger = logging.getLogger(__name__)

MAX_INIT_DATA_AGE = 3600


def extract_web_app_data(raw):
    """Return the inner WebAppData string.

    window.WebApp.initData is that string itself. A full launch URL keeps it
    in the hash as WebAppData=... parse_qsl decodes that parameter once.
    """
    text = str(raw or "").strip()
    if "WebAppData=" not in text:
        return text
    fragment = text.split("#", 1)[-1]
    values = [
        value
        for key, value in parse_qsl(fragment, keep_blank_values=True)
        if key == "WebAppData"
    ]
    if len(values) != 1:
        return ""
    return values[0]


def _literal_pairs(init_data):
    """Split key=value pairs without percent-decoding values."""
    pairs = []
    for part in init_data.split("&"):
        if not part:
            continue
        if "=" not in part:
            return None
        key, value = part.split("=", 1)
        if not key:
            return None
        pairs.append((key, value))
    return pairs


def _candidates(init_data):
    decoded = list(parse_qsl(init_data, keep_blank_values=True))
    found = []
    if decoded:
        found.append(decoded)
    literal = _literal_pairs(init_data)
    if literal and literal != decoded:
        found.append(literal)
    return found


def _auth_age(pairs, now):
    values = [value for key, value in pairs if key == "auth_date"]
    if len(values) != 1:
        return None
    try:
        auth_date = int(values[0])
    except (TypeError, ValueError):
        return None
    current = time.time() if now is None else now
    return int(current - auth_date), auth_date, current


def _signature_matches(pairs, token):
    received = [value for key, value in pairs if key == "hash"]
    if len(received) != 1:
        return False
    signed = sorted((key, value) for key, value in pairs if key != "hash")
    launch_params = "\n".join(f"{key}={value}" for key, value in signed)
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    signature = hmac.new(
        secret_key,
        launch_params.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    received_hash = received[0].lower()
    if len(signature) != len(received_hash):
        return False
    return hmac.compare_digest(signature, received_hash)


def _reject(reason, source, keys, age_seconds):
    logger.warning(
        "MAX initData rejected: reason=%s age_seconds=%s keys=%s length=%s",
        reason,
        "-" if age_seconds is None else age_seconds,
        list(keys),
        len(source or ""),
    )
    return None


def _inspect(pairs, token, now, max_age):
    """Return ('ok', params), ('reject', reason, keys, age), or ('retry', ...)."""
    keys = [key for key, _value in pairs]
    age_info = _auth_age(pairs, now)
    age = None if age_info is None else age_info[0]
    if len(keys) != len(set(keys)):
        return "retry", "повтор ключа", keys, age
    if keys.count("hash") != 1:
        return "retry", "нет hash", keys, age
    if not _signature_matches(pairs, token):
        return "retry", "подпись не сошлась", keys, age
    if age_info is None:
        return "reject", "нет auth_date", keys, None
    _age, auth_date, current = age_info
    if current - auth_date > max_age:
        return "reject", f"auth_date старше {int(max_age)} секунд", keys, age
    params = {key: value for key, value in pairs if key != "hash"}
    return "ok", params, keys, age


def validate_init_data(raw, bot_token, *, now=None, max_age=MAX_INIT_DATA_AGE):
    """Return decoded launch params when the signature is valid."""
    source = str(raw or "")
    init_data = extract_web_app_data(raw)
    token = str(bot_token or "")
    if not init_data or not token:
        reason = "пустая строка" if not init_data else "нет токена"
        return _reject(reason, source, [], None)

    candidates = _candidates(init_data)
    if not candidates:
        return _reject("пустая строка", source, [], None)

    first_failure = None
    for pairs in candidates:
        kind, reason, keys, age = _inspect(pairs, token, now, max_age)
        if kind == "ok":
            return reason
        if kind == "reject":
            return _reject(reason, source, keys, age)
        if first_failure is None:
            first_failure = (reason, keys, age)

    reason, keys, age = first_failure
    return _reject(reason, source, keys, age)
