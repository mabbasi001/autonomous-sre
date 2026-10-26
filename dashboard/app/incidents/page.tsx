"use client";

import Link from "next/link";
import { useCallback } from "react";
import { api, since } from "../lib/api";
import { usePoll } from "../lib/hooks";
import { SeverityBadge, StatusBadge } from "../components/badges";

type Incident = {
  id: string;
  title: string;
  status: string;
  severity: string;
  opened_at: string;
};

export default function IncidentsPage() {
  const fetcher = useCallback(() => api<{ incidents: Incident[] }>("/v1/incidents"), []);
  const { data, error } = usePoll(fetcher);

  return (
    <>
      <h1>Incidents</h1>
      {error && <div className="error">{error}</div>}
      <div className="panel table-scroll">
        <table>
          <thead>
            <tr>
              <th>Severity</th>
              <th>Status</th>
              <th>Incident</th>
              <th>Opened</th>
            </tr>
          </thead>
          <tbody>
            {data?.incidents.map((i) => (
              <tr key={i.id}>
                <td>
                  <SeverityBadge severity={i.severity} />
                </td>
                <td>
                  <StatusBadge status={i.status} />
                </td>
                <td>
                  <Link href={`/incidents/${i.id}`} className="pill-link">
                    {i.title}
                  </Link>
                </td>
                <td className="muted">{since(i.opened_at)}</td>
              </tr>
            ))}
            {data && data.incidents.length === 0 && (
              <tr>
                <td colSpan={4} className="muted">
                  No incidents.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
