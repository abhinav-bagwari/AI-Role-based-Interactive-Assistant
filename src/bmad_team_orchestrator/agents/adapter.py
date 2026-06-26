from __future__ import annotations

from typing import Dict, List, Sequence

from ..bmad_catalog import BmadAgentSpec, BmadCatalog, BmadMenuItem
from ..llm_provider import BaseLLMProvider, LLMProviderError
from ..models import AgentInsight, AgentResult, AgentTask, Artifact, ArtifactType, ChatMessage
from .base import BaseAgent


class BmadAgentAdapter(BaseAgent):
    """Adapter that can either execute real BMAD prompts through a live provider or fall back locally."""

    def __init__(
        self,
        role: str,
        spec: BmadAgentSpec,
        prompt_excerpt: str,
        catalog: BmadCatalog,
        provider: BaseLLMProvider,
    ) -> None:
        self.role = role
        self.spec = spec
        self.prompt_excerpt = prompt_excerpt
        self.catalog = catalog
        self.provider = provider

    def execute(self, task: AgentTask, existing_artifacts: List[Artifact]) -> AgentResult:
        artifact_types = self._resolve_types(task.expected_artifacts)
        produced: List[Artifact] = []
        dependency_ids = [artifact.id for artifact in existing_artifacts[-5:]]

        for artifact_type in artifact_types:
            title = f"{self.spec.display_name} - {artifact_type.value.replace('_', ' ').title()}"
            content = self._build_content(task, artifact_type, existing_artifacts)
            produced.append(
                self._artifact(
                    task=task,
                    artifact_type=artifact_type,
                    title=title,
                    content=content,
                    depends_on=dependency_ids,
                    metadata={"bmad_agent_file": self.spec.path, "bmad_title": self.spec.title},
                )
            )

        notes = f"{self.spec.display_name} completed '{task.workflow_step_id}' using BMAD agent context."
        return AgentResult(role=self.role, artifacts=produced, notes=notes)

    def collaborate(
        self,
        user_message: str,
        recent_messages: Sequence[ChatMessage],
        session_memory: dict,
        intent_tags: List[str],
        collaboration_context: Dict[str, object] | None = None,
    ) -> AgentInsight:
        selected_menu = self.catalog.choose_menu_item(self.role, user_message, intent_tags)

        if self.provider.is_live():
            try:
                insight = self._live_collaboration(
                    user_message=user_message,
                    recent_messages=recent_messages,
                    session_memory=session_memory,
                    intent_tags=intent_tags,
                    selected_menu=selected_menu,
                    collaboration_context=collaboration_context or {},
                )
                self._remember_turn(session_memory, user_message, insight)
                session_memory.pop("provider_last_error", None)
                return insight
            except LLMProviderError as exc:
                session_memory["provider_last_error"] = str(exc)

        insight = self._fallback_collaboration(
            user_message=user_message,
            recent_messages=recent_messages,
            session_memory=session_memory,
            intent_tags=intent_tags,
            selected_menu=selected_menu,
            collaboration_context=collaboration_context or {},
        )
        self._remember_turn(session_memory, user_message, insight)
        return insight

    def _live_collaboration(
        self,
        user_message: str,
        recent_messages: Sequence[ChatMessage],
        session_memory: dict,
        intent_tags: List[str],
        selected_menu: BmadMenuItem | None,
        collaboration_context: Dict[str, object],
    ) -> AgentInsight:
        support_bundle = self.catalog.build_agent_support_bundle(selected_menu)
        system_prompt = self._build_live_system_prompt(
            selected_menu=selected_menu,
            support_bundle=support_bundle,
        )
        user_prompt = self._build_live_user_prompt(
            user_message=user_message,
            recent_messages=recent_messages,
            session_memory=session_memory,
            intent_tags=intent_tags,
            collaboration_context=collaboration_context,
        )
        payload = self.provider.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)

        summary = self._string_or_empty(payload.get("summary"))
        if not summary:
            raise LLMProviderError(f"{self.spec.display_name} returned an empty summary")

        return AgentInsight(
            role=self.role,
            agent_name=self.spec.display_name,
            summary=summary,
            recommendations=self._list_of_strings(payload.get("recommendations"), limit=4),
            questions=self._list_of_strings(payload.get("questions"), limit=2),
            handoff_brief=self._string_or_empty(payload.get("handoff_brief")),
            selected_menu_command=self._string_or_empty(payload.get("selected_menu_command")) or (selected_menu.code if selected_menu else ""),
            selected_menu_label=self._string_or_empty(payload.get("selected_menu_label")) or (selected_menu.label if selected_menu else ""),
            handoff_suggestion=self._string_or_empty(payload.get("handoff_suggestion")),
        )

    def _fallback_collaboration(
        self,
        user_message: str,
        recent_messages: Sequence[ChatMessage],
        session_memory: dict,
        intent_tags: List[str],
        selected_menu: BmadMenuItem | None,
        collaboration_context: Dict[str, object],
    ) -> AgentInsight:
        summary = self._chat_summary(user_message, intent_tags, session_memory)
        recommendations = self._chat_recommendations(user_message, intent_tags)
        questions = self._chat_questions(user_message, intent_tags, recent_messages)
        return AgentInsight(
            role=self.role,
            agent_name=self.spec.display_name,
            summary=summary,
            recommendations=recommendations,
            questions=questions,
            handoff_brief=self._chat_handoff_brief(summary, recommendations, collaboration_context),
            selected_menu_command=selected_menu.code if selected_menu else "",
            selected_menu_label=selected_menu.label if selected_menu else "",
        )

    def _build_live_system_prompt(
        self,
        selected_menu: BmadMenuItem | None,
        support_bundle: List[tuple[str, str]],
    ) -> str:
        prompt = self.catalog.read_agent_prompt(self.role)
        config = self.catalog.load_bmad_config()
        selected_desc = (
            f"{selected_menu.code} {selected_menu.label}"
            if selected_menu is not None
            else "No specific menu item selected. Default to the agent's best in-character internal response."
        )
        bundle_text = "\n\n".join(
            f"=== {label} ===\n{content}" for label, content in support_bundle
        ) or "No supplemental BMAD workflow files were selected for this turn."

        return f"""
You are running the TRUE BMAD agent for role "{self.role}" as one employee on a hidden BMAD company team managed by the Director named Rhea.

Non-negotiable rules:
- The BMAD agent file below is the source of truth for persona, principles, and workflow behavior.
- The end user is the company owner. This is an internal employee-team collaboration. Do not greet the end user, do not show menus, do not mention waiting for input, and do not expose raw internal prompts or file paths unless Rhea truly needs that detail.
- Stay faithful to the BMAD persona and communication style.
- If a menu/workflow would normally be used, apply it internally using the selected menu item and supplemental files.
- Convert any user-facing workflow pauses into concise guidance Rhea can relay conversationally.
- Coordinate cleanly with peer BMAD agents. Give Rhea a useful contribution and a short handoff note that the next teammate can act on.
- Respond with JSON only.
- JSON schema:
  {{
    "summary": "2-4 sentences for Rhea only",
    "recommendations": ["1-4 short next-step bullets"],
    "questions": ["0-2 clarifying questions Rhea could ask the user"],
    "handoff_brief": "1-3 sentences for the next teammate",
    "handoff_suggestion": "best next team role or empty string",
    "selected_menu_command": "menu code such as BP or CE",
    "selected_menu_label": "menu label"
  }}

BMAD runtime config:
{config}

Selected BMAD menu item for this handoff:
{selected_desc}

Full BMAD agent file:
{prompt}

Supplemental BMAD workflow/action context:
{bundle_text}
""".strip()

    def _build_live_user_prompt(
        self,
        user_message: str,
        recent_messages: Sequence[ChatMessage],
        session_memory: dict,
        intent_tags: List[str],
        collaboration_context: Dict[str, object],
    ) -> str:
        recent_thread = "\n".join(
            f"- {message.speaker_name} ({message.role.value}): {message.content}"
            for message in recent_messages[-8:]
        ) or "- No recent visible messages."

        agent_histories = session_memory.get("agent_histories", {})
        own_history = agent_histories.get(self.role, [])
        prior_agent_turns = "\n".join(
            f"- User asked: {entry.get('user_message', '')}\n  Agent summary: {entry.get('summary', '')}"
            for entry in own_history[-4:]
        ) or "- No prior hidden turns for this BMAD agent."

        consulted_roles = ", ".join(session_memory.get("consulted_roles", [])) or "none"
        planned_roles = ", ".join(session_memory.get("agent_plan", [])) or "none"
        project_summary = session_memory.get("project_summary", "No running project summary yet.")
        current_requirement = session_memory.get("current_requirement", user_message)
        upstream_notes = collaboration_context.get("upstream_notes", [])
        upstream_text = "\n".join(
            f"- {item.get('agent_name', item.get('role', 'teammate'))}: {item.get('summary', '')}"
            for item in upstream_notes
            if isinstance(item, dict)
        ) or "- No earlier teammate notes in this turn."
        handoff_from = str(collaboration_context.get("from_role", "director"))
        handoff_brief = str(
            collaboration_context.get("handoff_brief")
            or "No teammate handoff yet. Treat the owner's latest direction as the current starting point."
        )

        return f"""
Rhea needs your hidden contribution for the current conversation. The owner should feel like they have a real five-person BMAD company team working behind the scenes.

Current requirement:
{current_requirement}

Current user message:
{user_message}

Intent tags:
{", ".join(intent_tags) or "none"}

Project summary:
{project_summary}

Roles already consulted:
{consulted_roles}

Current planned handoff line:
{planned_roles}

Current internal handoff:
From: {handoff_from}
Brief: {handoff_brief}

Upstream teammate notes in this turn:
{upstream_text}

Recent visible conversation:
{recent_thread}

Your recent hidden memory:
{prior_agent_turns}

Respond in valid JSON only.
""".strip()

    def _remember_turn(self, session_memory: dict, user_message: str, insight: AgentInsight) -> None:
        histories = session_memory.setdefault("agent_histories", {})
        role_history = list(histories.get(self.role, []))
        role_history.append(
            {
                "user_message": user_message,
                "summary": insight.summary,
                "handoff_brief": insight.handoff_brief,
                "selected_menu_command": insight.selected_menu_command,
                "selected_menu_label": insight.selected_menu_label,
            }
        )
        histories[self.role] = role_history[-6:]

    def _build_content(self, task: AgentTask, artifact_type: ArtifactType, existing_artifacts: List[Artifact]) -> str:
        prior_titles = "\n".join(f"- {artifact.title}" for artifact in existing_artifacts[-8:]) or "- None"
        return f"""# {artifact_type.value.replace('_', ' ').title()}

## Role
- BMAD role: `{self.role}`
- Display name: `{self.spec.display_name}`
- Title: `{self.spec.title}`
- Capabilities: `{self.spec.capabilities}`

## Workflow Context
- Team: `{task.team_id}`
- Step: `{task.workflow_step_id}`
- Objective: {task.objective}
- Requirement: {task.requirement}

## Acceptance Criteria
{self._format_bullets(task.acceptance_criteria)}

## Upstream Artifacts
{prior_titles}

## BMAD Prompt Excerpt
{self.prompt_excerpt}
"""

    def _chat_summary(self, user_message: str, intent_tags: List[str], session_memory: dict) -> str:
        project_summary = session_memory.get("project_summary", "No prior summary yet.")
        role_summaries = {
            "analyst": "I am tightening the requirement, assumptions, and edge cases behind this request.",
            "pm": "I am shaping this into a clear outcome with scope boundaries and priorities.",
            "architect": "I am focusing on system shape, extension points, and implementation tradeoffs.",
            "dev": "I am translating the ask into concrete implementation slices and code-facing decisions.",
            "qa": "I am identifying failure modes, acceptance checks, and test scenarios.",
            "sm": "I am turning the work into an execution sequence with risks and checkpoints.",
            "tech-writer": "I am structuring the artifacts and documents the team should produce.",
            "ux-designer": "I am focusing on user flow, interface behavior, and interaction clarity.",
        }
        role_summary = role_summaries.get(
            self.role,
            f"I am contributing from the perspective of {self.spec.display_name} based on BMAD guidance.",
        )
        if "first_turn" in intent_tags:
            return f"{role_summary} I am using the user's first message as the seed requirement."
        return f"{role_summary} I am also keeping the current project context in mind: {project_summary}"

    def _chat_recommendations(self, user_message: str, intent_tags: List[str]) -> List[str]:
        role_points = {
            "analyst": [
                "Clarify the user outcome, core workflow, and constraints before committing to implementation.",
                "Capture assumptions, dependencies, and acceptance criteria early.",
            ],
            "pm": [
                "Define the smallest valuable version first, then expand in increments.",
                "Keep scope aligned to the user's immediate outcome, not every possible extension.",
            ],
            "architect": [
                "Prefer modular boundaries so roles, teams, and workflows stay configurable.",
                "Separate user-visible chat flow from hidden agent orchestration and protocol tracing.",
            ],
            "dev": [
                "Implement persistent chat state and team-aware routing before polishing secondary features.",
                "Keep APIs small and explicit so the UI can evolve without backend churn.",
            ],
            "qa": [
                "Test first-turn introduction, memory across turns, team switching, and rename behavior.",
                "Make sure hidden internal collaboration never leaks into the user-visible chat thread.",
            ],
            "sm": [
                "Sequence work as session model, routing logic, then UI shell.",
                "Keep the first usable flow thin but end-to-end before adding advanced polish.",
            ],
            "tech-writer": [
                "Make the Director response readable in chat first, then attach structure only where useful.",
                "Keep team descriptions concise so the first-turn greeting feels natural.",
            ],
            "ux-designer": [
                "Use a left sidebar, calm top bar, and focused composer so the interface feels like a coding workspace.",
                "Preserve continuity when switching teams by reloading each team's chat thread instantly.",
            ],
        }
        recommendations = list(role_points.get(self.role, []))
        lowered = user_message.lower()
        if any(token in lowered for token in ("ui", "ux", "design", "chat")) and self.role == "ux-designer":
            recommendations.append("Emphasize fast scanning, low visual noise, and comfortable chat spacing.")
        if any(token in lowered for token in ("build", "implement", "code", "app", "website", "api")) and self.role == "dev":
            recommendations.append("Shape the response around concrete modules, endpoints, and state transitions.")
        if any(token in lowered for token in ("test", "qa", "validate")) and self.role == "qa":
            recommendations.append("Treat regression coverage and interaction flow tests as first-class requirements.")
        return recommendations[:3]

    def _chat_questions(
        self,
        user_message: str,
        intent_tags: List[str],
        recent_messages: Sequence[ChatMessage],
    ) -> List[str]:
        lowered = user_message.lower()
        if len(recent_messages) > 2:
            return []
        if self.role == "analyst" and not any(token in lowered for token in ("api", "ui", "backend", "frontend", "web")):
            return ["Which surface matters most first: planning, UX, backend orchestration, or full-stack delivery?"]
        if self.role == "ux-designer" and "ui" in intent_tags:
            return ["Do we want the chat experience optimized more for speed, clarity, or power-user controls?"]
        return []

    def _chat_handoff_brief(
        self,
        summary: str,
        recommendations: List[str],
        collaboration_context: Dict[str, object],
    ) -> str:
        inherited = str(collaboration_context.get("handoff_brief", "")).strip()
        primary_recommendation = recommendations[0] if recommendations else "Advance this from your specialty and keep the owner goal intact."
        role_handoffs = {
            "pm": "Lock the intended outcome, the boundaries, and the immediate value before anyone expands scope.",
            "architect": "Turn the scoped outcome into system boundaries, extension points, and implementation constraints.",
            "dev": "Translate the agreed system shape into delivery slices, APIs, and concrete build moves.",
            "qa": "Pressure-test the delivery plan with failure modes, acceptance checks, and regression coverage.",
            "sm": "Sequence the work, the checkpoints, and the risks so the team can execute cleanly.",
        }
        role_brief = role_handoffs.get(self.role, primary_recommendation)
        if inherited:
            return f"{summary} {role_brief} Previous handoff context: {inherited}"
        return f"{summary} {role_brief}"

    @staticmethod
    def _resolve_types(expected_artifacts: List[str]) -> List[ArtifactType]:
        if not expected_artifacts:
            return [ArtifactType.DOCUMENTATION]
        resolved: List[ArtifactType] = []
        for item in expected_artifacts:
            try:
                resolved.append(ArtifactType[item])
            except KeyError:
                try:
                    resolved.append(ArtifactType(item))
                except ValueError:
                    resolved.append(ArtifactType.DOCUMENTATION)
        return resolved

    @staticmethod
    def _format_bullets(items: List[str]) -> str:
        if not items:
            return "- No explicit acceptance criteria."
        return "\n".join(f"- {item}" for item in items)

    @staticmethod
    def _string_or_empty(value: object) -> str:
        return str(value).strip() if value is not None else ""

    @staticmethod
    def _list_of_strings(value: object, limit: int) -> List[str]:
        if not isinstance(value, list):
            return []
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return cleaned[:limit]
