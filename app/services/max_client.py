"""HTTP client for the MAX bot API.

Token is sent only in the Authorization header. Query tokens are not supported.
https://dev.max.ru/docs-api
"""

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


_SSL_CONTEXT = None


def max_ssl_context():
    """Trust the public CAs plus the Russian Trusted CA used by MAX."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is not None:
        return _SSL_CONTEXT
    context = ssl.create_default_context()
    cert_dir = Path(__file__).resolve().parent.parent / "certs"
    for path in sorted(cert_dir.glob("*.cer")):
        context.load_verify_locations(cafile=str(path))
    _SSL_CONTEXT = context
    return context


class MaxApiError(Exception):
    def __init__(self, status, detail=""):
        super().__init__(f"MAX API {status}")
        self.status = status
        self.detail = detail


class MaxClient:
    def __init__(self, token, base_url="https://platform-api2.max.ru"):
        self.token = token
        self.base_url = base_url.rstrip("/")

    def request(self, method, path, params=None, json_body=None, timeout=20):
        query = ""
        if params:
            cleaned = {
                key: value
                for key, value in params.items()
                if value is not None
            }
            if cleaned:
                query = "?" + urllib.parse.urlencode(cleaned)
        url = f"{self.base_url}{path}{query}"
        data = None
        headers = {"Authorization": self.token}
        if json_body is not None:
            data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(
                req,
                timeout=timeout,
                context=max_ssl_context(),
            ) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise MaxApiError(exc.code, detail) from None
        if not raw:
            return {}
        return json.loads(raw)

    def get_me(self):
        return self.request("GET", "/me", timeout=20)

    def get_updates(self, marker=None, timeout=30, types=None):
        params = {"limit": 100, "timeout": timeout}
        if marker is not None:
            params["marker"] = marker
        if types:
            params["types"] = ",".join(types)
        return self.request(
            "GET",
            "/updates",
            params=params,
            timeout=timeout + 15,
        )

    def send_message(
        self,
        *,
        user_id=None,
        chat_id=None,
        text="",
        attachments=None,
        text_format=None,
    ):
        params = {}
        if user_id is not None:
            params["user_id"] = user_id
        elif chat_id is not None:
            params["chat_id"] = chat_id
        else:
            raise ValueError("user_id or chat_id is required")
        body = {"text": text}
        if text_format:
            body["format"] = text_format
        if attachments:
            body["attachments"] = attachments
        return self.request("POST", "/messages", params=params, json_body=body, timeout=20)

    def subscribe(self, url, secret, update_types=None):
        body = {
            "url": url,
            "update_types": update_types or ["message_created", "bot_started"],
        }
        if secret:
            body["secret"] = secret
        return self.request("POST", "/subscriptions", json_body=body, timeout=20)
