# Pilot plan

The pilot is the only MVP step that needs real calendar time — a week of
monitor-only operation on real internal VMs. Everything it depends on is
done and evidenced (see `failure-matrix.md`, `security-review.md`).

## Readiness gate (all met)

- [x] Failure matrix passes with recorded evidence
- [x] Dependency scans clean (govulncheck, pip-audit)
- [x] Backup/restore drill passes (incl. audit-grant preservation)
- [x] Runbooks written (outage, backup/restore, operator)
- [x] Agent packaged (`.deb` builds in CI; Windows service documented)
- [x] Append-only audit enforced at the DB grant level
- [x] Kill switches verified (proposal + dispatch time)

## Procedure

### Week 0 — setup (monitor-only)

1. Provide the three deferred config values (see `../../requirements/`):
   Entra ID app registration, Slack webhook, Anthropic key.
2. Deploy the control plane (Docker Compose behind the TLS proxy).
3. Enroll 2–3 real internal VMs (mix of Linux + Windows if available)
   into the **development** environment.
4. Configure collection (services, HTTP checks) per VM.
5. **Create no remediation policies** — the platform detects, opens
   incidents, diagnoses, and notifies, but cannot act. This is the
   monitor-only posture.

### Week 1 — observe

- Let it run. Review the Incidents and Audit pages daily.
- Track the success metrics below from the audit log + incident data.

### Gate → dev auto-remediation

If the week-1 metrics pass, enable **auto-restart in development only**
by creating the `dev-service-restart` policy (`examples/policies/`).
Keep production remediation off.

## Success metrics (README §17 targets)

| Metric | Target | How to measure |
|---|---|---|
| Detection latency (fault → incident) | < 60 s | incident.opened − fault time (audit) |
| False-positive incident rate | < 10% | operator triage tags |
| Duplicate-incident rate | ~0 | fingerprint dedup (should be structural) |
| Agent overhead | < 1% CPU, < 50 MB RSS | host metrics (lab: 0.0% / 12.3 MB) |
| Audit completeness | 100% traceable | spot-check chains via `/v1/audit-logs` |
| Auto-remediation success (dev, post-gate) | > 90% verified-resolved | RESOLVED / attempted |
| False-resolve rate | 0 | verification escalates on doubt |

## Post-pilot review (deliverable)

Document: what fired, what remediated, what escalated, the measured
metrics vs targets, and an explicit **go/no-go for dev auto-remediation**
(and the conditions for a later production go/no-go).

## Status

**Execution pending** — needs the three config values and a week of
runtime on real VMs. All engineering prerequisites are complete.
