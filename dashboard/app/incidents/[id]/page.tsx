"use client";

import Link from "next/link";
import { use, useCallback, useState } from "react";
import { api, roleAtLeast } from "../../lib/api";
import { useMe, usePoll } from "../../lib/hooks";
import { SeverityBadge, StatusBadge } from "../../components/badges";

type Evidence = { kind: string; ref: string; summary: Record<string, unknown> };
type Event = { id: string; kind: string; type: string; occurred_at: string };
type Detail = {
  id: string;
  title: string;
  status: string;
  severity: string;
  opened_at: string;
  closed_at: string | null;
  evidence: Evidence[];
  events: Event[];
  allowed_transitions: string[];
};

function DiagnosisCard({ summary }: { summary: Record<string, unknown> }) {
  return (
    <div className="card">
      <strong>AI diagnosis</strong>{" "}
      <span className="muted">
        confidence {Math.round(Number(summary.confidence ?? 0) * 100)}%
      </span>
      <p style={{ margin: "8px 0 4px" }}>{String(summary.summary ?? "")}</p>
      <p className="muted" style={{ margin: 0 }}>
        {String(summary.probable_cause ?? "")}
      </p>
    </div>
  );
}

function VerificationCard({ summary }: { summary: Record<string, unknown> }) {
  const checks = (summary.checks ?? []) as { kind: string; outcome: string; detail?: string }[];
  return (
    <div className="card">
      <strong>Verification</strong> — attempt {String(summary.attempt)},{" "}
      <span className={`check-${summary.status === "passed" ? "pass" : "fail"}`}>
        {String(summary.status)}
      </span>
      <ul style={{ margin: "8px 0 0", paddingLeft: 18 }}>
        {checks.map((c, idx) => (
          <li key={idx}>
            {c.kind}: <span className={`check-${c.outcome}`}>{c.outcome}</span>{" "}
            <span className="muted">{c.detail}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function IncidentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const me = useMe();
  const [busy, setBusy] = useState(false);
  const fetcher = useCallback(() => api<Detail>(`/v1/incidents/${id}`), [id]);
  const { data, error, refresh } = usePoll(fetcher);

  const transition = async (to: string) => {
    const reason = window.prompt(`Reason for moving to ${to}?`);
    if (!reason) return;
    setBusy(true);
    try {
      await api(`/v1/incidents/${id}/transition`, {
        method: "POST",
        body: JSON.stringify({ to_status: to, reason }),
      });
      refresh();
    } catch (e) {
      alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (!data) return <>{error ? <div className="error">{error}</div> : <p>Loading…</p>}</>;

  return (
    <>
      <p className="muted" style={{ margin: "0 0 4px" }}>
        <Link href="/incidents">← Incidents</Link>
      </p>
      <h1>{data.title}</h1>
      <div className="row" style={{ marginBottom: 16 }}>
        <SeverityBadge severity={data.severity} />
        <StatusBadge status={data.status} />
        {roleAtLeast(me?.role, "operator") &&
          data.allowed_transitions.map((t) => (
            <button key={t} disabled={busy} onClick={() => transition(t)}>
              → {t}
            </button>
          ))}
      </div>
      {error && <div className="error">{error}</div>}

      <h2>Evidence</h2>
      {data.evidence
        .filter((e) => e.kind === "diagnosis")
        .map((e) => (
          <DiagnosisCard key={e.ref} summary={e.summary} />
        ))}
      {data.evidence
        .filter((e) => e.kind === "verification")
        .map((e) => (
          <VerificationCard key={e.ref} summary={e.summary} />
        ))}
      {data.evidence
        .filter((e) => e.kind === "alert")
        .map((e) => (
          <div className="card" key={e.ref}>
            <strong>Alert</strong> — {String(e.summary.rule)} ({String(e.summary.severity)})
          </div>
        ))}

      <h2>Timeline ({data.events.length} events)</h2>
      <div className="panel table-scroll">
        <table>
          <thead>
            <tr>
              <th>When</th>
              <th>Kind</th>
              <th>Type</th>
            </tr>
          </thead>
          <tbody>
            {data.events.map((ev) => (
              <tr key={ev.id}>
                <td className="mono">{new Date(ev.occurred_at).toLocaleString()}</td>
                <td>{ev.kind}</td>
                <td>{ev.type}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
