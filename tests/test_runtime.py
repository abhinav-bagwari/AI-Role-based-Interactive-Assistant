from __future__ import annotations

from pathlib import Path
import unittest

from bmad_team_orchestrator.llm_provider import StubLLMProvider
from bmad_team_orchestrator.runner import BmadTeamRuntime


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[2]
        self.runtime = BmadTeamRuntime(repo_root=self.repo_root, provider=StubLLMProvider("unit tests"))

    def test_teams_are_loaded(self) -> None:
        teams = self.runtime.list_teams()
        self.assertTrue(any(team["id"] == "team-a" for team in teams))
        self.assertTrue(any(team["id"] == "team-b" for team in teams))

    def test_bmad_agents_are_loaded(self) -> None:
        agents = self.runtime.list_bmad_agents()
        names = {agent["name"] for agent in agents}
        self.assertIn("pm", names)
        self.assertIn("architect", names)
        self.assertIn("dev", names)
        self.assertIn("qa", names)
        self.assertIn("sm", names)

    def test_runtime_status_is_available(self) -> None:
        status = self.runtime.runtime_status()
        self.assertEqual(status["mode"], "stub")
        self.assertFalse(status["ready"])

    def test_run_produces_artifacts_and_agent_handoffs(self) -> None:
        result = self.runtime.execute("team-b", "Create a modular multi-agent product engineering system.")
        payload = result.to_dict()
        self.assertGreater(len(payload["artifacts"]), 0)
        self.assertGreater(len(payload["protocol_trace"]), 0)
        self.assertIn("Director run completed.", payload["summary"])
        self.assertTrue(
            any(
                message["type"] == "HANDOFF"
                and message["from_role"] not in {"director", "user"}
                and message["to_role"] not in {"director", "user"}
                for message in payload["protocol_trace"]
            )
        )

    def test_first_chat_message_introduces_rhea_and_core_team(self) -> None:
        payload = self.runtime.send_message("team-b", "Hi Rhea")
        reply = payload["assistant_message"]["content"]
        self.assertIn("Hi, my name is Rhea", reply)
        self.assertIn("Let me introduce your core employees:", reply)
        self.assertIn("John (Product Manager)", reply)
        self.assertIn("Winston (Architect)", reply)
        self.assertIn("Amelia (Developer Agent)", reply)
        self.assertIn("Quinn (QA Engineer)", reply)
        self.assertIn("Bob (Scrum Master)", reply)
        self.assertIn("company owner", reply)
        self.assertNotIn("Mary (Business Analyst)", reply)

    def test_chat_history_persists_across_turns(self) -> None:
        self.runtime.send_message("team-a", "Hello")
        self.runtime.send_message("team-a", "We need to build a planning and implementation flow.")
        payload = self.runtime.send_message("team-a", "We also need stronger release checkpoints.")
        messages = payload["messages"]
        self.assertEqual(len(messages), 6)
        self.assertNotIn("Let me introduce your core employees:", payload["assistant_message"]["content"])

    def test_team_can_be_renamed(self) -> None:
        team = self.runtime.rename_team("team-a", "Alpha Delivery Team")
        self.assertEqual(team["name"], "Alpha Delivery Team")
        teams = self.runtime.list_teams()
        self.assertTrue(any(item["name"] == "Alpha Delivery Team" for item in teams))

    def test_requirement_runs_full_internal_team_sync(self) -> None:
        self.runtime.send_message("team-b", "Hello")
        payload = self.runtime.send_message(
            "team-b",
            "We need to build a configurable API platform with testing and deployment readiness.",
        )
        reply = payload["assistant_message"]["content"]
        latest_trace = payload["latest_internal_trace"]
        self.assertIn("I pulled your BMAD employee team into an internal sync.", reply)
        self.assertIsNotNone(latest_trace)
        self.assertEqual(set(latest_trace["roles"]), {"pm", "architect", "dev", "qa", "sm"})
        self.assertTrue(
            any(
                message["type"] == "HANDOFF"
                and message["from_role"] in {"pm", "architect", "dev", "qa", "sm"}
                and message["to_role"] in {"pm", "architect", "dev", "qa", "sm"}
                for message in latest_trace["messages"]
            )
        )

    def test_explicit_role_request_can_lead_the_sync(self) -> None:
        self.runtime.send_message("team-b", "Hello")
        payload = self.runtime.send_message("team-b", "Ask QA to challenge the release plan and coverage.")
        latest_trace = payload["latest_internal_trace"]
        self.assertIsNotNone(latest_trace)
        self.assertEqual(latest_trace["roles"][0], "qa")
        self.assertIn("Quinn (QA Engineer)", payload["assistant_message"]["content"])

    def test_conversation_payload_exposes_internal_protocol(self) -> None:
        self.runtime.send_message("team-a", "Hello")
        self.runtime.send_message("team-a", "We need to ship a new API and deployment workflow.")
        payload = self.runtime.get_conversation("team-a")
        self.assertIn("internal_traces", payload)
        self.assertGreater(len(payload["internal_traces"]), 0)
        latest_trace = payload["latest_internal_trace"]
        self.assertIsNotNone(latest_trace)
        self.assertTrue(any(message["type"] == "HANDOFF" for message in latest_trace["messages"]))


if __name__ == "__main__":
    unittest.main()
