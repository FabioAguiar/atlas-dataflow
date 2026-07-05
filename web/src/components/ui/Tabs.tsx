import type { ButtonHTMLAttributes, ReactNode } from "react";

export type TabItem = {
  id: string;
  icon?: ReactNode;
  showIndicator?: boolean;
  label: string;
  disabled?: boolean;
};

type TabsProps = {
  items: TabItem[];
  selectedId: string;
  onSelect?: (id: string) => void;
  ariaLabel: string;
};

type TabButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  selected?: boolean;
};

export function TabButton({ className, selected = false, type = "button", ...props }: TabButtonProps) {
  const classes = ["atlas-tab", selected ? "is-selected" : "", className].filter(Boolean).join(" ");

  return <button aria-selected={selected} className={classes} role="tab" type={type} {...props} />;
}

export function Tabs({ ariaLabel, items, onSelect, selectedId }: TabsProps) {
  return (
    <div aria-label={ariaLabel} className="atlas-tabs" role="tablist">
      {items.map((item) => (
        <TabButton
          disabled={item.disabled}
          key={item.id}
          onClick={() => onSelect?.(item.id)}
          selected={item.id === selectedId}
        >
          {item.icon ? (
            <span aria-hidden="true" className="atlas-tab__icon">
              {item.icon}
            </span>
          ) : null}
          <span className="atlas-tab__label">{item.label}</span>
          {item.showIndicator ? <span aria-hidden="true" className="atlas-tab__indicator" /> : null}
        </TabButton>
      ))}
    </div>
  );
}
