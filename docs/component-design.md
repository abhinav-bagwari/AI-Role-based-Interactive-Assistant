# Component-Level Design

## Components

1. Director (`director.py`)
- Accepts requirement.
- Loads selected team and workflow.
- Sends task and review protocol messages.
- Aggregates artifacts into final delivery.

2. BMAD Catalog (`bmad_catalog.py`)
- Reads `_bmad/_config/agent-manifest.csv`.
- Validates team roles against available BMAD agents.
- Loads BMAD agent prompt excerpts for context.

3. BMAD Agent Adapter (`agents/adapter.py`)
- Generic executor for any BMAD role.
- Uses role metadata and workflow expectations.
- Produces typed artifacts and metadata references.

4. Protocol Bus (`protocol.py`)
- Validates and stores structured messages.
- Provides trace per run.

5. Runtime (`runner.py`)
- Loads team/workflow configs.
- Creates Director and executes runs.
- Stores run outputs.

6. API (`api_server.py`) and UI (`ui/index.html`)
- Team listing, run submission, output inspection.

## Director Workflow Loop

1. Assign tasks to owner roles.
2. Collect intermediate outputs.
3. Trigger review roles.
4. Aggregate final delivery package.
