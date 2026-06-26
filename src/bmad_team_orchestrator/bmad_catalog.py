from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List


@dataclass
class BmadAgentSpec:
    name: str
    display_name: str
    title: str
    module: str
    path: str
    capabilities: str
    communication_style: str


@dataclass
class BmadMenuItem:
    code: str
    label: str
    command_hint: str
    exec_path: str | None = None
    workflow_path: str | None = None
    data_path: str | None = None
    action: str | None = None


class BmadCatalog:
    """Loads BMAD-provided agents from manifest files."""

    _LEGACY_PATH_ALIASES = {
        "/_bmad/bmm/workflows/1-analysis/": "/_bmad/bmm/workflows/analysis/",
        "/_bmad/bmm/workflows/2-plan-workflows/": "/_bmad/bmm/workflows/plan-workflows/",
    }

    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.agent_manifest_path = repo_root / "_bmad" / "_config" / "agent-manifest.csv"
        self.workflow_manifest_path = repo_root / "_bmad" / "_config" / "workflow-manifest.csv"
        self.agents = self._load_agents()
        self._prompt_cache: Dict[str, str] = {}
        self._menu_cache: Dict[str, List[BmadMenuItem]] = {}
        self._config_cache: Dict[str, str] | None = None

    def _load_agents(self) -> Dict[str, BmadAgentSpec]:
        if not self.agent_manifest_path.exists():
            raise FileNotFoundError(f"Missing BMAD agent manifest: {self.agent_manifest_path}")
        agents: Dict[str, BmadAgentSpec] = {}
        with self.agent_manifest_path.open(encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                spec = BmadAgentSpec(
                    name=row["name"],
                    display_name=row.get("displayName", row["name"]),
                    title=row.get("title", ""),
                    module=row.get("module", ""),
                    path=row.get("path", ""),
                    capabilities=row.get("capabilities", ""),
                    communication_style=row.get("communicationStyle", ""),
                )
                agents[spec.name] = spec
        return agents

    def list_agents(self) -> List[Dict[str, str]]:
        return [
            {
                "name": spec.name,
                "display_name": spec.display_name,
                "title": spec.title,
                "capabilities": spec.capabilities,
                "path": spec.path,
            }
            for spec in self.agents.values()
        ]

    def get_agent(self, role: str) -> BmadAgentSpec:
        if role not in self.agents:
            raise KeyError(f"Role '{role}' is not available in BMAD manifest")
        return self.agents[role]

    def read_agent_prompt(self, role: str) -> str:
        if role in self._prompt_cache:
            return self._prompt_cache[role]
        spec = self.get_agent(role)
        agent_file = self.repo_root / spec.path
        if not agent_file.exists():
            prompt = f"Agent file not found: {agent_file}"
        else:
            prompt = agent_file.read_text(encoding="utf-8", errors="ignore")
        self._prompt_cache[role] = prompt
        return prompt

    def read_agent_prompt_excerpt(self, role: str, max_chars: int = 900) -> str:
        return self.read_agent_prompt(role)[:max_chars]

    def list_menu_items(self, role: str) -> List[BmadMenuItem]:
        if role in self._menu_cache:
            return list(self._menu_cache[role])

        prompt = self.read_agent_prompt(role)
        items: List[BmadMenuItem] = []
        for match in re.finditer(r"<item(?P<attrs>[^>]*)>(?P<label>.*?)</item>", prompt, flags=re.DOTALL):
            attrs = {
                key: value
                for key, value in re.findall(r'(\w+)="(.*?)"', match.group("attrs"), flags=re.DOTALL)
            }
            label = re.sub(r"\s+", " ", match.group("label")).strip()
            code_match = re.search(r"\[(?P<code>[A-Z-]+)\]", label)
            code = code_match.group("code") if code_match else label[:2].upper()
            items.append(
                BmadMenuItem(
                    code=code,
                    label=label,
                    command_hint=attrs.get("cmd", ""),
                    exec_path=attrs.get("exec"),
                    workflow_path=attrs.get("workflow"),
                    data_path=attrs.get("data"),
                    action=attrs.get("action"),
                )
            )

        self._menu_cache[role] = items
        return list(items)

    def choose_menu_item(self, role: str, user_message: str, intent_tags: List[str]) -> BmadMenuItem | None:
        items = self.list_menu_items(role)
        if not items:
            return None

        by_code = {item.code: item for item in items}
        lowered = user_message.lower()

        role_hints: Dict[str, List[tuple[str, tuple[str, ...]]]] = {
            "analyst": [
                ("BP", ("brainstorm", "idea", "ideation", "concept", "explore", "unsure")),
                ("MR", ("market", "competitor", "competition", "trend", "landscape")),
                ("DR", ("domain", "industry", "terminology", "subject matter")),
                ("TR", ("technical", "feasibility", "stack", "approach", "architecture")),
                ("CB", ("brief", "product brief", "requirements", "scope")),
                ("DP", ("document project", "document this project", "analyze project")),
            ],
            "pm": [
                ("CE", ("epic", "epics", "stories", "backlog", "user story")),
                ("CP", ("prd", "product requirements", "requirements document")),
                ("VP", ("validate prd", "review prd", "validate requirements")),
                ("EP", ("edit prd", "update prd")),
                ("IR", ("implementation readiness", "ready to build", "handoff to engineering")),
                ("CC", ("course correction", "change course", "pivot")),
            ],
            "architect": [
                ("CA", ("architecture", "system design", "technical design", "solution design", "microservice")),
                ("IR", ("implementation readiness", "alignment", "ready to build")),
            ],
            "dev": [
                ("DS", ("build", "implement", "develop", "code", "story", "ship")),
                ("CR", ("code review", "review code", "review implementation")),
            ],
            "qa": [
                ("QA", ("test", "tests", "qa", "validate", "coverage", "e2e", "automation")),
            ],
            "sm": [
                ("SP", ("sprint", "plan sprint", "sprint planning", "milestone")),
                ("CS", ("create story", "next story", "prepare story", "story context")),
                ("ER", ("retro", "retrospective")),
                ("CC", ("course correction", "change course", "pivot")),
            ],
            "tech-writer": [
                ("DP", ("document project", "document this project", "project docs", "brownfield")),
                ("WD", ("write document", "document", "spec", "writeup")),
                ("MG", ("mermaid", "diagram", "flowchart")),
                ("VD", ("validate doc", "review document", "docs review")),
                ("EC", ("explain", "teach", "concept", "how does")),
            ],
            "ux-designer": [
                ("CU", ("ux", "ui", "design", "journey", "experience", "wireframe")),
            ],
            "quick-flow-solo-dev": [
                ("QS", ("quick spec", "lean spec", "rapid spec")),
                ("QD", ("quick dev", "rapid implementation", "fast build")),
            ],
        }

        for code, keywords in role_hints.get(role, []):
            if code not in by_code:
                continue
            if any(keyword in lowered for keyword in keywords):
                return by_code[code]

        if role == "analyst" and "architecture" in intent_tags and "TR" in by_code:
            return by_code["TR"]
        if role == "analyst" and "analysis" in intent_tags and "CB" in by_code:
            return by_code["CB"]
        if role == "pm" and "planning" in intent_tags and "CE" in by_code:
            return by_code["CE"]
        if role == "qa" and "quality" in intent_tags and "QA" in by_code:
            return by_code["QA"]
        if role == "sm" and "planning" in intent_tags and "SP" in by_code:
            return by_code["SP"]
        if role == "ux-designer" and "ui" in intent_tags and "CU" in by_code:
            return by_code["CU"]
        if role == "architect" and "architecture" in intent_tags and "CA" in by_code:
            return by_code["CA"]
        if role == "dev" and "implementation" in intent_tags and "DS" in by_code:
            return by_code["DS"]

        return by_code.get("CH") or next(iter(by_code.values()), None)

    def build_agent_support_bundle(self, menu_item: BmadMenuItem | None) -> List[tuple[str, str]]:
        if menu_item is None:
            return []

        documents: List[tuple[str, str]] = []
        seen: set[str] = set()

        def add(path: Path | None, label: str | None = None) -> None:
            if path is None or not path.exists():
                return
            key = str(path.resolve())
            if key in seen:
                return
            seen.add(key)
            documents.append((label or key, path.read_text(encoding="utf-8", errors="ignore")))

        if menu_item.exec_path:
            exec_path = self.resolve_path(menu_item.exec_path)
            if exec_path is not None:
                add(exec_path)
                for extra in self._load_markdown_followups(exec_path):
                    add(extra)

        if menu_item.workflow_path:
            workflow_path = self.resolve_path(menu_item.workflow_path)
            if workflow_path is not None:
                add(workflow_path)
                add(self.repo_root / "_bmad" / "core" / "tasks" / "workflow.xml")
                for extra in self._load_yaml_followups(workflow_path):
                    add(extra)

        if menu_item.data_path:
            add(self.resolve_path(menu_item.data_path))

        if menu_item.action:
            documents.append(("inline-action", menu_item.action.strip()))

        return documents

    def load_bmad_config(self) -> Dict[str, str]:
        if self._config_cache is None:
            config_path = self.repo_root / "_bmad" / "bmm" / "config.yaml"
            self._config_cache = self._load_simple_yaml(config_path)
        return dict(self._config_cache)

    def resolve_text(
        self,
        raw_value: str,
        base_dir: Path | None = None,
        variables: Dict[str, str] | None = None,
    ) -> str:
        value = str(raw_value or "").strip()
        if not value:
            return ""

        value = value.strip("`").strip('"').strip("'")
        merged = self._default_variables()
        if variables:
            merged.update({key: str(item) for key, item in variables.items() if item is not None})

        previous = None
        for _ in range(12):
            if value == previous:
                break
            previous = value
            for key, replacement in merged.items():
                value = value.replace(f"{{{key}}}", replacement)
            value = self._resolve_config_reference(value)

        value = self._apply_legacy_aliases(value)
        if base_dir is not None and value and not Path(value).is_absolute():
            value = str((base_dir / value).resolve())
        return value

    def resolve_path(
        self,
        raw_value: str,
        base_dir: Path | None = None,
        variables: Dict[str, str] | None = None,
    ) -> Path | None:
        value = self.resolve_text(raw_value, base_dir=base_dir, variables=variables)
        if not value or value.lower() in {"false", "todo"}:
            return None
        return Path(value)

    def role_summary(self, role: str) -> str:
        curated = {
            "analyst": "Handles requirement analysis and can also run BMAD's Brainstorm Project workflow for raw ideas.",
            "pm": "Shapes product goals, scope, priorities, and PRD quality.",
            "architect": "Leads architecture decisions, system structure, and implementation-readiness checks.",
            "dev": "Builds implementation plans and production-oriented code structure.",
            "qa": "Covers validation, testing strategy, and quality risks.",
            "sm": "Keeps delivery organized, sequenced, and execution-ready.",
            "tech-writer": "Produces clear PRDs, specs, diagrams, and supporting documentation.",
            "ux-designer": "Designs user flows, interface behavior, and UX direction.",
            "quick-flow-solo-dev": "Moves quickly from concept to implementation when lean delivery is needed.",
            "bmad-master": "Coordinates workflows and BMAD operating logic at the platform level.",
        }
        if role in curated:
            return curated[role]
        spec = self.get_agent(role)
        capabilities = [item.strip() for item in spec.capabilities.split(",") if item.strip()]
        if capabilities:
            return f"Focuses on {', '.join(capabilities[:3])}."
        return spec.title or spec.display_name

    def _load_yaml_followups(self, workflow_path: Path) -> List[Path]:
        yaml_data = self._load_simple_yaml(workflow_path)
        variables = dict(yaml_data)
        variables.setdefault("installed_path", str(workflow_path.parent))
        variables.setdefault("config_source", str(self.repo_root / "_bmad" / "bmm" / "config.yaml"))

        followups: List[Path] = []
        for key in ("instructions", "template", "validation", "documentation_requirements_csv"):
            raw_value = yaml_data.get(key, "")
            resolved = self.resolve_path(raw_value, base_dir=workflow_path.parent, variables=variables)
            if resolved is not None:
                followups.append(resolved)
        return followups

    def _load_markdown_followups(self, workflow_path: Path) -> List[Path]:
        content = workflow_path.read_text(encoding="utf-8", errors="ignore")
        frontmatter = self._parse_frontmatter(content)
        variables = dict(frontmatter)
        variables.setdefault("installed_path", str(workflow_path.parent))
        variables.setdefault("project-root", str(self.repo_root))

        followups: List[Path] = []
        patterns = [
            r"Read fully and follow:\s*`([^`]+)`",
            r"Read fully and follow:\s*'([^']+)'",
            r"Read fully and follow:\s*\"([^\"]+)\"",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, content):
                resolved = self.resolve_path(match, base_dir=workflow_path.parent, variables=variables)
                if resolved is not None:
                    followups.append(resolved)

        next_step = frontmatter.get("nextStep", "")
        resolved_next = self.resolve_path(next_step, base_dir=workflow_path.parent, variables=variables)
        if resolved_next is not None:
            followups.append(resolved_next)

        deduped: List[Path] = []
        seen: set[str] = set()
        for item in followups:
            key = str(item.resolve())
            if item.exists() and key not in seen:
                seen.add(key)
                deduped.append(item)
        return deduped

    def _default_variables(self) -> Dict[str, str]:
        variables = self.load_bmad_config()
        variables["project-root"] = str(self.repo_root)
        variables["config_source"] = str(self.repo_root / "_bmad" / "bmm" / "config.yaml")
        return variables

    def _resolve_config_reference(self, value: str) -> str:
        match = re.fullmatch(r"(.+\.ya?ml):([A-Za-z0-9_-]+)", value)
        if not match:
            return value

        config_path = Path(match.group(1))
        field = match.group(2)
        data = self._load_simple_yaml(config_path)
        return data.get(field, value)

    def _load_simple_yaml(self, path: Path) -> Dict[str, str]:
        if not path.exists():
            return {}

        data: Dict[str, str] = {}
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if raw_line.startswith((" ", "\t")):
                continue
            if ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
        return data

    @staticmethod
    def _parse_frontmatter(content: str) -> Dict[str, str]:
        if not content.startswith("---"):
            return {}
        parts = content.split("---", 2)
        if len(parts) < 3:
            return {}
        block = parts[1]
        data: Dict[str, str] = {}
        for raw_line in block.splitlines():
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#") or ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            data[key.strip()] = value.strip().strip('"').strip("'")
        return data

    def _apply_legacy_aliases(self, value: str) -> str:
        resolved = value
        for old, new in self._LEGACY_PATH_ALIASES.items():
            resolved = resolved.replace(old, new)
        return resolved
