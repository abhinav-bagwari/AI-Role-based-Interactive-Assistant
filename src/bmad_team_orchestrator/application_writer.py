from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List


DEFAULT_APPLICATIONS_ROOT = Path(__file__).resolve().parents[2] / "bmad-applications"


@dataclass(frozen=True)
class WrittenFile:
    label: str
    path: Path

    def to_dict(self) -> Dict[str, str]:
        return {
            "label": self.label,
            "path": str(self.path),
        }


class ApplicationWriter:
    def __init__(self, applications_root: Path | None = None) -> None:
        configured_root = os.getenv("BMAD_APPLICATIONS_ROOT", "").strip()
        self.applications_root = applications_root or Path(configured_root or DEFAULT_APPLICATIONS_ROOT)

    def write_application(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        app_name = self._string(payload.get("app_name") or payload.get("title") or "new-app")
        owner_input = self._string(payload.get("owner_input"))
        artifacts = self._artifacts(payload.get("artifacts"))
        slug = self.slugify(app_name)
        app_dir = self.applications_root / slug
        app_dir.mkdir(parents=True, exist_ok=True)

        written: List[WrittenFile] = []
        written.append(self._write_text(app_dir / "README.md", self._build_readme(app_name, owner_input, artifacts), "README"))
        written.append(self._write_json(app_dir / "manifest.json", self._build_manifest(app_name, slug, owner_input, artifacts), "Manifest"))

        for artifact in artifacts:
            file_path = app_dir / self._artifact_relative_path(artifact)
            content = self._string(artifact.get("content"))
            written.append(self._write_text(file_path, content, self._string(artifact.get("title")) or artifact["type"]))

            if artifact["type"] == "diagram":
                mermaid = self._extract_fenced_block(content, "mermaid")
                if mermaid:
                    written.append(self._write_text(app_dir / "diagrams" / "architecture.mmd", mermaid, "Mermaid source"))

            if artifact["type"] == "implementation":
                code_block = self._extract_first_code_block(content, languages=("tsx", "jsx", "ts", "js"))
                if code_block:
                    written.extend(self._write_react_scaffold(app_dir, app_name, code_block))

        return {
            "app_name": app_name,
            "slug": slug,
            "application_path": str(app_dir),
            "files": [item.to_dict() for item in written],
        }

    def list_applications(self) -> Dict[str, Any]:
        self.applications_root.mkdir(parents=True, exist_ok=True)
        applications = [
            self.inspect_application(path.name)
            for path in sorted(self.applications_root.iterdir())
            if path.is_dir() and (path / "manifest.json").exists()
        ]
        applications.sort(key=lambda item: item.get("generated_at") or "", reverse=True)
        return {
            "applications_root": str(self.applications_root),
            "applications": applications,
        }

    def inspect_application(self, slug: str) -> Dict[str, Any]:
        safe_slug = self.slugify(slug)
        app_dir = self.applications_root / safe_slug
        if not app_dir.exists() or not app_dir.is_dir():
            raise FileNotFoundError(f"Application not found: {safe_slug}")

        manifest = self._read_manifest(app_dir)
        app_name = self._string(manifest.get("app_name")) or safe_slug.replace("-", " ").title()
        files = [
            path.relative_to(app_dir).as_posix()
            for path in sorted(app_dir.rglob("*"))
            if path.is_file() and not self._is_ignored_application_file(path.relative_to(app_dir))
        ]
        source_files = [file for file in files if file.startswith("src/") and file.endswith((".tsx", ".jsx", ".ts", ".js"))]
        runnable_files = ["package.json", "index.html", "src/main.tsx"]
        runnable = all((app_dir / file).exists() for file in runnable_files)
        run_commands = [
            f"cd {app_dir}",
            "npm install",
            "npm run dev",
        ]
        return {
            "app_name": app_name,
            "slug": safe_slug,
            "application_path": str(app_dir),
            "owner_input": self._string(manifest.get("owner_input")),
            "generated_at": self._string(manifest.get("generated_at")),
            "artifact_count": manifest.get("artifact_count", 0),
            "files": files,
            "source_files": source_files,
            "runnable": runnable,
            "missing_runtime_files": [file for file in runnable_files if not (app_dir / file).exists()],
            "run_commands": run_commands,
        }

    @staticmethod
    def slugify(value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
        return cleaned or "new-app"

    @staticmethod
    def _component_name(app_name: str) -> str:
        parts = re.findall(r"[a-zA-Z0-9]+", app_name)
        if not parts:
            return "App"
        name = "".join(part[:1].upper() + part[1:] for part in parts)
        return name if name.lower().endswith("app") else f"{name}App"

    def _write_react_scaffold(self, app_dir: Path, app_name: str, code_block: Dict[str, str]) -> List[WrittenFile]:
        language = code_block["language"]
        extension = "tsx" if language in {"tsx", "jsx"} else "ts"
        component_name = self._exported_component_name(code_block["code"]) or self._component_name(app_name)
        source = self._ensure_react_import(code_block["code"])
        files = [
            self._write_text(app_dir / "src" / f"{component_name}.{extension}", source, "Implementation source"),
            self._write_text(app_dir / "src" / "main.tsx", self._build_main_tsx(component_name), "React entrypoint"),
            self._write_text(app_dir / "src" / "styles.css", self._build_styles_css(), "Base styles"),
            self._write_text(app_dir / "src" / "vite-env.d.ts", self._build_vite_env_d_ts(), "Vite env types"),
            self._write_text(app_dir / "index.html", self._build_index_html(app_name), "App HTML"),
            self._write_text(app_dir / ".gitignore", self._build_app_gitignore(), "App gitignore"),
            self._write_json(app_dir / "package.json", self._build_package_json(app_name), "Package manifest"),
            self._write_json(app_dir / "tsconfig.json", self._build_tsconfig(), "TypeScript config"),
        ]
        return files

    @staticmethod
    def _exported_component_name(source: str) -> str:
        match = re.search(r"export\s+function\s+([A-Z][A-Za-z0-9_]*)\s*\(", source)
        return match.group(1) if match else ""

    @staticmethod
    def _ensure_react_import(source: str) -> str:
        if "from 'react'" in source or 'from "react"' in source or "import React" in source or "import * as React" in source:
            return source
        return 'import * as React from "react";\n\n' + source

    @staticmethod
    def _build_main_tsx(component_name: str) -> str:
        return f"""import * as React from "react";
import {{ createRoot }} from "react-dom/client";
import {{ {component_name} }} from "./{component_name}";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <{component_name} />
  </React.StrictMode>,
);
"""

    @staticmethod
    def _build_styles_css() -> str:
        return """html,
body,
#root {
  min-height: 100%;
}

body {
  margin: 0;
  background: #020617;
  color: #f8fafc;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* {
  box-sizing: border-box;
}

button,
input {
  font: inherit;
}
"""

    @staticmethod
    def _build_vite_env_d_ts() -> str:
        return '/// <reference types="vite/client" />\n'

    @staticmethod
    def _build_app_gitignore() -> str:
        return """node_modules/
dist/
.DS_Store
*.log
*.tsbuildinfo
"""

    @staticmethod
    def _build_index_html(app_name: str) -> str:
        return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{app_name}</title>
    <script src="https://cdn.tailwindcss.com"></script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
"""

    @staticmethod
    def _build_package_json(app_name: str) -> Dict[str, Any]:
        slug = ApplicationWriter.slugify(app_name)
        return {
            "name": slug,
            "version": "0.1.0",
            "private": True,
            "type": "module",
            "scripts": {
                "dev": "vite",
                "build": "tsc -b && vite build",
                "preview": "vite preview",
            },
            "dependencies": {
                "vite": "latest",
                "typescript": "latest",
                "react": "latest",
                "react-dom": "latest",
            },
            "devDependencies": {
                "@types/react": "latest",
                "@types/react-dom": "latest",
            },
        }

    @staticmethod
    def _build_tsconfig() -> Dict[str, Any]:
        return {
            "compilerOptions": {
                "target": "ES2020",
                "useDefineForClassFields": True,
                "lib": ["DOM", "DOM.Iterable", "ES2020"],
                "allowJs": False,
                "skipLibCheck": True,
                "esModuleInterop": True,
                "allowSyntheticDefaultImports": True,
                "strict": True,
                "forceConsistentCasingInFileNames": True,
                "module": "ESNext",
                "moduleResolution": "Bundler",
                "resolveJsonModule": True,
                "isolatedModules": True,
                "noEmit": True,
                "jsx": "react-jsx",
            },
            "include": ["src"],
            "references": [],
        }

    @staticmethod
    def _string(value: object) -> str:
        return str(value).strip() if value is not None else ""

    def _artifacts(self, value: object) -> List[Dict[str, str]]:
        if not isinstance(value, list):
            return []
        artifacts: List[Dict[str, str]] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            artifact_type = self.slugify(self._string(item.get("type")) or "artifact")
            title = self._string(item.get("title")) or artifact_type.replace("-", " ").title()
            content = self._string(item.get("content"))
            if not content:
                continue
            artifacts.append(
                {
                    "type": artifact_type,
                    "title": title,
                    "content": content,
                }
            )
        return artifacts

    def _artifact_relative_path(self, artifact: Dict[str, str]) -> Path:
        artifact_type = artifact["type"]
        file_map = {
            "intake": Path("product") / "intake.md",
            "discovery": Path("product") / "team-huddle.md",
            "checkpoint": Path("product") / "owner-checkpoint.md",
            "roadmap": Path("product") / "roadmap.md",
            "diagram": Path("diagrams") / "architecture.md",
            "implementation": Path("src") / "implementation-package.md",
            "qa": Path("qa") / "release-gate.md",
            "release": Path("qa") / "release-gate.md",
            "final": Path("handoff") / "final-package.md",
        }
        return file_map.get(artifact_type, Path("artifacts") / f"{artifact_type}.md")

    def _build_readme(self, app_name: str, owner_input: str, artifacts: Iterable[Dict[str, str]]) -> str:
        artifact_list = list(artifacts)
        lines = [
            f"# {app_name}",
            "",
            "Generated by ARIA / BMAD Team Orchestrator.",
            "",
            "## Owner Request",
            "",
            owner_input or "No owner request captured.",
            "",
            "## Artifact Index",
            "",
        ]
        if artifact_list:
            for artifact in artifact_list:
                relative = self._artifact_relative_path(artifact)
                lines.append(f"- [{artifact['title']}]({relative.as_posix()})")
        else:
            lines.append("- No artifacts captured.")
        lines.extend(
            [
                "",
                "## Suggested Next Step",
                "",
                "Use the implementation package as the starting point for repo files, then run the QA release gate before treating this app as production-ready.",
                "",
            ]
        )
        return "\n".join(lines)

    def _build_manifest(
        self,
        app_name: str,
        slug: str,
        owner_input: str,
        artifacts: Iterable[Dict[str, str]],
    ) -> Dict[str, Any]:
        return {
            "app_name": app_name,
            "slug": slug,
            "owner_input": owner_input,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "artifact_count": len(list(artifacts)),
            "applications_root": str(self.applications_root),
        }

    def _write_text(self, path: Path, content: str, label: str) -> WrittenFile:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        return WrittenFile(label=label, path=path)

    def _write_json(self, path: Path, payload: Dict[str, Any], label: str) -> WrittenFile:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return WrittenFile(label=label, path=path)

    @staticmethod
    def _read_manifest(app_dir: Path) -> Dict[str, Any]:
        manifest_path = app_dir / "manifest.json"
        if not manifest_path.exists():
            return {}
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _is_ignored_application_file(relative_path: Path) -> bool:
        parts = relative_path.parts
        if not parts:
            return False
        if parts[0] in {"node_modules", "dist"}:
            return True
        if relative_path.name == ".DS_Store" or relative_path.name.endswith(".tsbuildinfo"):
            return True
        return False

    @staticmethod
    def _extract_fenced_block(content: str, language: str) -> str:
        pattern = rf"```{re.escape(language)}\s*(.*?)```"
        match = re.search(pattern, content, flags=re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else ""

    @staticmethod
    def _extract_first_code_block(content: str, languages: tuple[str, ...]) -> Dict[str, str] | None:
        pattern = r"```([a-zA-Z0-9_-]+)\s*(.*?)```"
        for match in re.finditer(pattern, content, flags=re.DOTALL):
            language = match.group(1).lower()
            if language in languages:
                return {"language": language, "code": match.group(2).strip()}
        return None
