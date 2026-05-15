"""
Servidor web mínimo para que Render no mate el proceso.
Corre en un thread separado junto al bot de Telegram.
"""
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot activo")

    def log_message(self, format, *args):
        pass  # Silenciar logs del servidor HTTP


def keep_alive():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
