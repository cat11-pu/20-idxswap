"""server.py：本机服务（查询 / 旁路重建原子切换 / 回滚）。"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from indexbuild import IndexStore

STORE = IndexStore()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/search":
            term = parse_qs(parsed.query).get("q", [""])[0]
            hits, generation = STORE.lookup(term)
            self._send_json(200, {"term": term, "hits": hits, "generation": generation})
        elif parsed.path == "/status":
            self._send_json(200, {
                "generation": STORE.generation,
                "builds": STORE.builds,
                "queries": STORE.queries,
                "has_previous": STORE.has_previous,
            })
        elif parsed.path in ("/", "/index.html"):
            with open(os.path.join(BASE_DIR, "index.html"), "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
            if not isinstance(payload, dict):
                payload = {}
        except json.JSONDecodeError:
            self._send_json(400, {"error": "invalid json"})
            return

        if parsed.path == "/rebuild":
            pause = 0
            if "build_pause" in payload:
                try:
                    pause = max(0.0, float(payload["build_pause"]))
                except (TypeError, ValueError):
                    self._send_json(400, {"error": "invalid build_pause"})
                    return
            generation = STORE.rebuild(payload.get("docs", {}), build_pause=pause)
            self._send_json(200, {"generation": generation, "builds": STORE.builds})
        elif parsed.path == "/rollback":
            try:
                generation = STORE.rollback()
            except LookupError as exc:
                self._send_json(409, {"error": str(exc)})
                return
            self._send_json(200, {"generation": generation})
        else:
            self._send_json(404, {"error": "not found"})

    def log_message(self, *args):
        pass


def serve(port: int = 0):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    print("listening on http://127.0.0.1:%d" % port)
    serve(port).serve_forever()
