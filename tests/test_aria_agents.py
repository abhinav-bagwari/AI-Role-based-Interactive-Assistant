from __future__ import annotations

from pathlib import Path
import unittest

from bmad_team_orchestrator.aria_agents import build_aria_agent_system_prompt, resolve_aria_bmad_role
from bmad_team_orchestrator.bmad_catalog import BmadCatalog


class AriaAgentRoleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repo_root = Path(__file__).resolve().parents[2]
        self.catalog = BmadCatalog(repo_root=self.repo_root)

    def test_resolves_aria_agents_to_bmad_roles(self) -> None:
        self.assertEqual(resolve_aria_bmad_role("rhea"), "bmad-master")
        self.assertEqual(resolve_aria_bmad_role("marcus"), "pm")
        self.assertEqual(resolve_aria_bmad_role("zara"), "ux-designer")
        self.assertEqual(resolve_aria_bmad_role("kai"), "dev")
        self.assertEqual(resolve_aria_bmad_role("priya"), "architect")
        self.assertEqual(resolve_aria_bmad_role("nox"), "qa")

    def test_builds_bmad_backed_system_prompt_for_known_agent(self) -> None:
        prompt, role = build_aria_agent_system_prompt(
            base_system_prompt="Base ARIA prompt.",
            catalog=self.catalog,
            agent_id="marcus",
            agent_name="Marcus",
            agent_role="Product Manager",
            mode="team",
            phase_label="Roadmap package",
            max_prompt_chars=1200,
        )

        self.assertEqual(role, "pm")
        self.assertIn("Base ARIA prompt.", prompt)
        self.assertIn("BMAD specialist backing", prompt)
        self.assertIn("BMAD source role: John (Product Manager)", prompt)
        self.assertIn("Use this BMAD source as specialist training", prompt)

    def test_unknown_agent_keeps_base_prompt(self) -> None:
        prompt, role = build_aria_agent_system_prompt(
            base_system_prompt="Base only.",
            catalog=self.catalog,
            agent_id="unknown",
        )

        self.assertEqual(role, "")
        self.assertEqual(prompt, "Base only.")


if __name__ == "__main__":
    unittest.main()
