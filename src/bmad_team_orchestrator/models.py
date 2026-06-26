from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


class MessageType(str, Enum):
    TASK_ASSIGNMENT = "TASK_ASSIGNMENT"
    HANDOFF = "HANDOFF"
    INTERMEDIATE_OUTPUT = "INTERMEDIATE_OUTPUT"
    CLARIFICATION_REQUEST = "CLARIFICATION_REQUEST"
    REVIEW_REQUEST = "REVIEW_REQUEST"
    REVIEW_FEEDBACK = "REVIEW_FEEDBACK"
    FINAL_DELIVERY = "FINAL_DELIVERY"


class ArtifactType(str, Enum):
    PRD = "PRD"
    DOCUMENTATION = "DOCUMENTATION"
    ARCHITECTURE = "ARCHITECTURE"
    API_DEFINITION = "API_DEFINITION"
    CODE = "CODE"
    TEST_PLAN = "TEST_PLAN"
    DEPLOYMENT = "DEPLOYMENT"
    UX = "UX"
    SPRINT_PLAN = "SPRINT_PLAN"
    SUMMARY = "SUMMARY"


class VisibleMessageRole(str, Enum):
    USER = "user"
    DIRECTOR = "director"


@dataclass
class AgentMessage:
    id: str
    run_id: str
    type: MessageType
    from_role: str
    to_role: str
    subject: str
    body: str
    payload: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "type": self.type.value,
            "from_role": self.from_role,
            "to_role": self.to_role,
            "subject": self.subject,
            "body": self.body,
            "payload": self.payload,
            "created_at": self.created_at,
        }


@dataclass
class AgentTask:
    run_id: str
    team_id: str
    workflow_step_id: str
    owner_role: str
    objective: str
    requirement: str
    expected_artifacts: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Artifact:
    id: str
    run_id: str
    produced_by: str
    type: ArtifactType
    title: str
    content: str
    depends_on: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "produced_by": self.produced_by,
            "type": self.type.value,
            "title": self.title,
            "content": self.content,
            "depends_on": self.depends_on,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


@dataclass
class AgentResult:
    role: str
    artifacts: List[Artifact] = field(default_factory=list)
    follow_up_questions: List[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class WorkflowStep:
    id: str
    objective: str
    owner_roles: List[str]
    review_roles: List[str] = field(default_factory=list)
    expected_artifacts: List[str] = field(default_factory=list)
    acceptance_criteria: List[str] = field(default_factory=list)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "WorkflowStep":
        return WorkflowStep(
            id=data["id"],
            objective=data["objective"],
            owner_roles=list(data.get("owner_roles", [])),
            review_roles=list(data.get("review_roles", [])),
            expected_artifacts=list(data.get("expected_artifacts", [])),
            acceptance_criteria=list(data.get("acceptance_criteria", [])),
        )


@dataclass
class TeamConfig:
    id: str
    name: str
    director_role: str
    workflow_id: str
    agents: List[Dict[str, str]]
    collaboration_style: str = "iterative"

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "TeamConfig":
        return TeamConfig(
            id=data["id"],
            name=data["name"],
            director_role=data.get("director_role", "director"),
            workflow_id=data["workflow_id"],
            agents=list(data.get("agents", [])),
            collaboration_style=data.get("collaboration_style", "iterative"),
        )


@dataclass
class RunResult:
    run_id: str
    team_id: str
    requirement: str
    summary: str
    artifacts: List[Artifact]
    protocol_trace: List[AgentMessage]
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "team_id": self.team_id,
            "requirement": self.requirement,
            "summary": self.summary,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "protocol_trace": [message.to_dict() for message in self.protocol_trace],
            "created_at": self.created_at,
        }


@dataclass
class ChatMessage:
    id: str
    team_id: str
    role: VisibleMessageRole
    speaker_name: str
    content: str
    created_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "team_id": self.team_id,
            "role": self.role.value,
            "speaker_name": self.speaker_name,
            "content": self.content,
            "created_at": self.created_at,
        }


@dataclass
class AgentInsight:
    role: str
    agent_name: str
    summary: str
    recommendations: List[str] = field(default_factory=list)
    questions: List[str] = field(default_factory=list)
    handoff_brief: str = ""
    selected_menu_command: str = ""
    selected_menu_label: str = ""
    handoff_suggestion: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "agent_name": self.agent_name,
            "summary": self.summary,
            "recommendations": self.recommendations,
            "questions": self.questions,
            "handoff_brief": self.handoff_brief,
            "selected_menu_command": self.selected_menu_command,
            "selected_menu_label": self.selected_menu_label,
            "handoff_suggestion": self.handoff_suggestion,
        }


@dataclass
class TeamConversation:
    team_id: str
    name: str
    workflow_id: str
    collaboration_style: str
    agents: List[Dict[str, str]]
    visible_messages: List[ChatMessage] = field(default_factory=list)
    internal_traces: List[Dict[str, Any]] = field(default_factory=list)
    introduced: bool = False
    director_name: str = "Rhea"
    memory: Dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=utc_now_iso)

    def rename(self, new_name: str) -> None:
        self.name = new_name
        self.updated_at = utc_now_iso()

    def add_visible_message(self, message: ChatMessage) -> None:
        self.visible_messages.append(message)
        self.updated_at = utc_now_iso()

    def add_internal_trace(self, turn_id: str, trace: List[AgentMessage], roles: List[str]) -> None:
        self.internal_traces.append(
            {
                "turn_id": turn_id,
                "roles": roles,
                "messages": [message.to_dict() for message in trace],
                "created_at": utc_now_iso(),
            }
        )
        self.updated_at = utc_now_iso()

    def public_summary(self) -> Dict[str, Any]:
        last_preview = ""
        if self.visible_messages:
            last_preview = self.visible_messages[-1].content.replace("\n", " ").strip()[:120]
        return {
            "id": self.team_id,
            "name": self.name,
            "workflow_id": self.workflow_id,
            "collaboration_style": self.collaboration_style,
            "agents": self.agents,
            "message_count": len(self.visible_messages),
            "last_message_preview": last_preview,
            "updated_at": self.updated_at,
        }

    def conversation_payload(self) -> Dict[str, Any]:
        return {
            "team": self.public_summary(),
            "messages": [message.to_dict() for message in self.visible_messages],
            "internal_traces": self.internal_traces[-12:],
            "latest_internal_trace": self.internal_traces[-1] if self.internal_traces else None,
        }
