from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List
from copy import deepcopy

from .bmad_catalog import BmadCatalog
from .director import Director
from .llm_provider import BaseLLMProvider, build_provider_from_env
from .models import ChatMessage, RunResult, TeamConfig, TeamConversation, WorkflowStep
from .protocol import InMemoryMessageBus


class BmadTeamRuntime:
    def __init__(self, repo_root: Path, provider: BaseLLMProvider | None = None) -> None:
        self.repo_root = repo_root
        self.project_root = repo_root / "bmad-team-orchestrator"
        self.config_root = self.project_root / "config"
        self.catalog = BmadCatalog(repo_root=repo_root)
        self.provider = provider or build_provider_from_env()
        self.teams = self._load_teams()
        self.conversations = self._build_conversations()
        self.runs: Dict[str, RunResult] = {}

    def list_teams(self) -> List[Dict[str, object]]:
        return [conversation.public_summary() for conversation in self.conversations.values()]

    def list_bmad_agents(self) -> List[Dict[str, str]]:
        return self.catalog.list_agents()

    def runtime_status(self) -> Dict[str, object]:
        return self.provider.status().to_dict()

    def get_conversation(self, team_id: str) -> Dict[str, object]:
        session = self._get_session(team_id)
        payload = session.conversation_payload()
        payload["runtime"] = self._runtime_payload(session)
        return payload

    def rename_team(self, team_id: str, new_name: str) -> Dict[str, object]:
        cleaned = new_name.strip()
        if not cleaned:
            raise ValueError("Team name cannot be empty")
        session = self._get_session(team_id)
        session.rename(cleaned)
        self.teams[team_id].name = cleaned
        return session.public_summary()

    def send_message(self, team_id: str, content: str) -> Dict[str, object]:
        message = content.strip()
        if not message:
            raise ValueError("Message cannot be empty")
        session = self._get_session(team_id)
        workflow = self._load_workflow(self.teams[team_id].workflow_id)
        bus = InMemoryMessageBus()
        director = Director(
            team=self.teams[team_id],
            workflow=workflow,
            catalog=self.catalog,
            bus=bus,
            provider=self.provider,
        )
        assistant_message = director.chat(session=session, user_content=message)
        return {
            "team": session.public_summary(),
            "runtime": self._runtime_payload(session),
            "assistant_message": assistant_message.to_dict(),
            "messages": [visible_message.to_dict() for visible_message in session.visible_messages],
            "internal_traces": session.internal_traces[-12:],
            "latest_internal_trace": session.internal_traces[-1] if session.internal_traces else None,
        }

    def execute(self, team_id: str, requirement: str) -> RunResult:
        if team_id not in self.teams:
            raise KeyError(f"Unknown team id '{team_id}'")
        team = self.teams[team_id]
        workflow = self._load_workflow(team.workflow_id)
        bus = InMemoryMessageBus()
        director = Director(team=team, workflow=workflow, catalog=self.catalog, bus=bus, provider=self.provider)
        result = director.run(requirement=requirement)
        self.runs[result.run_id] = result
        return result

    def get_run(self, run_id: str) -> Dict[str, object]:
        if run_id not in self.runs:
            raise KeyError(f"Unknown run id '{run_id}'")
        return self.runs[run_id].to_dict()

    def _load_teams(self) -> Dict[str, TeamConfig]:
        teams: Dict[str, TeamConfig] = {}
        teams_dir = self.config_root / "teams"
        for file in sorted(teams_dir.glob("*.json")):
            team = TeamConfig.from_dict(json.loads(file.read_text(encoding="utf-8")))
            self._validate_team(team)
            teams[team.id] = team
        return teams

    def _validate_team(self, team: TeamConfig) -> None:
        for agent in team.agents:
            role = agent["role"]
            if role == "director":
                continue
            self.catalog.get_agent(role)

    def _build_conversations(self) -> Dict[str, TeamConversation]:
        conversations: Dict[str, TeamConversation] = {}
        for team in self.teams.values():
            conversations[team.id] = TeamConversation(
                team_id=team.id,
                name=team.name,
                workflow_id=team.workflow_id,
                collaboration_style=team.collaboration_style,
                agents=deepcopy(team.agents),
            )
        return conversations

    def _load_workflow(self, workflow_id: str) -> List[WorkflowStep]:
        file = self.config_root / "workflows" / f"{workflow_id}.json"
        if not file.exists():
            raise FileNotFoundError(f"Workflow not found: {file}")
        data = json.loads(file.read_text(encoding="utf-8"))
        return [WorkflowStep.from_dict(item) for item in data.get("steps", [])]

    def _get_session(self, team_id: str) -> TeamConversation:
        if team_id not in self.conversations:
            raise KeyError(f"Unknown team id '{team_id}'")
        return self.conversations[team_id]

    def _runtime_payload(self, session: TeamConversation | None = None) -> Dict[str, object]:
        payload = self.runtime_status()
        if session is None:
            return payload

        error = session.memory.get("provider_last_error")
        if error:
            payload = dict(payload)
            payload["mode"] = "fallback"
            payload["ready"] = False
            payload["reason"] = f"Live BMAD provider failed, so this conversation fell back locally. {error}"
        return payload
