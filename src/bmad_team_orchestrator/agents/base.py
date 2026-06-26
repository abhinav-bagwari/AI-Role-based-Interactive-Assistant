from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import uuid4
from typing import Dict, List

from ..models import AgentResult, AgentTask, Artifact, ArtifactType


class BaseAgent(ABC):
    role = "base"

    @abstractmethod
    def execute(self, task: AgentTask, existing_artifacts: List[Artifact]) -> AgentResult:
        raise NotImplementedError

    def _artifact(
        self,
        task: AgentTask,
        artifact_type: ArtifactType,
        title: str,
        content: str,
        depends_on: List[str] | None = None,
        metadata: Dict[str, str] | None = None,
    ) -> Artifact:
        return Artifact(
            id=str(uuid4()),
            run_id=task.run_id,
            produced_by=self.role,
            type=artifact_type,
            title=title,
            content=content,
            depends_on=depends_on or [],
            metadata=metadata or {},
        )
