"""Local test relay for the web app (developer tool, never deployed).

Lets you test the browser app's AI path without typing a real key into the page: run this, choose provider
"Custom" in the app with base URL http://localhost:8766/v1/ and any dummy key. The relay adds the real key from
.env (GEMINI_API_KEY) and forwards to Gemini's OpenAI-compatible endpoint.

  python tools/dev_proxy.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from promofinder.llm import load_env_file  # noqa: E402

load_env_file()
UPSTREAM = "https://generativelanguage.googleapis.com/v1beta/openai"
KEY = os.environ.get("GEMINI_API_KEY", "")


class Relay(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        path = self.path.split("/v1", 1)[-1]
        req = urllib.request.Request(UPSTREAM + path, data=body, method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}"})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                status, data = r.status, r.read()
        except urllib.error.HTTPError as e:
            status, data = e.code, e.read()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data)
        try:
            model = json.loads(body).get("model")
        except Exception:  # noqa: BLE001
            model = "?"
        print(f"relay {status} {model}", flush=True)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    if not KEY:
        sys.exit("GEMINI_API_KEY not found in .env")
    print("relay on http://localhost:8766/v1/ -> Gemini", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8766), Relay).serve_forever()
