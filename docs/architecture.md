# High-Level Architecture

```mermaid
flowchart LR
    U["User"] --> D["Director"]
    D --> P["Protocol Bus"]
    P --> BMAD["BMAD Agent Adapters (pm, analyst, dev, qa, sm, ux-designer, tech-writer, architect)"]
    BMAD --> A["Artifacts Store (in-memory run package)"]
    A --> D
    D --> U
    C["BMAD Catalog Loader (_bmad manifests)"] --> D
```

## Core Principles

- Director is the only user-facing interface.
- Agent roles come from BMAD manifests, not custom role implementations.
- Team composition and workflows are JSON-configurable.
- Protocol trace is explicit and auditable.
- System is independent from `microservice-ecp-service-manager` and treated as a new project.

## Suggested Production Stack

- API: FastAPI (Python) or NestJS (Node)
- Workflow orchestration: Temporal/Celery
- Event bus: NATS/Kafka
- Data store: PostgreSQL + Redis
- UI: React + TypeScript
- Observability: OpenTelemetry + Prometheus/Grafana
