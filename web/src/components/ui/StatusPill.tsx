import type { HTMLAttributes, ReactNode } from "react";

type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";

type StatusPillProps = HTMLAttributes<HTMLSpanElement> & {
  children: ReactNode;
  tone?: StatusTone;
};

export function StatusPill({ children, className, tone = "neutral", ...props }: StatusPillProps) {
  const classes = ["atlas-status-pill", tone !== "neutral" ? `atlas-status-pill--${tone}` : "", className]
    .filter(Boolean)
    .join(" ");

  return (
    <span className={classes} {...props}>
      {children}
    </span>
  );
}
