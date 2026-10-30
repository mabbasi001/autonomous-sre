"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useMe } from "../lib/hooks";

const LINKS = [
  ["/incidents", "Incidents"],
  ["/approvals", "Approvals"],
  ["/audit", "Audit"],
  ["/operations", "Operations"],
];

export function Nav() {
  const pathname = usePathname();
  const router = useRouter();
  const me = useMe();

  // The login page has no nav.
  if (pathname === "/login") return null;

  async function signOut() {
    await fetch("/api/auth/logout", { method: "POST" });
    router.replace("/login");
    router.refresh();
  }

  return (
    <nav className="nav">
      <span className="brand">Autonomous SRE</span>
      {LINKS.map(([href, label]) => (
        <Link
          key={href}
          href={href}
          className={pathname.startsWith(href) ? "active" : ""}
        >
          {label}
        </Link>
      ))}
      <span className="spacer" />
      {me && (
        <span className="whoami">
          {me.email} · <span className="role">{me.role}</span>
        </span>
      )}
      <button type="button" className="signout" onClick={signOut}>
        Sign out
      </button>
    </nav>
  );
}
