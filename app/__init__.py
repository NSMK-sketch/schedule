import os
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, session, url_for

from app.config import Config, ensure_secret_key
from app.database import init_db
from app.services.settings import apply_stored_settings, has_admin


BASE_DIR = Path(__file__).resolve().parent.parent


def _enabled(name):
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def create_app(test_config=None):
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
        static_url_path="/static",
    )
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    ensure_secret_key(app)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = _enabled("COOKIE_SECURE")
    app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024

    if _enabled("TRUST_PROXY"):
        from werkzeug.middleware.proxy_fix import ProxyFix

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    init_db(app)
    apply_stored_settings(app)

    @app.after_request
    def _security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    @app.get("/")
    def index():
        return render_template("student.html")

    @app.get("/student")
    def student_legacy():
        """Old mini-app path from MAX; keep working until the bot URL is updated."""
        target = "/"
        if request.query_string:
            target = f"/?{request.query_string.decode('utf-8', 'ignore')}"
        return redirect(target, code=301)

    @app.get("/admin")
    def admin():
        if not has_admin():
            return render_template("setup.html")
        return render_template("index.html")

    @app.get("/print/all")
    def print_all():
        if "user_id" not in session:
            return redirect(url_for("admin"))
        return render_template("print.html", mode="all", group_id=None)

    @app.get("/print/<int:group_id>")
    def print_group(group_id):
        if "user_id" not in session:
            return redirect(url_for("admin"))
        return render_template("print.html", mode="group", group_id=group_id)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/admin/changes")
    def changes_admin():
        if session.get("role") != "admin":
            return redirect(url_for("admin"))
        from app.services.substitution_service import get_notify_chat

        return render_template(
            "changes.html",
            notify_chat=get_notify_chat().get("chat_id") or "",
        )

    @app.get("/changes/<int:sheet_id>")
    def changes_public(sheet_id):
        from app.services.substitution_service import published_sheet

        sheet = published_sheet(sheet_id)
        if sheet is None:
            abort(404)
        return render_template("changes_public.html", sheet=sheet)

    from app.routes.auth import auth_bp
    from app.routes.drafts import drafts_bp
    from app.routes.lessons import lessons_bp
    from app.routes.max_webhook import max_webhook_bp
    from app.routes.public import public_bp
    from app.routes.reference import reference_bp
    from app.routes.settings import settings_bp
    from app.routes.setup import setup_bp
    from app.routes.substitutions import substitutions_bp

    app.register_blueprint(setup_bp, url_prefix="/api/setup")
    app.register_blueprint(settings_bp, url_prefix="/api/settings")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(public_bp, url_prefix="/api/public")
    app.register_blueprint(max_webhook_bp, url_prefix="/max")
    # Static API prefixes before reference so /api/<name>/<id> does not swallow them.
    app.register_blueprint(lessons_bp, url_prefix="/api")
    app.register_blueprint(drafts_bp, url_prefix="/api")
    app.register_blueprint(substitutions_bp, url_prefix="/api")
    app.register_blueprint(reference_bp, url_prefix="/api")

    return app
