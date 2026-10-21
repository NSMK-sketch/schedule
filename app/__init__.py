import os
from pathlib import Path

from flask import Flask, redirect, render_template, session, url_for

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
        if not has_admin():
            return render_template("setup.html")
        return render_template("index.html")

    @app.get("/student")
    def student():
        return render_template("student.html")

    @app.get("/print/all")
    def print_all():
        if "user_id" not in session:
            return redirect(url_for("index"))
        return render_template("print.html", mode="all", group_id=None)

    @app.get("/print/<int:group_id>")
    def print_group(group_id):
        if "user_id" not in session:
            return redirect(url_for("index"))
        return render_template("print.html", mode="group", group_id=group_id)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    from app.routes.auth import auth_bp
    from app.routes.lessons import lessons_bp
    from app.routes.max_webhook import max_webhook_bp
    from app.routes.public import public_bp
    from app.routes.reference import reference_bp
    from app.routes.setup import setup_bp

    app.register_blueprint(setup_bp, url_prefix="/api/setup")
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(public_bp, url_prefix="/api/public")
    app.register_blueprint(max_webhook_bp, url_prefix="/max")
    # lessons before reference so /api/lessons/<id> is not caught by /api/<name>/<id>
    app.register_blueprint(lessons_bp, url_prefix="/api")
    app.register_blueprint(reference_bp, url_prefix="/api")

    return app
