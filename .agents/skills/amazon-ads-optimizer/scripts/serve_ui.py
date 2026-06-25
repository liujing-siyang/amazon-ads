#!/usr/bin/env python3
"""Local HTML UI server for Amazon Ads Optimizer."""

from __future__ import annotations

import argparse
import importlib.util
import json
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

SKILL_DIR = Path(__file__).resolve().parents[1]
DEFAULT_DB = Path(__file__).resolve().parents[4] / "data" / "amazon_ads.sqlite"


def _load_script(name: str):
    script = Path(__file__).with_name(f"{name}.py")
    spec = importlib.util.spec_from_file_location(name, script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdsOptimizerApp:
    def __init__(self, db_path: str | Path = DEFAULT_DB) -> None:
        self.db_path = str(db_path)

    def _json_response(self, status: int, data: dict[str, Any]) -> dict[str, Any]:
        return {"status": status, "content_type": "application/json; charset=utf-8", "body": json.dumps(data, ensure_ascii=False).encode("utf-8")}

    def handle_for_test(self, method: str, path: str, body: bytes) -> dict[str, Any]:
        return self.dispatch(method, path, body)

    def dispatch(self, method: str, path: str, body: bytes) -> dict[str, Any]:
        try:
            if method == "GET" and path == "/api/status":
                return self._json_response(200, {"ok": True, "db": self.db_path})
            if method == "GET" and path in {"/", "/config-builder.html"}:
                file = SKILL_DIR / "ui" / "config-builder.html"
                return {"status": 200, "content_type": "text/html; charset=utf-8", "body": file.read_bytes()}
            if method == "POST" and path == "/api/analyze":
                payload = json.loads(body.decode("utf-8") or "{}")
                analyzer = _load_script("analyze_asin")
                result = analyzer.analyze(payload.get("db") or self.db_path, payload["asin"], payload.get("target_acos"), rule_overrides=payload.get("rule_profile"), persist=bool(payload.get("persist")))
                output = payload.get("html_output")
                if output:
                    _load_script("render_html_report").write_html_report(result, output)
                    result["html_output"] = output
                return self._json_response(200, result)
            if method == "POST" and path == "/api/import-ads":
                payload = json.loads(body.decode("utf-8") or "{}")
                importer = _load_script("import_ad_reports")
                files = payload.get("csv_files") or []
                return self._json_response(200, {"results": [importer.import_report(payload.get("db") or self.db_path, f) for f in files]})
            if method == "POST" and path == "/api/validate-evidence":
                payload = json.loads(body.decode("utf-8") or "{}")
                return self._json_response(200, _load_script("validate_evidence").validate_database(payload.get("db") or self.db_path))
            return self._json_response(404, {"ok": False, "error": "not found"})
        except Exception as exc:
            return self._json_response(500, {"ok": False, "error": str(exc)})


def create_app(db_path: str | Path = DEFAULT_DB) -> AdsOptimizerApp:
    return AdsOptimizerApp(db_path)


def make_handler(app: AdsOptimizerApp):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self._handle()
        def do_POST(self):
            self._handle()
        def _handle(self):
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            response = app.dispatch(self.command, self.path.split("?", 1)[0], body)
            self.send_response(response["status"])
            self.send_header("Content-Type", response.get("content_type") or mimetypes.types_map.get(Path(self.path).suffix, "application/octet-stream"))
            self.send_header("Content-Length", str(len(response["body"])))
            self.end_headers()
            self.wfile.write(response["body"])
        def log_message(self, format, *args):
            return
    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve local Amazon Ads Optimizer UI.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    app = create_app(args.db)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    print(f"Serving Amazon Ads Optimizer at http://{args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
