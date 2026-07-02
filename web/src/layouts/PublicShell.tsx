import type { ReactNode } from "react";
import { Link } from "react-router-dom";

type PublicShellProps = {
  children: ReactNode;
};

export default function PublicShell({ children }: PublicShellProps) {
  return (
    <div className="public-shell">
      <header className="public-shell__header">
        <Link className="public-shell__brand" to="/">
          Atlas DataFlow
        </Link>
      </header>
      <main className="app-shell">{children}</main>
    </div>
  );
}
