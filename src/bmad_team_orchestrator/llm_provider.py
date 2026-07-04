from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class LLMProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderStatus:
    mode: str
    provider_name: str
    model: str
    base_url: str
    wire_api: str
    ready: bool
    reason: str

    def to_dict(self) -> Dict[str, object]:
        return {
            "mode": self.mode,
            "provider_name": self.provider_name,
            "model": self.model,
            "base_url": self.base_url,
            "wire_api": self.wire_api,
            "ready": self.ready,
            "reason": self.reason,
        }


class BaseLLMProvider:
    def status(self) -> ProviderStatus:
        raise NotImplementedError

    def is_live(self) -> bool:
        return self.status().mode == "live" and self.status().ready

    def generate_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        raise NotImplementedError

    def generate_text(self, system_prompt: str, user_prompt: str, max_tokens: int = 700) -> str:
        raise NotImplementedError


class StubLLMProvider(BaseLLMProvider):
    def __init__(self, reason: str) -> None:
        self._status = ProviderStatus(
            mode="stub",
            provider_name="local-fallback",
            model="heuristic",
            base_url="",
            wire_api="chat",
            ready=False,
            reason=reason,
        )

    def status(self) -> ProviderStatus:
        return self._status

    def generate_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        raise LLMProviderError("Live BMAD provider is not configured")

    def generate_text(self, system_prompt: str, user_prompt: str, max_tokens: int = 700) -> str:
        raise LLMProviderError("Live BMAD provider is not configured")


class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str | None = None,
        provider_name: str = "openai-compatible",
        wire_api: str = "chat",
        extra_headers: Dict[str, str] | None = None,
        temperature: float = 0.2,
        timeout_seconds: int = 90,
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or ""
        self.provider_name = provider_name
        self.wire_api = wire_api
        self.extra_headers = extra_headers or {}
        self.temperature = temperature
        self.timeout_seconds = timeout_seconds

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            mode="live",
            provider_name=self.provider_name,
            model=self.model,
            base_url=self.base_url,
            wire_api=self.wire_api,
            ready=True,
            reason="True BMAD agents are enabled through a live language-model provider.",
        )

    def generate_json(self, system_prompt: str, user_prompt: str) -> Dict[str, Any]:
        content = self.generate_text(system_prompt=system_prompt, user_prompt=user_prompt)
        return self._parse_json_object(content)

    def generate_text(self, system_prompt: str, user_prompt: str, max_tokens: int = 700) -> str:
        if self.wire_api == "responses":
            return self._generate_responses_text(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=max_tokens)
        return self._generate_chat_text(system_prompt=system_prompt, user_prompt=user_prompt, max_tokens=max_tokens)

    def _generate_chat_text(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        raw = self._post_json(f"{self.base_url}/chat/completions", payload)
        return self._extract_message_content(raw).strip()

    def _generate_responses_text(self, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
        payload = {
            "model": self.model,
            "max_output_tokens": max_tokens,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": system_prompt}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_prompt}],
                },
            ],
        }
        raw = self._post_json(f"{self.base_url}/responses", payload)
        return self._extract_responses_content(raw).strip()

    def _post_json(self, url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json", **self.extra_headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(url=url, data=body, headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise LLMProviderError(f"Provider returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise LLMProviderError(f"Provider request failed: {exc.reason}") from exc

        try:
            return json.loads(raw_body)
        except json.JSONDecodeError as exc:
            sse_payload = self._parse_sse_json(raw_body)
            if sse_payload is not None:
                return sse_payload
            raise LLMProviderError("Provider returned invalid JSON") from exc

    @staticmethod
    def _extract_message_content(payload: Dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMProviderError("Provider response did not include choices")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
            if parts:
                return "\n".join(parts)
        raise LLMProviderError("Provider response did not include usable text content")

    @classmethod
    def _extract_responses_content(cls, payload: Dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        if "choices" in payload:
            return cls._extract_message_content(payload)

        parts: list[str] = []

        def collect(value: Any) -> None:
            if isinstance(value, dict):
                item_type = str(value.get("type") or "")
                text = value.get("text")
                if item_type in {"output_text", "text"} and isinstance(text, str):
                    parts.append(text)
                for key in ("content", "output"):
                    collect(value.get(key))
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(payload.get("output"))
        if parts:
            return "\n".join(parts)
        raise LLMProviderError("Provider response did not include usable response text")

    @staticmethod
    def _parse_sse_json(raw_body: str) -> Dict[str, Any] | None:
        payloads: list[Dict[str, Any]] = []
        for raw_line in raw_body.splitlines():
            line = raw_line.strip()
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if not data or data == "[DONE]":
                continue
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                payloads.append(parsed)
        return payloads[-1] if payloads else None

    @staticmethod
    def _parse_json_object(content: str) -> Dict[str, Any]:
        text = content.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                raise LLMProviderError("Provider response was not valid JSON")
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError as exc:
                raise LLMProviderError("Provider response contained malformed JSON") from exc

        if not isinstance(parsed, dict):
            raise LLMProviderError("Provider response JSON must be an object")
        return parsed


def _load_project_env_files() -> None:
    project_root = Path(__file__).resolve().parents[2]
    for path in (project_root / ".env.local", project_root / ".env"):
        _load_env_file(path)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip().strip('"').strip("'")
        os.environ[key] = value


def _load_codex_provider_config(home: Path | None = None) -> Dict[str, Any]:
    root = home or Path.home()
    config_path = root / ".codex" / "config.toml"
    auth_path = root / ".codex" / "auth.json"
    parsed = _parse_simple_toml(config_path)
    top = parsed.get("", {})
    profile_name = str(os.getenv("BMAD_CODEX_PROFILE") or top.get("profile") or "").strip()
    profile = parsed.get(f"profiles.{profile_name}", {}) if profile_name else {}
    provider_id = str(profile.get("model_provider") or top.get("model_provider") or "").strip()
    provider = parsed.get(f"model_providers.{provider_id}", {}) if provider_id else {}
    headers = parsed.get(f"model_providers.{provider_id}.http_headers", {}) if provider_id else {}

    model = str(profile.get("model") or top.get("model") or provider.get("model") or "").strip()
    base_url = str(provider.get("base_url") or "").strip()
    wire_api = str(provider.get("wire_api") or "chat").strip()
    provider_name = str(provider.get("name") or provider_id or "Codex provider").strip()

    api_key = ""
    if auth_path.exists():
        try:
            auth = json.loads(auth_path.read_text(encoding="utf-8"))
            api_key = str(auth.get("OPENAI_API_KEY") or "").strip()
        except (json.JSONDecodeError, OSError):
            api_key = ""

    return {
        "model": model,
        "base_url": base_url,
        "api_key": api_key,
        "wire_api": wire_api,
        "provider_name": provider_name,
        "extra_headers": {str(key): str(value) for key, value in headers.items()},
    }


def _parse_simple_toml(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        return {"": {}}

    sections: Dict[str, Dict[str, str]] = {"": {}}
    current = sections[""]
    for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section_name = line.strip("[]").strip()
            current = sections.setdefault(section_name, {})
            continue
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = _parse_simple_toml_value(raw_value.strip())
        if key:
            current[key] = value
    return sections


def _parse_simple_toml_value(raw_value: str) -> str:
    value = raw_value.split("#", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def build_provider_from_env() -> BaseLLMProvider:
    _load_project_env_files()
    model = os.getenv("BMAD_LLM_MODEL") or os.getenv("OPENAI_MODEL") or ""
    base_url = os.getenv("BMAD_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or ""
    api_key = os.getenv("BMAD_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or ""
    wire_api = os.getenv("BMAD_LLM_WIRE_API") or os.getenv("OPENAI_WIRE_API") or ""
    provider_name = "openai-compatible"
    extra_headers: Dict[str, str] = {}
    temperature_raw = os.getenv("BMAD_LLM_TEMPERATURE", "0.2")
    timeout_raw = os.getenv("BMAD_LLM_TIMEOUT_SECONDS", "90")
    loaded_codex_provider = False

    if not model or not base_url or not api_key or not wire_api:
        codex_config = _load_codex_provider_config()
        if codex_config.get("model") or codex_config.get("base_url"):
            codex_base_url = str(codex_config.get("base_url") or "").rstrip("/")
            model = model or str(codex_config.get("model") or "")
            base_url = base_url or str(codex_config.get("base_url") or "")
            uses_codex_provider = bool(codex_base_url) and base_url.rstrip("/") == codex_base_url
            if uses_codex_provider:
                api_key = api_key or str(codex_config.get("api_key") or "")
                wire_api = wire_api or str(codex_config.get("wire_api") or "")
                provider_name = str(codex_config.get("provider_name") or provider_name)
                extra_headers = dict(codex_config.get("extra_headers") or {})
                loaded_codex_provider = True

    if not model:
        return StubLLMProvider(
            "Set BMAD_LLM_MODEL and BMAD_LLM_BASE_URL, or keep Codex configured with a model provider, to enable live BMAD-agent execution.",
        )

    if not base_url:
        if api_key:
            base_url = "https://api.openai.com/v1"
        else:
            return StubLLMProvider(
                "Set BMAD_LLM_BASE_URL (or OPENAI_BASE_URL) to enable live BMAD-agent execution.",
            )

    if loaded_codex_provider and not api_key:
        return StubLLMProvider(
            "Codex provider config was found, but no API key was available in ~/.codex/auth.json.",
        )

    try:
        temperature = float(temperature_raw)
    except ValueError:
        temperature = 0.2

    try:
        timeout_seconds = int(timeout_raw)
    except ValueError:
        timeout_seconds = 90

    return OpenAICompatibleProvider(
        model=model,
        base_url=base_url,
        api_key=api_key or None,
        provider_name=provider_name,
        wire_api=(wire_api or "chat").strip().lower(),
        extra_headers=extra_headers,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
    )
