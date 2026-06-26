# AI Role-based Interactive Assistant

This repository now has two distinct layers:

- `ui/` contains **ARIA**, a standalone browser prototype where a team of AI employees collaborates in `#team-room` and private DMs.
- `src/` contains the maintained **BMAD orchestration backend**, which still supports real BMAD-agent execution, workflows, and tests as a separate Python runtime.

The older generic `multi-agent-system` prototype has been retired in favor of this project.

## ARIA Frontend Prototype

ARIA is the current UI experience in this repo. It is served by the local Python backend so Rhea can save app workspaces and route live model calls server-side.

What it includes:

- six named AI employees: Rhea, Marcus, Zara, Kai, Priya, and Nox
- Party Mode-inspired `#team-room` plus private DMs
- facilitator-led discussion rounds where Rhea selects the 2-3 most relevant agents for each owner message
- Rhea-led delivery state machine for build-style asks: intro meeting, owner brief, team huddle, owner checkpoint, roadmap, architecture diagram, implementation package, QA/release gate, and final owner handoff
- filesystem app workspaces for delivery tasks under `/Users/abhinavbagwari/ai/bmad-applications/<app-name>/`
- backend model bridge for live agent turns through the configured OpenAI-compatible provider, keeping API keys out of the browser
- BMAD-backed role context for ARIA live turns: Rhea uses orchestration context, Marcus uses PM context, Zara uses UX context, Kai uses dev context, Priya uses architecture context, and Nox uses QA context
- public routing, visible handoffs, standups, session reset via `*exit`, and live-topic status
- local simulation fallback when no backend provider is configured

Important notes:

- **No API key is required** to use ARIA locally.
- The UI no longer assumes a canned to-do demo. The owner is expected to bring the real requirement or question.
- If you want live model-written turns, the backend now inherits the current Codex Oracle Code Assist provider from `~/.codex/config.toml` and the API key from `~/.codex/auth.json` when explicit `BMAD_LLM_*` variables are not set. Existing Oracle Code Assist or GPT-compatible credentials can still be exposed through those environment variables when you want to override Codex.
- The browser never stores model API keys.

### Run ARIA

```bash
cd /Users/abhinavbagwari/bmad
PYTHONPATH=bmad-team-orchestrator/src python3 -m bmad_team_orchestrator
```

Then open `http://127.0.0.1:8091`.

For build-style prompts such as “Create a calendar app,” ARIA saves the delivery package to:

```text
/Users/abhinavbagwari/ai/bmad-applications/calendar-app/
```

The output folder includes product notes, owner checkpoint, roadmap, Mermaid diagram source, implementation package, extracted source code when present, a small React/Vite scaffold, QA/release gate, final handoff, and a manifest.

## BMAD Backend

The Python backend remains the maintained BMAD orchestration path in this repo.

Backend capabilities:

- agent definitions from `_bmad/_config/agent-manifest.csv`
- role prompts and metadata from `_bmad/bmm/agents/*` and `_bmad/core/agents/*`
- teams from `config/teams/*.json`
- workflows from `config/workflows/*.json`
- seeded five-role BMAD team: PM, Architect, Developer, QA, and Scrum Master
- internal agent-to-agent handoffs between BMAD employees
- live BMAD execution through an OpenAI-compatible chat-completions or responses endpoint
- live ARIA agent turns through `POST /api/agent-turns`, with server-side BMAD role prompts attached to known ARIA agents
- app workspace persistence through `POST /api/applications`
- fallback preview mode when no provider is configured
- workflow-runner APIs preserved for artifact-oriented runs

### BMAD Live Mode

The default live provider mirrors the current Codex setup:

```bash
export BMAD_LLM_MODEL="gpt-5.5"
export BMAD_LLM_BASE_URL="https://code-internal.aiservice.us-chicago-1.oci.oraclecloud.com/20250206/app/litellm"
export BMAD_LLM_WIRE_API="responses"
export BMAD_LLM_API_KEY="$(python3 -c 'import json, pathlib; print(json.loads((pathlib.Path.home() / ".codex" / "auth.json").read_text()).get("OPENAI_API_KEY", ""))')"
```

You normally do not need to run those exports manually on this machine because the backend reads the Codex config/auth files automatically and never sends the API key to the browser.

Optional:

```bash
export BMAD_LLM_TEMPERATURE="0.2"
export BMAD_LLM_TIMEOUT_SECONDS="90"
```

If those variables and Codex credentials are not available, the backend still works, but it runs in local fallback preview mode instead of true live BMAD-agent execution.

### Run The BMAD API

```bash
PYTHONPATH=bmad-team-orchestrator/src python3 -m bmad_team_orchestrator
```

## Backend API

- `GET /api/teams`
- `GET /api/teams/{teamId}/conversation`
- `POST /api/teams/{teamId}/messages`
- `POST /api/teams/{teamId}/rename`
- `GET /api/runtime-status`
- `POST /api/agent-turns`
- `POST /api/applications`

## Supporting API

- `GET /api/bmad-agents`
- `POST /api/runs`
- `GET /api/runs/{runId}`

## Tests

```bash
PYTHONPATH=bmad-team-orchestrator/src python3 -m unittest discover -s bmad-team-orchestrator/tests -v
```
