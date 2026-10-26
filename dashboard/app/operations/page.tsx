"use client";

import { useCallback, useState } from "react";
import { api, roleAtLeast, since } from "../lib/api";
import { useMe, usePoll } from "../lib/hooks";

type KillSwitch = { scope: string; engaged: boolean; reason: string | null; updated_at: string | null };
type Agent = {
  id: string;
  hostname: string;
  environment: string | null;
  status: string;
  version: string | null;
  last_seen_at: string | null;
};

export default function OperationsPage() {
  const me = useMe();
  const isAdmin = roleAtLeast(me?.role, "admin");
  const isOperator = roleAtLeast(me?.role, "operator");
  const [busy, setBusy] = useState<string | null>(null);

  const fetcher = useCallback(async () => {
    const [switches, envs, agents] = await Promise.all([
      api<{ kill_switches: KillSwitch[] }>("/v1/kill-switches"),
      api<{ environments: string[] }>("/v1/environments"),
      isOperator
        ? api<{ agents: Agent[] }>("/v1/agents")
        : Promise.resolve({ agents: [] as Agent[] }),
    ]);
    return { switches: switches.kill_switches, envs: envs.environments, agents: agents.agents };
  }, [isOperator]);

  const { data, error, refresh } = usePoll(fetcher);

  const scopes = data
    ? ["global", ...data.envs.map((e) => `environment:${e}`)]
    : [];
  const stateOf = (scope: string) => data?.switches.find((s) => s.scope === scope);

  const flip = async (scope: string, engaged: boolean) => {
    const reason = window.prompt(`Reason for ${engaged ? "engaging" : "releasing"} ${scope}?`);
    if (!reason) return;
    setBusy(scope);
    try {
      await api(`/v1/kill-switches/${scope}`, {
        method: "PUT",
        body: JSON.stringify({ engaged, reason }),
      });
      refresh();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <>
      <h1>Operations</h1>
      {error && <div className="error">{error}</div>}

      <h2>Kill switches</h2>
      <div className="panel table-scroll">
        <table>
          <thead>
            <tr>
              <th>Scope</th>
              <th>State</th>
              <th>Reason</th>
              <th>Updated</th>
              {isAdmin && <th></th>}
            </tr>
          </thead>
          <tbody>
            {scopes.map((scope) => {
              const s = stateOf(scope);
              const engaged = s?.engaged ?? false;
              return (
                <tr key={scope}>
                  <td className="mono">{scope}</td>
                  <td>
                    <span className={`badge ${engaged ? "st-escalated" : "st-resolved"}`}>
                      {engaged ? "ENGAGED" : "released"}
                    </span>
                  </td>
                  <td className="muted">{s?.reason ?? ""}</td>
                  <td className="muted">{since(s?.updated_at ?? null)}</td>
                  {isAdmin && (
                    <td>
                      <button
                        className={engaged ? "" : "danger"}
                        disabled={busy === scope}
                        onClick={() => flip(scope, !engaged)}
                      >
                        {engaged ? "Release" : "Engage"}
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <h2>Agents</h2>
      {!isOperator ? (
        <p className="muted">Agent inventory requires the operator role.</p>
      ) : (
        <div className="panel table-scroll">
          <table>
            <thead>
              <tr>
                <th>Hostname</th>
                <th>Environment</th>
                <th>Status</th>
                <th>Version</th>
                <th>Last seen</th>
              </tr>
            </thead>
            <tbody>
              {data?.agents.map((a) => {
                const stale =
                  a.last_seen_at &&
                  Date.now() - new Date(a.last_seen_at).getTime() > 90_000;
                return (
                  <tr key={a.id}>
                    <td>{a.hostname}</td>
                    <td className="muted">{a.environment}</td>
                    <td>{a.status}</td>
                    <td className="mono muted">{a.version ?? "—"}</td>
                    <td className={stale ? "check-fail" : "muted"}>{since(a.last_seen_at)}</td>
                  </tr>
                );
              })}
              {data && data.agents.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    No agents enrolled.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
