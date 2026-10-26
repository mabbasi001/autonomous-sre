"use client";

import Link from "next/link";
import { useCallback, useState } from "react";
import { api, roleAtLeast, since } from "../lib/api";
import { useMe, usePoll } from "../lib/hooks";

type Approval = {
  id: string;
  incident_id: string;
  action: string;
  target: string;
  status: string;
  requested_by: string;
  expires_at: string;
};

export default function ApprovalsPage() {
  const me = useMe();
  const canDecide = roleAtLeast(me?.role, "approver");
  const [busy, setBusy] = useState<string | null>(null);
  const fetcher = useCallback(
    () => api<{ approvals: Approval[] }>("/v1/approvals?status=pending"),
    [],
  );
  const { data, error, refresh } = usePoll(fetcher);

  const decide = async (id: string, decision: "approved" | "rejected") => {
    const reason = window.prompt(`Reason for ${decision}?`);
    if (!reason) return;
    setBusy(id);
    try {
      await api(`/v1/approvals/${id}/decision`, {
        method: "POST",
        body: JSON.stringify({ decision, reason }),
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
      <h1>Pending approvals</h1>
      {!canDecide && (
        <p className="muted">
          Your role ({me?.role ?? "…"}) can view approvals but not decide them.
        </p>
      )}
      {error && <div className="error">{error}</div>}
      <div className="panel table-scroll">
        <table>
          <thead>
            <tr>
              <th>Action</th>
              <th>Target</th>
              <th>Requested by</th>
              <th>Expires</th>
              <th>Incident</th>
              {canDecide && <th></th>}
            </tr>
          </thead>
          <tbody>
            {data?.approvals.map((a) => (
              <tr key={a.id}>
                <td className="mono">{a.action}</td>
                <td>{a.target}</td>
                <td className="muted">{a.requested_by}</td>
                <td className="muted">{since(a.expires_at)}</td>
                <td>
                  <Link href={`/incidents/${a.incident_id}`}>view</Link>
                </td>
                {canDecide && (
                  <td>
                    <div className="row">
                      <button
                        className="primary"
                        disabled={busy === a.id}
                        onClick={() => decide(a.id, "approved")}
                      >
                        Approve
                      </button>
                      <button
                        className="danger"
                        disabled={busy === a.id}
                        onClick={() => decide(a.id, "rejected")}
                      >
                        Reject
                      </button>
                    </div>
                  </td>
                )}
              </tr>
            ))}
            {data && data.approvals.length === 0 && (
              <tr>
                <td colSpan={canDecide ? 6 : 5} className="muted">
                  Nothing awaiting approval.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
