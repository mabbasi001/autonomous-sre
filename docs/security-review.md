# Security review

Review of the MVP against the platform's security model. Dependency
scans (`govulncheck`, `pip-audit`) ran clean on 2026-11-01.

## Secret handling

| Secret | Where it lives | Exposure control |
|---|---|---|
| Agent per-agent secret | `agents.secret` (DB), agent `credentials.json` (0600 / ACL'd) | Never returned by any read endpoint; never logged; required raw because HMAC verification needs it (see Accepted risks) |
| Enrollment token | sha256 hash in `enrollment_tokens`; raw shown once at mint | Single-use, environment-scoped, time-expiring |
| OIDC bearer (operator) | Server-side proxy / backend only | Never reaches the browser; the dashboard talks only to its own proxy |
| Slack webhook URL | `SRE_SLACK_WEBHOOK_URL` env | Not in Git (`.env` gitignored); never rendered in UI or logs |
| Anthropic API key | `ANTHROPIC_API_KEY` env | Not in Git; never sent to agents; not in evidence bundles |
| Azure / DB creds | env / Key Vault (deploy) | Not in agent config responses |

Checks: no secret appears in `/v1/agents/config` responses, incident
detail, audit detail, or Slack messages (asserted by tests
`test_agent_inventory_requires_operator`, `test_messages_carry_no_log_content`,
`test_detail_returns_references_not_bulk_logs`).

## Authentication & authorization

- Agents: HMAC-SHA256 over method+path+timestamp+body-hash, ±300 s
  replay window, constant-time compare, revocation checked per request.
- Operators: Entra ID OIDC (issuer + audience + JWKS validated); RBAC
  (viewer<operator<approver<admin) enforced on **every** platform
  endpoint; requester ≠ approver enforced at API **and** DB constraint.
- Dev fallback (no OIDC configured) is **development-only**; any other
  environment returns 401 (`test_dev_fallback_only_without_oidc_config`).

## Database least-privilege

- Runtime role `sre_app`: full DML except **UPDATE/DELETE revoked on
  `audit_logs`** (append-only, enforced at the grant level, survives
  backup/restore — verified in the drill).
- Migrations run as the owning `sre` role via `SRE_MIGRATION_DATABASE_URL`;
  a grant on the table owner would be bypassable, this isn't.

## Rate & payload limits

- 1 MB request body cap → 413; ingestion batch cap 500 → 422.
- Per-(action, resource) policy rate limits + cooldowns + per-incident
  retry caps; restart loops are a policy failure, not an executor one.
- Command execution timeout; output bounded (4 KB).

## Execution safety

- No arbitrary execution: fixed 5-action catalogue (code, not runtime
  registration); no LLM/API/DB string reaches a shell.
- Dual allowlist: the agent validates targets against its local config
  independently of central policy (proven live: a compromised control
  plane can't push the agent off-list).
- Linux: unprivileged user + per-service `sudoers` entries (exact
  command match). Windows: SCM restart + IIS recycle (see Accepted risks).

## Accepted risks (MVP)

1. **Agent secret stored plaintext** server-side — HMAC needs the raw
   key, so a hash-only verifier is impossible. Encryption-at-rest via
   the DB/KMS is the mitigation; ACL + no-read-endpoint limit exposure.
2. **Same-window replay** (within 300 s, no nonce cache) — harmless for
   idempotent heartbeats; commands carry their own idempotency keys +
   expiry. A nonce cache is a cheap future add.
3. **Windows IIS needs admin** — appcmd/WAS require elevation, so the
   Windows service account is a local admin for IIS management. The
   agent-side allowlist remains the operative control. Linux stays
   unprivileged. Tighter IIS delegation is a follow-up.
4. **Per-command signing deferred** — channel auth + expiry +
   idempotency + dual allowlist cover the MVP threat model; signing
   needs a key-distribution design.
5. **mTLS deferred** — HMAC-over-TLS gives the same outbound-only
   posture without operating a CA; adopt step-ca/SPIFFE later.

## Scans (2026-11-01)

- `govulncheck ./...` (agent): No vulnerabilities found.
- `pip-audit` (backend): No known vulnerabilities found.
