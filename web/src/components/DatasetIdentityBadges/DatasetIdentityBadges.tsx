import { Badge } from "../ui";
import { getPerformanceFocusLabel } from "../../lib/performanceMetricMetadata";

export type DatasetIdentityBadgesProps = {
  /**
   * Already-resolved problem label (e.g. "Continuous Regression"). This
   * component performs no problem-type resolution or humanization itself --
   * callers own that authority (getProblemTypeLabel on Home,
   * release-bound humanization on Dataset Detail) and stay separate per
   * surface, per Project Spec S0238.
   */
  problemLabel?: string | null;
  /**
   * Raw Performance focus id, resolved to a label here through the same
   * shared getPerformanceFocusLabel(...) authority every surface already
   * uses. An unknown/missing focus id omits the badge entirely -- it is
   * never rendered blank and never falls back to a hardcoded focus label.
   */
  performanceFocusId?: string | null;
  /**
   * Bounded release-bound model display name. Blank/whitespace-only values
   * omit the Model badge rather than rendering empty text.
   */
  modelDisplayName?: string | null;
  /** Preserves the surface-specific badge-row wrapper class/layout hook. */
  groupClassName?: string;
};

/**
 * Project Spec S0238: the single shared presentational Dataset identity
 * badge composition. Project Spec S0286 retired its Home Card renderer --
 * DatasetCard (Home, and its Admin Metadata & Card / Live Preview Home Card
 * previews) no longer imports or renders this component. DatasetDetailHeader
 * (Dataset Detail, including its Dataset Admin Live Preview counterpart)
 * remains its sole owner. Accepts only already-bounded semantic values -- no
 * fetch, registry/release inspection, or per-surface semantic branching
 * happens here. Renders the known roles in the fixed order problem -> focus
 * -> model, each carrying its own Theme Preset-derived color role
 * (dataset-identity-badge--problem/--focus/--model in App.css) while badge
 * text alone remains the semantic authority.
 */
export default function DatasetIdentityBadges({
  problemLabel,
  performanceFocusId,
  modelDisplayName,
  groupClassName,
}: DatasetIdentityBadgesProps) {
  const performanceFocusLabel = getPerformanceFocusLabel(performanceFocusId);
  const trimmedModelDisplayName = modelDisplayName?.trim() || null;

  if (!problemLabel && !performanceFocusLabel && !trimmedModelDisplayName) {
    return null;
  }

  return (
    <div className={["dataset-identity-badges", groupClassName].filter(Boolean).join(" ")}>
      {problemLabel && <Badge className="dataset-identity-badge--problem">{problemLabel}</Badge>}
      {performanceFocusLabel && (
        <Badge className="dataset-identity-badge--focus">{performanceFocusLabel}</Badge>
      )}
      {trimmedModelDisplayName && (
        <Badge className="dataset-identity-badge--model">{trimmedModelDisplayName}</Badge>
      )}
    </div>
  );
}
