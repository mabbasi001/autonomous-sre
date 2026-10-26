# Dashboard

Operator UI for the Autonomous SRE platform. Next.js (App Router) + a
server-side proxy to the control plane, so the operator's bearer token
stays server-side and the browser only ever talks to this app.

## Pages

- **Incidents** — live list (severity, status, opened)
- **Incident detail** — status + allowed transitions (operator+), AI
  diagnosis with confidence, verification results, event timeline
- **Approvals** — pending queue with approve/reject (approver+)
- **Audit** — filterable audit log
- **Operations** — kill switches (admin flip) + agent inventory

Role gating in the UI is cosmetic; the control plane enforces RBAC on
every endpoint. The UI reads `GET /v1/me` to show/hide actions.

## Run

```bash
npm install
SRE_API_URL=http://localhost:8000 npm run dev    # http://localhost:3000
# or: npm run build && SRE_API_URL=... npm start
```

`SRE_API_URL` points at the control plane (default
`http://localhost:8000`). In development the backend's dev-fallback
authenticates without a token, so no login is needed locally; wiring
Entra ID login injects the bearer in `app/api/sre/[...path]/route.ts`.
