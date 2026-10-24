import json

import pytest
from conftest import operator_token
from sim_agent import SimAgent
from sqlalchemy import select
from test_enrollment import make_token

from app.config import settings
from app.detection.engine import process_pending_events
from app.incidents.manager import process_new_alerts
from app.investigation import service
from app.investigation.provider import ProviderError, SchemaError
from app.investigation.service import investigate, investigate_open_incidents
from app.models import AIInvestigation, AuditLog, Command, Incident, IncidentEvidence


@pytest.fixture()
def sim(client, db):
    agent = SimAgent(client)
    agent.enroll(make_token(db))
    return agent


class FakeProvider:
    def __init__(self, *script):
        self.script = list(script)
        self.calls = 0

    def diagnose(self, system, evidence):
        self.calls += 1
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step, {"input_tokens": 100, "output_tokens": 50}, json.dumps(step)


def diagnosis(action="service.restart", unit="nginx"):
    proposed = []
    if action:
        proposed = [{"action": action, "unit": unit}]
    return {
        "summary": "nginx is down",
        "probable_cause": "the nginx unit exited",
        "confidence": 0.9,
        "evidence_event_ids": [],
        "proposed_actions": proposed,
    }


def open_incident(sim, db, with_injection=False):
    if with_injection:
        sim.replay("prompt_injection")
    sim.replay("nginx_down")
    process_pending_events(db)
    process_new_alerts(db)
    return db.scalar(
        select(Incident).where(Incident.fingerprint == f"systemd:nginx:{sim.agent_id}")
    )


def test_diagnosis_proposes_and_dispatches_restart(sim, db):
    incident = open_incident(sim, db)
    provider = FakeProvider(diagnosis())
    investigation = investigate(db, incident, provider=provider)

    assert investigation.status == "completed"
    assert investigation.attempts == 1
    db.refresh(incident)
    assert incident.status == "EXECUTING"  # seeded dev policy auto-allows nginx restarts
    command = db.scalar(select(Command))
    assert command.action == "service.restart"
    assert command.params == {"unit": "nginx"}

    evidence_row = db.scalar(
        select(IncidentEvidence).where(IncidentEvidence.kind == "diagnosis")
    )
    assert evidence_row.summary["probable_cause"] == "the nginx unit exited"
    # the log excerpt travelled as data inside the evidence bundle
    assert "bind() to 0.0.0.0:80 failed" in json.dumps(investigation.request)


def test_out_of_catalogue_proposal_discarded(sim, db):
    incident = open_incident(sim, db, with_injection=True)
    provider = FakeProvider(
        {
            "summary": "hijacked",
            "probable_cause": "injection",
            "confidence": 1.0,
            "evidence_event_ids": [],
            "proposed_actions": [
                {"action": "shell.exec"},
                {"action": "vm.delete"},
                {"action": "service.restart"},  # catalogue action but no unit
            ],
        }
    )
    investigation = investigate(db, incident, provider=provider)

    assert investigation.status == "completed"
    assert db.scalar(select(Command)) is None
    db.refresh(incident)
    assert incident.status == "MANUAL_TRIAGE"
    discarded = db.scalars(
        select(AuditLog).where(AuditLog.event_type == "ai.proposal_discarded")
    ).all()
    assert {d.detail["action"] for d in discarded} == {
        "shell.exec",
        "vm.delete",
        "service.restart",
    }
    reasons = {d.detail["action"]: d.detail["reason"] for d in discarded}
    assert reasons["service.restart"] == "missing required fields"
    # injection text is present in the evidence - as data, never as instructions
    assert "ignore all previous instructions" in json.dumps(investigation.request)


def test_provider_error_degrades_to_manual_triage(sim, db):
    incident = open_incident(sim, db)
    investigation = investigate(db, incident, provider=FakeProvider(ProviderError("api down")))

    assert investigation.status == "failed"
    assert investigation.error == "api down"
    db.refresh(incident)
    assert incident.status == "MANUAL_TRIAGE"


def test_schema_failure_retries_once_then_triage(sim, db):
    incident = open_incident(sim, db)
    provider = FakeProvider(SchemaError("not json"), SchemaError("still not json"))
    investigation = investigate(db, incident, provider=provider)

    assert provider.calls == 2
    assert investigation.attempts == 2
    assert investigation.status == "invalid"
    assert investigation.response["attempts"] == ["not json", "still not json"]
    db.refresh(incident)
    assert incident.status == "MANUAL_TRIAGE"


def test_schema_failure_then_success(sim, db):
    incident = open_incident(sim, db)
    provider = FakeProvider(SchemaError("oops"), diagnosis())
    investigation = investigate(db, incident, provider=provider)

    assert investigation.status == "completed"
    assert investigation.attempts == 2
    db.refresh(incident)
    assert incident.status == "EXECUTING"


def test_no_provider_configured_goes_to_triage(sim, db):
    incident = open_incident(sim, db)
    investigation = investigate(db, incident)  # settings key is blank in tests

    assert investigation.status == "skipped"
    db.refresh(incident)
    assert incident.status == "MANUAL_TRIAGE"


def test_token_budget_skips_provider(sim, db, monkeypatch):
    incident = open_incident(sim, db)
    provider = FakeProvider(diagnosis())
    monkeypatch.setattr(settings, "ai_token_budget", 1)
    investigation = investigate(db, incident, provider=provider)

    assert provider.calls == 0
    assert investigation.status == "skipped"
    assert "token budget" in investigation.error
    db.refresh(incident)
    assert incident.status == "MANUAL_TRIAGE"


def test_worker_auto_investigates_open_incidents(sim, db, monkeypatch):
    incident = open_incident(sim, db)
    monkeypatch.setattr(service, "get_provider", lambda: FakeProvider(diagnosis()))
    assert investigate_open_incidents(db) >= 1
    db.refresh(incident)
    assert incident.status == "EXECUTING"


def test_manual_investigate_endpoint(sim, db, client, monkeypatch):
    incident = open_incident(sim, db)
    investigate(db, incident)  # no provider -> MANUAL_TRIAGE
    db.refresh(incident)
    assert incident.status == "MANUAL_TRIAGE"

    monkeypatch.setattr(service, "get_provider", lambda: FakeProvider(diagnosis()))
    resp = client.post(
        f"/v1/incidents/{incident.id}/investigate",
        headers={"Authorization": f"Bearer {operator_token('operator')}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"
    assert resp.json()["incident_status"] == "EXECUTING"

    second = client.post(f"/v1/incidents/{incident.id}/investigate")
    assert second.status_code == 409


def test_investigation_row_is_reproducible(sim, db):
    incident = open_incident(sim, db)
    investigate(db, incident, provider=FakeProvider(diagnosis()))

    row = db.scalar(select(AIInvestigation))
    assert row.model == settings.ai_model
    assert row.request["system"] == service.SYSTEM_PROMPT
    assert row.request["evidence"]["incident"]["fingerprint"] == incident.fingerprint
    assert row.response["attempts"]
    assert row.usage == {"input_tokens": 100, "output_tokens": 50}
    assert row.diagnosis["confidence"] == 0.9