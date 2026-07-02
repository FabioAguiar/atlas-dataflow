import type { HTMLAttributes, ReactNode } from "react";

type CardProps = HTMLAttributes<HTMLElement> & {
  children: ReactNode;
  muted?: boolean;
};

export function Card({ children, className, muted = false, ...props }: CardProps) {
  const classes = ["atlas-card", muted ? "atlas-card--muted" : "", className].filter(Boolean).join(" ");

  return (
    <section className={classes} {...props}>
      {children}
    </section>
  );
}
