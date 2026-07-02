import type { ReactNode } from "react";

type FormRowProps = {
  children: ReactNode;
  helpText?: string;
  label: string;
  htmlFor?: string;
};

export function FormRow({ children, helpText, htmlFor, label }: FormRowProps) {
  return (
    <div className="atlas-form-row">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {helpText && <p className="atlas-form-row__help">{helpText}</p>}
    </div>
  );
}
