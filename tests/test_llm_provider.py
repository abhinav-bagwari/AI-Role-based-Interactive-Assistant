from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bmad_team_orchestrator.llm_provider import OpenAICompatibleProvider, _load_codex_provider_config


class LLMProviderConfigTests(unittest.TestCase):
    def test_loads_codex_provider_config_without_exposing_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_dir = home / ".codex"
            codex_dir.mkdir()
            (codex_dir / "config.toml").write_text(
                """
model_provider = "example"
profile = "gpt-5-3-codex"
model = "top-level-model"

[model_providers.example]
base_url = "https://provider.example.test/v1"
model = "provider-model"
name = "Codex Example Provider"
wire_api = "responses"

  [model_providers.example.http_headers]
  client = "codex-cli"

[profiles.gpt-5-3-codex]
model = "gpt-5.5"
model_provider = "example"
""",
                encoding="utf-8",
            )
            (codex_dir / "auth.json").write_text('{"OPENAI_API_KEY":"secret-value"}', encoding="utf-8")

            config = _load_codex_provider_config(home=home)

            self.assertEqual(config["model"], "gpt-5.5")
            self.assertEqual(config["base_url"], "https://provider.example.test/v1")
            self.assertEqual(config["wire_api"], "responses")
            self.assertEqual(config["provider_name"], "Codex Example Provider")
            self.assertEqual(config["extra_headers"], {"client": "codex-cli"})
            self.assertEqual(config["api_key"], "secret-value")

    def test_extracts_responses_output_text(self) -> None:
        payload = {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Hello from responses.",
                        }
                    ],
                }
            ]
        }

        self.assertEqual(OpenAICompatibleProvider._extract_responses_content(payload), "Hello from responses.")

    def test_parses_sse_wrapped_response_payload(self) -> None:
        raw = 'event: response.completed\n\ndata: {"output_text":"SSE ok"}\n\ndata: [DONE]\n'

        self.assertEqual(OpenAICompatibleProvider._parse_sse_json(raw), {"output_text": "SSE ok"})


if __name__ == "__main__":
    unittest.main()
