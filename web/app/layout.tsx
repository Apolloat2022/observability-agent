import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "obsvagent — Observability",
  description: "Trace list, reasoning-path graph, and the Checker's audit review queue",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <nav
          style={{
            padding: "12px 20px",
            borderBottom: "1px solid var(--border)",
            display: "flex",
            gap: 20,
            alignItems: "center",
          }}
        >
          <strong>obsvagent</strong>
          <Link href="/observability">Traces</Link>
          <Link href="/observability/review">Review Queue</Link>
        </nav>
        <main style={{ padding: 20, maxWidth: 1100, margin: "0 auto" }}>{children}</main>
      </body>
    </html>
  );
}
