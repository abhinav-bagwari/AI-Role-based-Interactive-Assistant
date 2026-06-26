from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from bmad_team_orchestrator.application_writer import ApplicationWriter


class ApplicationWriterTests(unittest.TestCase):
    def test_write_application_creates_expected_folder_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            writer = ApplicationWriter(applications_root=Path(tmp))
            result = writer.write_application(
                {
                    "app_name": "Calendar App",
                    "owner_input": "Create a calendar app.",
                    "artifacts": [
                        {
                            "type": "roadmap",
                            "title": "Product Roadmap",
                            "content": "Roadmap body",
                        },
                        {
                            "type": "diagram",
                            "title": "Architecture Diagram",
                            "content": "```mermaid\nflowchart LR\n  A --> B\n```",
                        },
                        {
                            "type": "implementation",
                            "title": "Implementation Package",
                            "content": "```tsx\nexport function CalendarApp() { return null; }\n```",
                        },
                    ],
                }
            )

            app_path = Path(result["application_path"])
            self.assertEqual(app_path.name, "calendar-app")
            self.assertTrue((app_path / "README.md").exists())
            self.assertTrue((app_path / "manifest.json").exists())
            self.assertTrue((app_path / "package.json").exists())
            self.assertTrue((app_path / "index.html").exists())
            self.assertTrue((app_path / ".gitignore").exists())
            self.assertTrue((app_path / "src" / "vite-env.d.ts").exists())
            self.assertEqual((app_path / "product" / "roadmap.md").read_text(encoding="utf-8").strip(), "Roadmap body")
            self.assertIn("flowchart LR", (app_path / "diagrams" / "architecture.mmd").read_text(encoding="utf-8"))
            self.assertIn("CalendarApp", (app_path / "src" / "CalendarApp.tsx").read_text(encoding="utf-8"))
            self.assertIn("<CalendarApp />", (app_path / "src" / "main.tsx").read_text(encoding="utf-8"))
            (app_path / "node_modules").mkdir()
            (app_path / "node_modules" / "example.js").write_text("ignored", encoding="utf-8")

            inspected = writer.inspect_application("calendar-app")
            self.assertTrue(inspected["runnable"])
            self.assertEqual(inspected["run_commands"][0], f"cd {app_path}")
            self.assertIn("package.json", inspected["files"])
            self.assertNotIn("node_modules/example.js", inspected["files"])

            listed = writer.list_applications()
            self.assertEqual(listed["applications"][0]["slug"], "calendar-app")


if __name__ == "__main__":
    unittest.main()
