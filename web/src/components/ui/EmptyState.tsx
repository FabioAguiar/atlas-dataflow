import type { ReactNode } from "react";

type EmptyStateProps = {
  title: string;
  message?: string;
  action?: ReactNode;
};

export function EmptyState({ action, message, title }: EmptyStateProps) {
  return (
    <section className="atlas-empty-state" aria-label={title}>
      <h2>{title}</h2>
      {message && <p>{message}</p>}
      {action}
    </section>
  );
}
