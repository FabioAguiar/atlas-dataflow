import type { ReactNode } from "react";

type ErrorStateProps = {
  title: string;
  message: string;
  action?: ReactNode;
};

export function ErrorState({ action, message, title }: ErrorStateProps) {
  return (
    <section className="atlas-error-state" aria-label={title} role="alert">
      <h2>{title}</h2>
      <p>{message}</p>
      {action}
    </section>
  );
}
