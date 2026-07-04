import { createContext, useContext, useMemo, useState, type ReactNode } from "react";

/**
 * Mirrors registry/admin_settings_store.py's DEFAULT_ADMIN_SETTINGS.display_name,
 * so the shell shows the same value the backend would return before any
 * settings have been loaded in this session.
 */
export const DEFAULT_ADMIN_DISPLAY_NAME = "Internal operator";

type AdminSettingsContextValue = {
  displayName: string;
  setDisplayName: (displayName: string) => void;
};

const AdminSettingsContext = createContext<AdminSettingsContextValue | null>(null);

export function AdminSettingsProvider({ children }: { children: ReactNode }) {
  const [displayName, setDisplayName] = useState(DEFAULT_ADMIN_DISPLAY_NAME);

  const value = useMemo(() => ({ displayName, setDisplayName }), [displayName]);

  return <AdminSettingsContext.Provider value={value}>{children}</AdminSettingsContext.Provider>;
}

export function useAdminSettings(): AdminSettingsContextValue {
  const context = useContext(AdminSettingsContext);
  if (!context) {
    throw new Error("useAdminSettings must be used within an AdminSettingsProvider");
  }
  return context;
}
