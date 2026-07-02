import type { ButtonHTMLAttributes } from "react";

export type TabItem = {
  id: string;
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
  const classes = ["atlas-tab", className].filter(Boolean).join(" ");

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
          {item.label}
        </TabButton>
      ))}
    </div>
  );
}
