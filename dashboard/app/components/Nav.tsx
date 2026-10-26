"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMe } from "../lib/hooks";

const LINKS = [
  ["/incidents", "Incidents"],
  ["/approvals", "Approvals"],
  ["/audit", "Audit"],
  ["/operations", "Operations"],
];

export function Nav() {
  const pathname = usePathname();
  const me = useMe();
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
    </nav>
  );
}
