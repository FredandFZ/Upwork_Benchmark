from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from runtime import build, feature_catalog

build(ROOT / "dist")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/features":
            payload = json.dumps(feature_catalog(), ensure_ascii=False).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/json; charset=utf-8"); self.end_headers(); self.wfile.write(payload); return
        candidates = [ROOT / "dist" / "index.html", ROOT / "dist" / "mobile-preview.html", ROOT / "dist" / "template-preview.html", ROOT / "dist" / "report-preview.html"]
        page = next((path for path in candidates if path.exists()), None)
        if self.path == "/" and page:
            payload = page.read_bytes(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.end_headers(); self.wfile.write(payload); return
        self.send_error(404)

ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
