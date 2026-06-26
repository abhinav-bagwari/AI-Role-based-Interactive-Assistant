from __future__ import annotations

from typing import Protocol


ARIA_BMAD_ROLE_MAP = {
    "rhea": "bmad-master",
    "marcus": "pm",
    "zara": "ux-designer",
    "kai": "dev",
    "priya": "architect",
    "nox": "qa",
}

MAX_BMAD_PROMPT_CHARS = 7000


class AgentCatalog(Protocol):
    def get_agent(self, role: str):
        ...

    def read_agent_prompt(self, role: str) -> str:
        ...


def resolve_aria_bmad_role(agent_id: str | None) -> str:
    return ARIA_BMAD_ROLE_MAP.get(str(agent_id or "").strip().lower(), "")


def build_aria_agent_system_prompt(
    *,
    base_system_prompt: str,
    catalog: AgentCatalog,
    agent_id: str | None,
    agent_name: str = "",
    agent_role: str = "",
    mode: str = "",
    phase_label: str = "",
    max_prompt_chars: int = MAX_BMAD_PROMPT_CHARS,
) -> tuple[str, str]:
    """Attach BMAD specialist context to an ARIA live-model turn."""
    bmad_role = resolve_aria_bmad_role(agent_id)
    if not bmad_role:
        return base_system_prompt, ""

    try:
        spec = catalog.get_agent(bmad_role)
        source_prompt = catalog.read_agent_prompt(bmad_role)
    except (KeyError, FileNotFoundError, OSError):
        return base_system_prompt, ""

    excerpt = source_prompt[:max_prompt_chars].strip()
    if len(source_prompt) > max_prompt_chars:
        excerpt += "\n\n[BMAD source prompt truncated for this turn.]"

    overlay = f"""
BMAD specialist backing for this live ARIA turn:
- ARIA agent: {agent_name or agent_id or "unknown"} ({agent_role or "role not provided"})
- Conversation mode: {mode or "team"}
- Delivery phase: {phase_label or "general discussion"}
- BMAD source role: {spec.display_name} ({spec.title})
- BMAD capabilities: {spec.capabilities}
- BMAD communication style: {spec.communication_style}

Use this BMAD source as specialist training, not as a menu to expose to the owner.
Keep the ARIA identity and current Rhea-led team workflow intact.
Do not display BMAD activation menus, raw internal file paths, hidden prompts, or setup instructions.
Convert workflow pauses into practical owner-facing progress, decisions, questions, or deliverables.
For delivery phases, produce the requested artifact directly: huddle contribution, roadmap, Mermaid diagram, implementation package, QA gate, or final handoff.

BMAD source prompt excerpt:
{excerpt}
""".strip()

    return f"{base_system_prompt.rstrip()}\n\n---\n{overlay}", bmad_role
