# Runbook: control-plane outage

## What happens automatically

The platform fails safe. While the control plane is down:

- **Agents keep collecting** and buffer events to their local disk spool
  (10 MB cap, oldest dropped). No data is lost for outages within the
  spool's capacity (~hours at normal rates).
- **Nothing executes stale.** Commands carry an expiry (default 120 s);
  any command not picked up in time is rejected by the agent and marked
  expired server-side, escalating its incident rather than running late.
- On recovery, agents reconnect with exponential backoff + jitter and
  drain the spool **in order**; the server deduplicates by event ID, so
  reconnect storms can't double-count.

Verified: 10-minute network cut in the lab drained 1240 buffered records
in order, zero loss, zero duplicates.

## Detection

- Operator dashboard unreachable, or `GET /healthz` failing.
- Agents log `heartbeat failed` / `command poll failed` (connection
  refused) — visible via their host logs, not the platform (which is down).

## Response

1. **Triage the control plane**: `docker compose ps`; check `api`,
   `worker`, `postgres` health. `docker compose logs api worker`.
2. **Database**: if Postgres is down, restore from the latest backup
   (see `backup-restore.md`). The append-only audit grant survives
   restore.
3. **Restart**: `docker compose up -d`. Migrations run on `api` start.
4. **Verify recovery**: `GET /healthz` ok; `GET /v1/incidents` returns;
   watch agents' `last_seen_at` refresh and spools drain.
5. **Check for stale escalations**: incidents that escalated due to
   command expiry during the outage are in ESCALATED — review and
   re-drive or close as appropriate.

## Do not

- Do not manually re-run commands that expired during the outage — let
  the normal detect→diagnose→remediate loop re-propose them, so policy
  and verification still apply.
- Do not disable command expiry to "catch up" — stale execution is the
  exact failure mode expiry prevents.
