import os

from app import create_app
from app.services.max_bot import start_bot


app = create_app()

# One process: SQLite and the MAX poller must not be multiplied by workers.
if os.environ.get("SCHEDULE_START_BOT", "1").strip().lower() not in {"0", "false", "no", "off"}:
    start_bot(app)
