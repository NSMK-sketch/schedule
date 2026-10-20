from pathlib import Path

from flask import Flask, render_template, session, redirect, url_for

from app.config import Config
from app.database import init_db


BASE_DIR = Path(__file__).resolve().parent.parent


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

    init_db(app)

    @app.get("/")
    def index():
        return render_template("index.html")

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
    from app.routes.reference import reference_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    # lessons before reference so /api/lessons/<id> is not caught by /api/<name>/<id>
    app.register_blueprint(lessons_bp, url_prefix="/api")
    app.register_blueprint(reference_bp, url_prefix="/api")

    return app
