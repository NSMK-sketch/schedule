import os
import secrets


BASE_DIR = os.path.dirname(os.path.dirname(__file__))

_WEAK_SECRET_KEYS = {
    "",
    "change-me",
    "change-me-in-production",
    "dev-secret-change-me",
    "secret",
}


def _load_local_env():
    path = os.path.join(BASE_DIR, ".env")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _flag(name, default="0"):
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


_load_local_env()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    DATABASE = os.getenv(
        "DATABASE", os.path.join(BASE_DIR, "instance", "schedule.db")
    )
    SEED_DEMO_DATA = _flag("SEED_DEMO_DATA", "0")
    MAX_API_BASE = os.getenv("MAX_API_BASE", "https://platform-api2.max.ru").rstrip("/")
    MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "").strip()
    MAX_WEBHOOK_URL = os.getenv("MAX_WEBHOOK_URL", "").strip()
    MAX_WEBHOOK_SECRET = os.getenv("MAX_WEBHOOK_SECRET", "").strip()
    MAX_MINIAPP_URL = os.getenv("MAX_MINIAPP_URL", "").strip()
    MAX_BOT_USERNAME = os.getenv("MAX_BOT_USERNAME", "").strip()


def ensure_secret_key(app):
    """Keep an explicit key, otherwise create one beside the database."""
    configured = str(app.config.get("SECRET_KEY") or "").strip()
    if configured not in _WEAK_SECRET_KEYS:
        app.config["SECRET_KEY"] = configured
        return

    directory = os.path.dirname(os.path.abspath(app.config["DATABASE"]))
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, "secret_key")
    existing = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            existing = handle.read().strip()
    if existing in _WEAK_SECRET_KEYS or len(existing) < 32:
        existing = secrets.token_hex(32)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(existing)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    app.config["SECRET_KEY"] = existing
