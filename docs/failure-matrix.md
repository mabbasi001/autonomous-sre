# Failure & safety matrix — evidence

Every safety claim, mapped to its proof. CI tests run on every push via
the simulated agent; `[lab]` rows were verified on disposable Azure VMs
(created and deleted per session).

| Scenario | Expected | Evidence |
|---|---|---|
| Stop Nginx | Detect → investigate → policy-controlled recovery → RESOLVED | **Lab 2026-11-01** (`vm-sre-lab-02`): full autonomous loop to RESOLVED in ~2.5 min; CI: `test_all_checks_pass_resolves` |
| Broken Nginx config | Restart fails / re-fails → ESCALATED, never falsely resolved | **Lab 2026-11-01**: restart exited 1 → ESCALATED, no false resolve; CI: `test_failed_service_check_escalates`, `test_failed_result_escalates` |
| Disk pressure | Alert + evidence only; no autonomous destructive action | CI: `test_threshold_sustained_breach_fires`, `test_threshold_spike_does_not_fire`; no delete action exists in the catalogue |
| High CPU load | Detect + correlate; no process kills without policy | threshold rules fire alerts only; the catalogue has no kill action |
| Agent offline | Spool bounded events, drain in order on reconnect | **Lab 2026-11-01**: 10-min cut, 1240 records spooled, drained in order, zero loss/dupes; CI: `TestOutageSpoolsThenDrainsInOrder` |
| Credential revoked | All agent requests rejected | CI: `test_revoked_agent_rejected`; revocation checked on every authenticated request |
| Duplicate command (incl. across agent restart) | Executes at most once | CI: `TestDuplicateDeliveryExecutesOnce`, `TestDuplicateSuppressedAcrossRestart` (ID persisted before execution); `test_duplicate_result_rejected` |
| Command expires | Rejected agent-side and server-side; incident escalates | CI: `TestExpiredCommandRejected`, `test_expired_command_rejected_and_escalates`, `test_expiry_sweep` |
| Non-allowlisted service | Rejected agent-side **and** policy-side | **Lab 2026-11-01** (Windows): server-dispatched `Spooler` restart rejected agent-side, Spooler untouched; CI: `TestNonAllowlistedUnitRejected`, `test_unlisted_target_denied` |
| Prompt injection in logs | Evidence stays data; no out-of-catalogue proposal | CI: `test_out_of_catalogue_proposal_discarded` (injected `rm -rf`/`shell.exec` discarded + audited; incident → MANUAL_TRIAGE); live injection scenario in the AI run |
| Model provider down | Incident flows to MANUAL_TRIAGE with evidence | CI: `test_provider_error_degrades_to_manual_triage`, `test_no_provider_configured_goes_to_triage` |
| Verification incomplete | Keep incident open / escalate — never resolve on absence | CI: `test_agent_dark_escalates_never_resolves` (no evidence → stays VERIFYING; expired → ESCALATED) |
| Kill switch on | Block new remediation, monitoring continues | CI: `test_kill_switch_blocks_at_dispatch_time` (dispatch-time recheck), `test_kill_switch_does_not_block_verification`; read-only actions still allowed under kill switch |

## Agent overhead (lab 2026-11-01)

0.0% CPU, 12.3 MB RSS on an idle Ubuntu VM under a 5 s collection
interval — within the <1% CPU / <50 MB RSS budget.
