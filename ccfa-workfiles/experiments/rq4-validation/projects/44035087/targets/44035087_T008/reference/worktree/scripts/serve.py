
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from application import create_app
from runtime import build

APP = create_app()
build(ROOT / "dist")


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="application/json; charset=utf-8"):
        payload = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _api(self):
        parsed = urlsplit(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        try:
            payload = json.loads(self.rfile.read(length)) if length else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send(400, {"error": "invalid JSON"})
            return
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        result = APP.request(self.command, parsed.path, payload, query)
        self._send(result["status"], result["body"])

    def do_GET(self):
        if self.path.startswith("/api/"):
            self._api(); return
        name = "app.js" if self.path == "/app.js" else ("mobile-preview.html" if (ROOT / "dist" / "mobile-preview.html").exists() else "index.html")
        path = ROOT / "dist" / name
        if self.path not in {"/", "/app.js"} or not path.is_file():
            self.send_error(404); return
        kind = "application/javascript; charset=utf-8" if name == "app.js" else "text/html; charset=utf-8"
        self._send(200, path.read_bytes(), kind)

    def do_POST(self):
        self._api()

    def do_PATCH(self):
        self._api()


ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
