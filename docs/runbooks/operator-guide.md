# Runbook: operator guide

## Roles

| Role | Can |
|---|---|
| viewer | read incidents, inventory, audit |
| operator | + trigger investigations, propose manual actions, transition incidents |
| approver | + approve/reject remediation (never your own request) |
| admin | + manage policies, alert rules, kill switches, agents |

## Daily

- Watch the **Incidents** page. Each incident shows its AI diagnosis,
  proposed/executed actions, and verification result.
- Clear the **Approvals** queue — unactioned approvals expire and
  escalate their incident. You cannot approve a request you made.

## Enrolling an agent

1. Admin mints a single-use, environment-scoped token:
   `python -m app.cli create-enrollment-token --environment <env>`
2. On the VM, enroll once, then start the service (see
   `agent/packaging/README.md` for Linux and Windows).

## Stopping remediation fast (kill switch)

**Operations → kill switches** (admin). Engage `global` or
`environment:<env>`. Effect is immediate and checked again at dispatch
time — in-flight proposals won't execute. Monitoring and verification
continue; only remediation stops. Release the same way, with a reason
(both are audited).

## When an incident escalates

ESCALATED means the platform declined to resolve it autonomously —
failed/expired remediation, failed verification, a denied proposal, or a
diagnosis with no safe catalogue action. Investigate from the incident
detail (evidence + diagnosis + audit), then act manually and transition
the incident, or close it.

## Enabling remediation in a new environment

Production ships with **no policies** — remediation is off until an
admin creates one (see `examples/policies/`). Keep new action types
disabled until the failure matrix passes for that environment. Require
peer review for production policy changes.

## Everything is auditable

`GET /v1/audit-logs` (or the **Audit** page) reconstructs any decision
chain: alert → incident → diagnosis → policy decision (with inputs +
version) → approval (who/when/why) → command → execution → verification.
The audit log is append-only at the database level.
