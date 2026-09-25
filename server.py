"""server.py：本机服务（查询 / 重建 / 回滚，重建期间查询始终可用）。"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from indexbuild import IndexStore, RollbackError

STORE = IndexStore()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _json_bytes(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False).encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/search":
            term = query.get("q", [""])[0]
            hits = STORE.search(term)
            self._write_json(200, {"term": term, "hits": hits, "generation": STORE.generation})
        elif parsed.path == "/status":
            self._write_json(200, {
                "generation": STORE.generation,
                "builds": STORE.builds,
                "queries": STORE.queries,
                "history": len(STORE._history),
            })
        elif parsed.path in ("/", "/index.html"):
            self._write_file(os.path.join(BASE_DIR, "index.html"), "text/html; charset=utf-8")
        else:
            self._write_json(404, {"error": "not found", "path": parsed.path})

    def do_POST(self):
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._write_json(400, {"error": "invalid JSON body"})
            return

        if parsed.path == "/rebuild":
            docs = payload.get("docs", {})
            if not isinstance(docs, dict):
                self._write_json(400, {"error": "'docs' must be an object"})
                return
            generation = STORE.rebuild(docs)
            self._write_json(200, {"generation": generation})
        elif parsed.path == "/rollback":
            try:
                generation = STORE.rollback()
            except RollbackError as exc:
                self._write_json(409, {"error": str(exc), "generation": STORE.generation})
            else:
                self._write_json(200, {"generation": generation})
        else:
            self._write_json(404, {"error": "not found", "path": parsed.path})

    def _write_json(self, status: int, payload) -> None:
        body = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _write_file(self, path: str, content_type: str) -> None:
        try:
            with open(path, "rb") as handle:
                body = handle.read()
        except OSError:
            self._write_json(404, {"error": "not found"})
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(port: int = 0):
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    httpd = serve(port)
    print("listening on http://%s:%d" % httpd.server_address, flush=True)
    httpd.serve_forever()
