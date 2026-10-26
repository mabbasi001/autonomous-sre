"use client";

import { useCallback, useState } from "react";
import { api } from "../lib/api";
import { usePoll } from "../lib/hooks";

type AuditLog = {
  id: string;
  actor_type: string;
  actor_id: string | null;
  event_type: string;
  entity_type: string | null;
  entity_id: string | null;
  correlation_id: string | null;
  detail: Record<string, unknown> | null;
  created_at: string;
};

export default function AuditPage() {
  const [eventType, setEventType] = useState("");
  const [entityId, setEntityId] = useState("");

  const fetcher = useCallback(() => {
    const qs = new URLSearchParams();
    if (eventType) qs.set("event_type", eventType);
    if (entityId) qs.set("entity_id", entityId);
    qs.set("limit", "200");
    return api<{ audit_logs: AuditLog[] }>(`/v1/audit-logs?${qs.toString()}`);
  }, [eventType, entityId]);

  const { data, error, refresh } = usePoll(fetcher, 8000);

  return (
    <>
      <h1>Audit log</h1>
      <div className="row" style={{ marginBottom: 16 }}>
        <input
          placeholder="event_type (e.g. command.created)"
          value={eventType}
          onChange={(e) => setEventType(e.target.value)}
          style={{ width: 260 }}
        />
        <input
          placeholder="entity_id"
          value={entityId}
          onChange={(e) => setEntityId(e.target.value)}
          style={{ width: 300 }}
        />
        <button onClick={refresh}>Filter</button>
      </div>
      {error && <div className="error">{error}</div>}
      <div className="panel table-scroll">
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Actor</th>
              <th>Event</th>
              <th>Entity</th>
              <th>Detail</th>
            </tr>
          </thead>
          <tbody>
            {data?.audit_logs.map((r) => (
              <tr key={r.id}>
                <td className="mono">{new Date(r.created_at).toLocaleString()}</td>
                <td>
                  {r.actor_type}
                  {r.actor_id && <span className="muted"> · {r.actor_id}</span>}
                </td>
                <td className="mono">{r.event_type}</td>
                <td className="muted">{r.entity_type}</td>
                <td className="mono muted">{r.detail ? JSON.stringify(r.detail) : ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
