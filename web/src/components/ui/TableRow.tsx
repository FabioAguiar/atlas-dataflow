import type { ReactNode } from "react";

type TableRowProps = {
  actions?: ReactNode;
  children: ReactNode;
  meta?: ReactNode;
};

export function TableRow({ actions, children, meta }: TableRowProps) {
  return (
    <div className="atlas-table-row" role="row">
      <div>
        {children}
        {meta && <div className="atlas-table-row__meta">{meta}</div>}
      </div>
      {actions}
    </div>
  );
}
