import type { HTMLAttributes, ReactNode } from "react";

type StatusTone = "neutral" | "info" | "success" | "warning" | "danger";
type StatusVariant = "published" | "pending" | "hidden" | "draft" | "not-published";

type StatusPillProps = HTMLAttributes<HTMLSpanElement> & {
  children: ReactNode;
  tone?: StatusTone;
  variant?: StatusVariant;
};

export function StatusPill({ children, className, tone = "neutral", variant, ...props }: StatusPillProps) {
  const classes = [
    "atlas-status-pill",
    tone !== "neutral" ? `atlas-status-pill--${tone}` : "",
    variant ? `atlas-status-pill--${variant}` : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span className={classes} {...props}>
      {variant ? <i aria-hidden="true" className="atlas-status-pill__indicator" /> : null}
      {children}
    </span>
  );
}
