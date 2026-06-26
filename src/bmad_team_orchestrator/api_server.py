from __future__ import annotations

import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .application_writer import ApplicationWriter
from .aria_agents import build_aria_agent_system_prompt
from .llm_provider import LLMProviderError
from .runner import BmadTeamRuntime


class ApiHandler(BaseHTTPRequestHandler):
    runtime = BmadTeamRuntime(repo_root=Path(__file__).resolve().parents[3])
    application_writer = ApplicationWriter()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        normalized_path = parsed.path.rstrip("/") or "/"
        parts = [part for part in normalized_path.split("/") if part]
        if normalized_path == "/health":
            self._json(HTTPStatus.OK, {"status": "ok"})
            return
        if normalized_path == "/api/teams":
            self._json(HTTPStatus.OK, {"teams": self.runtime.list_teams(), "runtime": self.runtime.runtime_status()})
            return
        if normalized_path == "/api/bmad-agents":
            self._json(HTTPStatus.OK, {"agents": self.runtime.list_bmad_agents()})
            return
        if normalized_path == "/api/applications":
            self._json(HTTPStatus.OK, self.application_writer.list_applications())
            return
        if len(parts) == 3 and parts[:2] == ["api", "applications"]:
            try:
                self._json(HTTPStatus.OK, self.application_writer.inspect_application(parts[2]))
            except FileNotFoundError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            return
        if normalized_path == "/api/runtime-status":
            self._json(HTTPStatus.OK, {"runtime": self.runtime.runtime_status()})
            return
        if len(parts) == 4 and parts[:2] == ["api", "teams"] and parts[3] == "conversation":
            team_id = parts[2]
            try:
                payload = self.runtime.get_conversation(team_id)
                self._json(HTTPStatus.OK, payload)
            except KeyError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            return
        if normalized_path.startswith("/api/runs/"):
            run_id = normalized_path.split("/")[-1]
            try:
                payload = self.runtime.get_run(run_id)
                self._json(HTTPStatus.OK, payload)
            except KeyError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            return
        if not normalized_path.startswith("/api/"):
            self._serve_ui_file(normalized_path)
            return
        self._json(HTTPStatus.NOT_FOUND, {"error": "Endpoint not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        normalized_path = parsed.path.rstrip("/") or "/"
        parts = [part for part in normalized_path.split("/") if part]
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        try:
            data = json.loads(raw.decode("utf-8")) if raw else {}
        except json.JSONDecodeError:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Invalid JSON"})
            return

        if normalized_path == "/api/runs":
            team_id = data.get("team_id")
            requirement = data.get("requirement")
            if not team_id or not requirement:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "team_id and requirement are required"})
                return
            try:
                result = self.runtime.execute(team_id=team_id, requirement=requirement)
            except (KeyError, FileNotFoundError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._json(HTTPStatus.CREATED, result.to_dict())
            return

        if normalized_path == "/api/applications":
            try:
                payload = self.application_writer.write_application(data)
            except OSError as exc:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(exc)})
                return
            self._json(HTTPStatus.CREATED, payload)
            return

        if normalized_path == "/api/agent-turns":
            provider = self.runtime.provider
            status = provider.status()
            if not provider.is_live():
                self._json(
                    HTTPStatus.OK,
                    {
                        "mode": "fallback",
                        "body": "",
                        "runtime": status.to_dict(),
                        "reason": status.reason,
                    },
                )
                return

            system_prompt = str(data.get("system_prompt") or "").strip()
            user_prompt = str(data.get("user_prompt") or "").strip()
            if not system_prompt or not user_prompt:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "system_prompt and user_prompt are required"})
                return
            system_prompt, bmad_role = build_aria_agent_system_prompt(
                base_system_prompt=system_prompt,
                catalog=self.runtime.catalog,
                agent_id=str(data.get("agent_id") or ""),
                agent_name=str(data.get("agent_name") or ""),
                agent_role=str(data.get("agent_role") or ""),
                mode=str(data.get("mode") or ""),
                phase_label=str(data.get("phase_label") or ""),
            )
            try:
                body = provider.generate_text(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    max_tokens=int(data.get("max_tokens") or 700),
                )
            except (LLMProviderError, ValueError) as exc:
                self._json(
                    HTTPStatus.OK,
                    {
                        "mode": "fallback",
                        "body": "",
                        "runtime": status.to_dict(),
                        "reason": str(exc),
                    },
                )
                return
            self._json(
                HTTPStatus.OK,
                {
                    "mode": "live",
                    "body": body,
                    "runtime": status.to_dict(),
                    "bmad_role": bmad_role,
                },
            )
            return

        if len(parts) == 4 and parts[:2] == ["api", "teams"] and parts[3] == "messages":
            team_id = parts[2]
            content = data.get("content")
            if not content:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "content is required"})
                return
            try:
                payload = self.runtime.send_message(team_id, content)
            except (KeyError, ValueError, FileNotFoundError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._json(HTTPStatus.CREATED, payload)
            return

        if len(parts) == 4 and parts[:2] == ["api", "teams"] and parts[3] == "rename":
            team_id = parts[2]
            name = data.get("name")
            if not name:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "name is required"})
                return
            try:
                payload = self.runtime.rename_team(team_id, name)
            except (KeyError, ValueError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return
            self._json(HTTPStatus.OK, {"team": payload})
            return

        self._json(HTTPStatus.NOT_FOUND, {"error": "Endpoint not found"})

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT.value)
        self._set_cors_headers()
        self.end_headers()

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _json(self, status: HTTPStatus, payload: dict) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _serve_ui_file(self, normalized_path: str) -> None:
        ui_root = self.runtime.project_root / "ui"
        relative = "index.html" if normalized_path == "/" else unquote(normalized_path.lstrip("/"))
        requested = (ui_root / relative).resolve()

        try:
            requested.relative_to(ui_root.resolve())
        except ValueError:
            self._json(HTTPStatus.FORBIDDEN, {"error": "Forbidden"})
            return

        if requested.is_dir():
            requested = requested / "index.html"
        if not requested.exists() or not requested.is_file():
            self._json(HTTPStatus.NOT_FOUND, {"error": "File not found"})
            return

        body = requested.read_bytes()
        content_type = mimetypes.guess_type(str(requested))[0] or "application/octet-stream"
        if requested.name == "index.html":
            content_type = "text/html; charset=utf-8"
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def _set_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")


def serve(host: str = "127.0.0.1", port: int = 8091) -> None:
    server = ThreadingHTTPServer((host, port), ApiHandler)
    print(f"BMAD Team Orchestrator running at http://{host}:{port}")
    server.serve_forever()
