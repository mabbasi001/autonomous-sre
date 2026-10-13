# Autonomous SRE Platform

An AI-assisted SRE platform: a lightweight Go agent on Azure VMs plus a
control plane that detects failures, opens incidents, investigates them
with an LLM, and executes **policy-controlled, typed remediation** —
with human approval gates, independent verification, kill switches, and
an append-only audit trail.

## How it works

The agent watches host health, systemd services, and HTTP endpoints,
and talks **outbound-only** (HMAC-signed HTTPS) to the control plane.
Server-side alert rules turn signals into deduplicated incidents. An
LLM produces a schema-constrained diagnosis and may propose actions
from a **fixed action catalogue** — never arbitrary commands. The
policy engine (not the AI) decides allow / approval-required / deny;
risky actions wait for a human, and Slack gets notified. Approved
commands are dispatched with expiry and idempotency keys, executed once
by the agent, then verified through a separate code path. Everything
lands in a database-enforced append-only audit log. If the model
provider is down, the platform degrades to a normal incident tracker —
never to silence.

## Safety invariants

1. No arbitrary execution — typed catalogue actions only; no LLM string
   ever reaches a shell.
2. Dual allowlists: the agent validates targets locally, independent of
   central policy.
3. AI proposes → policy decides → humans approve. Requester ≠ approver.
4. Kill switches checked at proposal *and* dispatch.
5. Commands expire; duplicates are no-ops, even across agent restarts.
6. Verification never resolves on absence of evidence — escalate on
   doubt.
7. `audit_logs` is append-only at the database-grant level.
8. Secrets never reach agents' config responses, the LLM, logs, or Git.

## Repository layout

```text
agent/        Go agent: cmd/, internal/{collectors,enrollment,transport,executor,config}, packaging/
backend/      FastAPI control plane: app/{api,detection,incidents,investigation,policies,
              approvals,commands,verification,notifications,inventory,audit}, tests/
dashboard/    Operator UI (Entra ID login)
deploy/       compose/, containers/, scripts/
examples/     agent-config/, policies/
```

## Stack

| Part | Tech |
|---|---|
| Agent | Go, single static binary, outbound HTTPS + HMAC |
| Backend | Python 3.12, FastAPI, SQLAlchemy + Alembic |
| DB & queue | PostgreSQL (also the work queue — `SKIP LOCKED`; no broker) |
| Dashboard | Next.js + TypeScript, Entra ID (OIDC) |
| AI | Provider-abstracted LLM client, schema-constrained output |
| Azure | Resource Graph, Managed Identity, read-only |
| Deploy | Docker Compose behind a TLS reverse proxy |

## Quickstart

Only PostgreSQL runs in Docker; everything else runs natively.
Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Go 1.22+.

```bash
make db        # postgres in docker, exposed on localhost:5432
make migrate
make api       # uvicorn with reload on :8000
make worker    # in a second terminal
curl -s localhost:8000/healthz
```

## Development

```bash
make test      # backend pytest + agent go test
make lint      # ruff + go vet
make db-stop
```

CI runs lint, tests, the agent build, and a full migration
up/down/up cycle against a fresh Postgres on every push.

## Deployment

The full stack (api, worker, postgres, web) ships as Docker Compose
behind a TLS reverse proxy:

```bash
cd deploy/compose
docker compose up -d --build
```

Migrations run automatically when the api container starts.

## Contributing

- Changes to policy, approvals, commands, the executor, audit, or
  AI-output handling require peer review.
- New action types default to disabled everywhere.
- Production remediation stays disabled until the failure-testing
  matrix passes in the lab.
- Branches: `feature/*` and `fix/*` off `develop`; PRs target
  `develop`; releases merge to `main`.
