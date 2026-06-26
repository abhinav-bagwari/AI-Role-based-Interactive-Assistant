from __future__ import annotations

from typing import List

from .models import AgentMessage


class ProtocolError(ValueError):
    pass


class InMemoryMessageBus:
    def __init__(self) -> None:
        self._messages: List[AgentMessage] = []

    def send(self, message: AgentMessage) -> None:
        if not message.run_id:
            raise ProtocolError("run_id is required")
        if not message.from_role:
            raise ProtocolError("from_role is required")
        if not message.to_role:
            raise ProtocolError("to_role is required")
        if not message.subject:
            raise ProtocolError("subject is required")
        if not message.body:
            raise ProtocolError("body is required")
        self._messages.append(message)

    def for_run(self, run_id: str) -> List[AgentMessage]:
        return [message for message in self._messages if message.run_id == run_id]
