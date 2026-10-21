import os
import socket

from app import create_app
from app.services.max_bot import start_bot


app = create_app()


def _lan_ip():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except OSError:
        return "ВАШ_IP"


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.getenv("PORT", "5050"))
    debug = os.getenv("FLASK_DEBUG", "").strip().lower() in {"1", "true", "yes", "on"}
    # The reloader parent must not poll: only the serving process may call MAX.
    serving = (not debug) or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
    if serving:
        start_bot(app)
    lan = _lan_ip()
    print(f"Локально:     http://127.0.0.1:{port}/")
    print(f"В сети (LAN): http://{lan}:{port}/")
    app.run(host=host, port=port, debug=debug)
