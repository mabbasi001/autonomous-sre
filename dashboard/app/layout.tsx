import "./globals.css";
import type { Metadata } from "next";
import { Nav } from "./components/Nav";

export const metadata: Metadata = {
  title: "Autonomous SRE",
  description: "Operator dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Nav />
        <main className="container">{children}</main>
      </body>
    </html>
  );
}
