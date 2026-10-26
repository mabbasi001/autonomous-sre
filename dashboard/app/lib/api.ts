export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`/api/sre${path}`, {
    ...init,
    headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json()).detail ?? detail;
    } catch {
      /* non-json error body */
    }
    throw new Error(`${resp.status} ${detail}`);
  }
  return resp.json();
}

export const ROLES = ["viewer", "operator", "approver", "admin"];

export function roleAtLeast(role: string | undefined, min: string): boolean {
  if (!role) return false;
  return ROLES.indexOf(role) >= ROLES.indexOf(min);
}

export function since(iso: string | null): string {
  if (!iso) return "never";
  const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.round(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.round(secs / 3600)}h ago`;
  return `${Math.round(secs / 86400)}d ago`;
}
