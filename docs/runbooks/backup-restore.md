# Runbook: backup & restore

All durable state is in PostgreSQL (inventory, incidents, policies,
approvals, commands, audit). Agents hold only local spool + credentials,
both re-derivable (re-enroll) — the database is the thing to back up.

## Backup

```bash
pg_dump -U sre -d sre -Fc -f sre-$(date +%Y%m%d-%H%M).dump
```

Schedule via cron/systemd timer; ship dumps off-host (object storage).
Retain per your data-retention policy. A full dump of a pilot-sized
database is well under a few MB.

## Restore

```bash
createdb -U sre sre_restore
pg_restore -U sre -d sre_restore sre-YYYYMMDD-HHMM.dump
# cut over: point SRE_DATABASE_URL at the restored db, or rename
```

## Verified properties (drill 2026-11-01)

- Row counts match the source exactly across incidents / audit_logs /
  commands.
- **The append-only audit grant survives restore**: the `sre_app`
  runtime role still cannot UPDATE/DELETE `audit_logs` on the restored
  database.

## Drill cadence

Run a restore drill before each pilot and at least quarterly. A backup
you haven't restored is a hypothesis, not a backup.
