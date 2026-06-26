from __future__ import annotations

import re
from typing import Dict, List
from uuid import uuid4

from .agents.adapter import BmadAgentAdapter
from .bmad_catalog import BmadCatalog
from .llm_provider import BaseLLMProvider
from .models import (
    AgentMessage,
    AgentInsight,
    AgentTask,
    Artifact,
    ChatMessage,
    MessageType,
    RunResult,
    TeamConfig,
    TeamConversation,
    VisibleMessageRole,
    WorkflowStep,
)
from .protocol import InMemoryMessageBus


class Director:
    role = "director"
    director_name = "Rhea"

    def __init__(
        self,
        team: TeamConfig,
        workflow: List[WorkflowStep],
        catalog: BmadCatalog,
        bus: InMemoryMessageBus,
        provider: BaseLLMProvider,
    ) -> None:
        self.team = team
        self.workflow = workflow
        self.catalog = catalog
        self.bus = bus
        self.provider = provider
        self.agents = self._build_agents()

    def run(self, requirement: str) -> RunResult:
        run_id = str(uuid4())
        artifacts: List[Artifact] = []
        context = {
            "bmad_agents_count": str(len(self.catalog.agents)),
            "project_mode": "new_project",
        }

        for step in self.workflow:
            owner_roles = [owner_role for owner_role in step.owner_roles if owner_role in self.agents]
            reviewer_roles = [reviewer_role for reviewer_role in step.review_roles if reviewer_role in self.agents]
            last_owner_role = self.role
            last_step_notes = step.objective

            for index, owner_role in enumerate(owner_roles):
                task = AgentTask(
                    run_id=run_id,
                    team_id=self.team.id,
                    workflow_step_id=step.id,
                    owner_role=owner_role,
                    objective=step.objective,
                    requirement=requirement,
                    expected_artifacts=step.expected_artifacts,
                    acceptance_criteria=step.acceptance_criteria,
                    context=context,
                )

                self._send(
                    run_id,
                    MessageType.TASK_ASSIGNMENT if index == 0 else MessageType.HANDOFF,
                    from_role=self.role if index == 0 else owner_roles[index - 1],
                    to_role=owner_role,
                    subject=f"Execute step {step.id}" if index == 0 else f"Continue step {step.id}",
                    body=step.objective if index == 0 else last_step_notes,
                    payload={
                        "expected_artifacts": step.expected_artifacts,
                        "acceptance_criteria": step.acceptance_criteria,
                    },
                )
                result = self.agents[owner_role].execute(task, artifacts)
                artifacts.extend(result.artifacts)
                last_owner_role = owner_role
                last_step_notes = result.notes

                if index + 1 >= len(owner_roles):
                    self._send(
                        run_id,
                        MessageType.INTERMEDIATE_OUTPUT,
                        from_role=owner_role,
                        to_role=self.role,
                        subject=f"Step {step.id} output",
                        body=result.notes,
                        payload={"artifact_ids": [artifact.id for artifact in result.artifacts]},
                    )

            last_review_role = last_owner_role
            last_review_notes = last_step_notes

            for index, reviewer_role in enumerate(reviewer_roles):
                review_task = AgentTask(
                    run_id=run_id,
                    team_id=self.team.id,
                    workflow_step_id=f"{step.id}-review",
                    owner_role=reviewer_role,
                    objective=f"Review outputs of {step.id}",
                    requirement=requirement,
                    expected_artifacts=["SUMMARY"],
                    acceptance_criteria=step.acceptance_criteria,
                    context=context,
                )
                self._send(
                    run_id,
                    MessageType.REVIEW_REQUEST if index == 0 else MessageType.HANDOFF,
                    from_role=last_owner_role if index == 0 else reviewer_roles[index - 1],
                    to_role=reviewer_role,
                    subject=f"Review step {step.id}" if index == 0 else f"Continue review for {step.id}",
                    body="Review and provide feedback summary." if index == 0 else last_review_notes,
                    payload={"step_id": step.id},
                )
                review = self.agents[reviewer_role].execute(review_task, artifacts)
                artifacts.extend(review.artifacts)
                last_review_role = reviewer_role
                last_review_notes = review.notes
                if index + 1 >= len(reviewer_roles):
                    self._send(
                        run_id,
                        MessageType.REVIEW_FEEDBACK,
                        from_role=reviewer_role,
                        to_role=self.role,
                        subject=f"Review feedback for {step.id}",
                        body=review.notes,
                        payload={"artifact_ids": [artifact.id for artifact in review.artifacts]},
                    )

        summary = self._summary(requirement, artifacts)
        self._send(
            run_id,
            MessageType.FINAL_DELIVERY,
            to_role="user",
            subject="Final delivery from Director",
            body=summary,
            payload={"artifact_count": len(artifacts)},
        )

        return RunResult(
            run_id=run_id,
            team_id=self.team.id,
            requirement=requirement,
            summary=summary,
            artifacts=artifacts,
            protocol_trace=self.bus.for_run(run_id),
        )

    def chat(self, session: TeamConversation, user_content: str) -> ChatMessage:
        turn_id = str(uuid4())
        cleaned = user_content.strip()
        user_message = ChatMessage(
            id=str(uuid4()),
            team_id=session.team_id,
            role=VisibleMessageRole.USER,
            speaker_name="You",
            content=cleaned,
        )
        session.add_visible_message(user_message)

        if not session.introduced:
            assistant_message = self._visible_reply(session, self._compose_intro_only_reply(session))
            session.add_visible_message(assistant_message)
            session.add_internal_trace(turn_id=turn_id, trace=[], roles=[])
            session.introduced = True
            session.memory["awaiting_requirement"] = True
            session.memory["consulted_roles"] = []
            session.memory["agent_plan"] = self._available_team_roles(session)
            session.memory["last_selected_roles"] = []
            session.memory["last_intent_tags"] = ["first_turn"]
            return assistant_message

        if self._looks_like_new_requirement(cleaned, session):
            session.memory["awaiting_requirement"] = True
            session.memory["consulted_roles"] = []

        intent_tags = self._intent_tags(cleaned, session)
        if session.memory.get("awaiting_requirement", False) or not session.memory.get("current_requirement"):
            session.memory["current_requirement"] = cleaned
            session.memory["awaiting_requirement"] = False
        session.memory["project_summary"] = self._update_project_summary(session, cleaned)
        requested_role = self._extract_requested_role(cleaned, session)
        plan = self._build_agent_plan(session, cleaned, requested_role=requested_role)
        session.memory["agent_plan"] = plan

        insights = self._run_team_huddle(
            turn_id=turn_id,
            plan=plan,
            user_content=cleaned,
            session=session,
            intent_tags=intent_tags,
        )
        selected_roles = [insight.role for insight in insights]
        session.memory["consulted_roles"] = selected_roles
        reply = self._compose_team_huddle_reply(session, insights)

        assistant_message = self._visible_reply(session, reply)
        session.add_visible_message(assistant_message)
        session.add_internal_trace(turn_id=turn_id, trace=self.bus.for_run(turn_id), roles=selected_roles)
        session.memory["last_selected_roles"] = selected_roles
        session.memory["last_intent_tags"] = intent_tags
        return assistant_message

    def _build_agents(self) -> Dict[str, BmadAgentAdapter]:
        agents: Dict[str, BmadAgentAdapter] = {}
        for entry in self.team.agents:
            role = entry["role"]
            if role == self.role:
                continue
            spec = self.catalog.get_agent(role)
            prompt_excerpt = self.catalog.read_agent_prompt_excerpt(role)
            agents[role] = BmadAgentAdapter(
                role=role,
                spec=spec,
                prompt_excerpt=prompt_excerpt,
                catalog=self.catalog,
                provider=self.provider,
            )
        return agents

    def _intent_tags(self, user_content: str, session: TeamConversation) -> List[str]:
        lowered = user_content.lower()
        tags: List[str] = []
        if any(token in lowered for token in ("continue", "go ahead", "proceed", "keep going", "next", "yes", "sure")):
            previous_tags = list(session.memory.get("last_intent_tags", []))
            for tag in previous_tags:
                if tag not in tags:
                    tags.append(tag)
        keyword_map = {
            "analysis": ("analyze", "analysis", "requirements", "scope", "problem", "research"),
            "planning": ("plan", "roadmap", "prioritize", "sprint", "milestone", "backlog", "epic", "story"),
            "architecture": ("architecture", "system", "microservice", "scalable", "backend", "brainstorm", "idea", "concept"),
            "implementation": ("build", "implement", "code", "develop", "app", "website", "api", "frontend"),
            "ui": ("ui", "ux", "design", "wireframe", "screen", "chat"),
            "quality": ("qa", "test", "validate", "bug", "edge case", "coverage"),
            "documentation": ("prd", "document", "spec", "docs", "writeup"),
        }
        for tag, keywords in keyword_map.items():
            if any(keyword in lowered for keyword in keywords):
                tags.append(tag)
        if not tags:
            tags.extend(["analysis", "planning"])
        return tags

    def _compose_intro_only_reply(self, session: TeamConversation) -> str:
        return (
            self._intro_message(session)
            + "\n\nGive me direction like the company owner. I’ll pull your core BMAD team into an internal sync, let them hand work to one another through the agent2agent protocol, and bring you back one aligned answer."
        )

    def _compose_team_huddle_reply(self, session: TeamConversation, insights: List[AgentInsight]) -> str:
        if not insights:
            return "I understand the direction. I can run it through your BMAD team as soon as you want."

        role_lines = []
        for insight in insights:
            spec = self.catalog.get_agent(insight.role)
            workflow_hint = self._workflow_hint(insight)
            role_lines.append(f"- {spec.display_name} ({spec.title}): {insight.summary}{workflow_hint}")

        recommendations = self._collect_points(insights, key="recommendations", limit=5)
        questions = self._collect_points(insights, key="questions", limit=3)
        plan_label = " -> ".join(self.catalog.get_agent(role).display_name for role in session.memory.get("agent_plan", []))

        paragraphs = [
            "I pulled your BMAD employee team into an internal sync. PM, Architect, Dev, QA, and SM all coordinated through the agent2agent protocol before I answered you.",
            f"Internal handoff line: {plan_label}",
            "Team readout:\n" + "\n".join(role_lines),
        ]
        if recommendations:
            paragraphs.append("What I would drive next:\n" + "\n".join(f"- {item}" for item in recommendations))
        if questions:
            paragraphs.append("What the team still needs from you as the owner:\n" + "\n".join(f"- {item}" for item in questions))
        else:
            paragraphs.append("Reply with any owner-level change in direction and I’ll run the team through another internal sync.")
        return "\n\n".join(paragraphs)

    def _intro_message(self, session: TeamConversation) -> str:
        lines = [
            f"Hi, my name is {self.director_name} and I run your BMAD delivery team.",
            "",
            "Let me introduce your core employees:",
        ]
        for entry in session.agents:
            role = entry["role"]
            if role == self.role:
                continue
            spec = self.catalog.get_agent(role)
            lines.append(f"- {spec.display_name} ({spec.title}): {self.catalog.role_summary(role)}")
        return "\n".join(lines)

    def _consult_role(
        self,
        turn_id: str,
        role: str,
        user_content: str,
        session: TeamConversation,
        intent_tags: List[str],
        from_role: str,
        subject: str,
        body: str,
        collaboration_context: Dict[str, object],
    ) -> AgentInsight:
        agent = self.agents.get(role)
        if agent is None:
            raise KeyError(f"Role '{role}' is not available in this team")
        self._send(
            turn_id,
            MessageType.TASK_ASSIGNMENT if from_role == self.role else MessageType.HANDOFF,
            from_role=from_role,
            to_role=role,
            subject=subject,
            body=body,
            payload={"intent_tags": intent_tags, "collaboration_context": collaboration_context},
        )
        insight = agent.collaborate(
            user_message=user_content,
            recent_messages=session.visible_messages[-8:],
            session_memory=session.memory,
            intent_tags=intent_tags,
            collaboration_context=collaboration_context,
        )
        return insight

    def _run_team_huddle(
        self,
        turn_id: str,
        plan: List[str],
        user_content: str,
        session: TeamConversation,
        intent_tags: List[str],
    ) -> List[AgentInsight]:
        active_plan = [role for role in plan if role in self.agents]
        insights: List[AgentInsight] = []
        upstream_notes: List[Dict[str, object]] = []

        for index, role in enumerate(active_plan):
            sender_role = self.role if index == 0 else active_plan[index - 1]
            handoff_brief = (
                user_content
                if index == 0
                else str(upstream_notes[-1].get("handoff_brief") or upstream_notes[-1].get("summary") or user_content)
            )
            insight = self._consult_role(
                turn_id=turn_id,
                role=role,
                user_content=user_content,
                session=session,
                intent_tags=intent_tags,
                from_role=sender_role,
                subject="Owner request kickoff" if index == 0 else f"{sender_role} employee handoff",
                body=handoff_brief,
                collaboration_context={
                    "from_role": sender_role,
                    "handoff_brief": handoff_brief,
                    "upstream_notes": upstream_notes,
                },
            )
            insights.append(insight)

            note = {
                "role": insight.role,
                "agent_name": insight.agent_name,
                "summary": insight.summary,
                "recommendations": insight.recommendations,
                "questions": insight.questions,
                "handoff_brief": insight.handoff_brief or insight.summary,
            }
            upstream_notes.append(note)

            if index + 1 >= len(active_plan):
                self._send(
                    turn_id,
                    MessageType.INTERMEDIATE_OUTPUT,
                    from_role=role,
                    to_role=self.role,
                    subject=f"{role} internal update",
                    body=insight.handoff_brief or insight.summary,
                    payload={
                        "summary": insight.summary,
                        "recommendations": insight.recommendations,
                        "questions": insight.questions,
                        "selected_menu_command": insight.selected_menu_command,
                        "selected_menu_label": insight.selected_menu_label,
                    },
                )

        session.memory["latest_team_sync"] = [insight.to_dict() for insight in insights]
        return insights

    def _build_agent_plan(
        self,
        session: TeamConversation,
        requirement: str,
        requested_role: str | None = None,
    ) -> List[str]:
        lowered = requirement.lower()
        if any(token in lowered for token in ("idea", "brainstorm", "explore", "unsure", "not sure", "concept")):
            preferred = ["pm", "architect", "dev", "qa", "sm"]
        elif any(token in lowered for token in ("test", "qa", "validate", "coverage")):
            preferred = ["qa", "dev", "architect", "pm", "sm"]
        elif any(token in lowered for token in ("sprint", "plan", "backlog", "milestone")):
            preferred = ["sm", "pm", "architect", "dev", "qa"]
        elif any(token in lowered for token in ("code", "build", "implement", "api", "backend", "frontend", "website", "app")):
            preferred = ["dev", "architect", "qa", "pm", "sm"]
        else:
            preferred = ["pm", "architect", "dev", "qa", "sm"]

        available = self._available_team_roles(session)
        ordered = [role for role in preferred if role in available]
        for role in available:
            if role not in ordered:
                ordered.append(role)
        if requested_role and requested_role in ordered:
            ordered = [requested_role] + [role for role in ordered if role != requested_role]
        return ordered

    def _available_team_roles(self, session: TeamConversation) -> List[str]:
        core_order = ["pm", "architect", "dev", "qa", "sm"]
        available = {entry["role"] for entry in session.agents if entry["role"] != self.role}
        ordered = [role for role in core_order if role in available]
        for role in sorted(available):
            if role not in ordered:
                ordered.append(role)
        return ordered

    def _next_role_in_plan(self, session: TeamConversation) -> str | None:
        plan = list(session.memory.get("agent_plan", []))
        consulted = set(session.memory.get("consulted_roles", []))
        for role in plan:
            if role not in consulted:
                return role
        return None

    def _determine_follow_up_role(self, user_content: str, session: TeamConversation, intent_tags: List[str]) -> str | None:
        explicit = self._extract_requested_role(user_content, session)
        if explicit:
            return explicit

        lowered = user_content.lower()
        if any(token in lowered for token in ("yes", "next", "continue", "go ahead", "proceed", "bring in next", "talk to next")):
            return self._next_role_in_plan(session)

        if any(token in lowered for token in ("same agent", "stay here", "keep with this agent")):
            consulted = list(session.memory.get("consulted_roles", []))
            return consulted[-1] if consulted else self._next_role_in_plan(session)

        consulted = list(session.memory.get("consulted_roles", []))
        if consulted:
            return consulted[-1]
        return self._next_role_in_plan(session)

    def _extract_requested_role(self, user_content: str, session: TeamConversation) -> str | None:
        lowered = user_content.lower()
        aliases = {
            "analyst": ("analyst", "analysis", "mary", "requirements", "brainstormer", "brainstorming"),
            "architect": ("architect", "ideation", "winston"),
            "pm": ("pm", "product manager", "john", "epic", "epics", "priorities"),
            "tech-writer": ("tech writer", "technical writer", "writer", "docs", "documentation", "paige"),
            "ux-designer": ("ux", "ui designer", "designer", "sally"),
            "dev": ("developer", "dev", "engineer", "amelia"),
            "qa": ("qa", "tester", "test engineer", "quinn"),
            "sm": ("scrum", "scrum master", "bob"),
        }
        available = {entry["role"] for entry in session.agents if entry["role"] != self.role}
        for role, keywords in aliases.items():
            if role not in available:
                continue
            if any(keyword in lowered for keyword in keywords):
                return role
        return None

    def _looks_like_new_requirement(self, user_content: str, session: TeamConversation) -> bool:
        if not session.memory.get("current_requirement"):
            return False
        lowered = user_content.lower()
        return any(token in lowered for token in ("new requirement", "another requirement", "different requirement", "new idea", "start over"))

    @staticmethod
    def _update_project_summary(session: TeamConversation, user_content: str) -> str:
        earlier = session.memory.get("project_summary", "")
        trimmed = user_content.strip().replace("\n", " ")
        if not earlier:
            return trimmed[:280]
        merged = f"{earlier} | {trimmed}"
        return merged[-560:]

    def _visible_reply(self, session: TeamConversation, content: str) -> ChatMessage:
        return ChatMessage(
            id=str(uuid4()),
            team_id=session.team_id,
            role=VisibleMessageRole.DIRECTOR,
            speaker_name=self.director_name,
            content=content,
        )

    @staticmethod
    def _workflow_hint(insight: AgentInsight) -> str:
        label = insight.selected_menu_label.strip()
        command = insight.selected_menu_command.strip()
        if not label or command == "CH":
            return ""
        cleaned = re.sub(r"^\[[A-Z-]+\]\s*", "", label).strip()
        return f" I’m using the BMAD {cleaned} flow for this handoff."

    def _send(
        self,
        run_id: str,
        msg_type: MessageType,
        to_role: str,
        subject: str,
        body: str,
        payload: Dict[str, object] | None = None,
        from_role: str | None = None,
    ) -> None:
        msg = AgentMessage(
            id=str(uuid4()),
            run_id=run_id,
            type=msg_type,
            from_role=from_role or self.role,
            to_role=to_role,
            subject=subject,
            body=body,
            payload=payload or {},
        )
        self.bus.send(msg)

    @staticmethod
    def _summary(requirement: str, artifacts: List[Artifact]) -> str:
        by_type: Dict[str, int] = {}
        by_role: Dict[str, int] = {}
        for artifact in artifacts:
            by_type[artifact.type.value] = by_type.get(artifact.type.value, 0) + 1
            by_role[artifact.produced_by] = by_role.get(artifact.produced_by, 0) + 1

        lines = [
            "Director run completed.",
            f"Requirement: {requirement}",
            "Artifacts by type:",
        ]
        for artifact_type, count in sorted(by_type.items()):
            lines.append(f"- {artifact_type}: {count}")
        lines.append("Artifacts by BMAD role:")
        for role, count in sorted(by_role.items()):
            lines.append(f"- {role}: {count}")
        return "\n".join(lines)

    @staticmethod
    def _collect_points(insights: List[AgentInsight], key: str, limit: int) -> List[str]:
        points: List[str] = []
        seen: set[str] = set()
        for insight in insights:
            raw_items = getattr(insight, key, [])
            for item in raw_items:
                cleaned = item.strip()
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                points.append(cleaned)
                if len(points) >= limit:
                    return points
        return points
