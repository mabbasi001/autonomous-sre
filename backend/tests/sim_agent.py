"""A fake agent that drives the real API: enroll, heartbeat, and replay
scripted event sequences. Used by the integration tests and runnable
against a live server:

    python -m tests.sim_agent --scenario nginx_down --token <enrollment-token>
"""

import argparse
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx

SCENARIOS_DIR = Path(__file__).parent / "scenarios"

ENDPOINT_FIELDS = {
    "/v1/telemetry/metrics": "metrics",
    "/v1/telemetry/logs": "logs",
    "/v1/events": "events",
}


class SimAgent:
    def __init__(self, client: httpx.Client, hostname: str = "sim-agent-01"):
        self.client = client
        self.hostname = hostname
        self.agent_id: str | None = None
        self.secret: str | None = None

    def enroll(self, token: str, environment: str = "development") -> None:
        resp = self.client.post(
            "/v1/agents/enroll",
            json={"token": token, "hostname": self.hostname, "environment": environment},
        )
        resp.raise_for_status()
        data = resp.json()
        self.agent_id = data["agent_id"]
        self.secret = data["secret"]

    def signed_post(self, path: str, payload: dict) -> httpx.Response:
        from app.security import sign

        body = json.dumps(payload).encode()
        ts = str(int(time.time()))
        return self.client.post(
            path,
            content=body,
            headers={
                "content-type": "application/json",
                "x-agent-id": self.agent_id,
                "x-timestamp": ts,
                "x-signature": sign(self.secret, "POST", path, ts, body),
            },
        )

    def signed_get(self, path: str) -> httpx.Response:
        from app.security import sign

        ts = str(int(time.time()))
        return self.client.get(
            path,
            headers={
                "x-agent-id": self.agent_id,
                "x-timestamp": ts,
                "x-signature": sign(self.secret, "GET", path, ts, b""),
            },
        )

    def heartbeat(self, version: str = "sim") -> httpx.Response:
        return self.signed_post("/v1/agents/heartbeat", {"version": version})

    def send(self, path: str, items: list[dict]) -> httpx.Response:
        stamped = []
        for item in items:
            stamped.append(
                {
                    "event_id": str(uuid.uuid4()),
                    "occurred_at": datetime.now(UTC).isoformat(),
                }
                | item
            )
        return self.signed_post(path, {ENDPOINT_FIELDS[path]: stamped})

    def replay(self, scenario: str) -> list[httpx.Response]:
        steps = json.loads((SCENARIOS_DIR / f"{scenario}.json").read_text())
        responses = []
        for step in steps:
            responses.append(self.send(step["path"], step["items"]))
        return responses


def main() -> None:
    parser = argparse.ArgumentParser(prog="sim-agent")
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--base-url", default="http://localhost:8000")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url) as client:
        agent = SimAgent(client)
        agent.enroll(args.token)
        print(f"enrolled as {agent.agent_id}")
        for resp in agent.replay(args.scenario):
            print(resp.status_code, resp.json())


if __name__ == "__main__":
    main()
