import socket

from app import create_app


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
    port = 5000
    lan = _lan_ip()
    print(f"Локально:     http://127.0.0.1:{port}/")
    print(f"В сети (LAN): http://{lan}:{port}/")
    app.run(host=host, port=port, debug=True)
