import os


BASE_DIR = os.path.dirname(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    DATABASE = os.path.join(BASE_DIR, "instance", "schedule.db")
    # Seed groups/teachers/subjects/lessons on first launch when DB is empty
    SEED_DEMO_DATA = os.getenv("SEED_DEMO_DATA", "1") not in ("0", "false", "False")
