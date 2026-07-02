export type ConfidenceTone = "success" | "warning" | "danger";

/**
 * Deterministic placeholder default: buckets confidence into the existing
 * StatusPill tone vocabulary. Not admin-driven customization data -- this is
 * the fixed shape a later, explicitly admin-driven milestone can override.
 */
export function confidenceTone(confidence: number): ConfidenceTone {
  if (confidence >= 0.75) return "success";
  if (confidence >= 0.5) return "warning";
  return "danger";
}

/**
 * Mirrors pipeline/contract_derivation.py's _fresh_label convention
 * (replace _/- with spaces, title case) on the client side.
 */
export function formatResultLabel(label: string): string {
  return label
    .replace(/_/g, " ")
    .replace(/-/g, " ")
    .replace(/\w\S*/g, (word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase());
}
