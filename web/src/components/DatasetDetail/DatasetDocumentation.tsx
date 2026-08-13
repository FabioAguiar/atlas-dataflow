import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export type DatasetDocumentationPayload = {
  format: "markdown";
  content: string;
};

export type DatasetDocumentationProps = {
  // Project Spec S0196: accepts either a bare Markdown source string or the
  // bounded {format, content} documentation payload shared by the draft and
  // published-snapshot contracts, so both Admin (form.documentation, a
  // plain string) and the public route (context.documentation, the
  // payload shape) can feed this same renderer directly.
  content?: string | DatasetDocumentationPayload | null;
  // Project Spec S0197: the current dataset's slug, used exclusively to
  // bound which generated Documentation media `img` references this
  // renderer will accept -- never used for data fetching.
  datasetSlug?: string;
};

// Project Spec S0196/S0197: the single shared, presentation-only Markdown
// Documentation renderer used by both the Admin Documentation tab/Live
// Preview and the public Dataset Detail Documentation tab. Deliberately has
// no data fetching and no knowledge of Admin state, route params, profile
// stores, or publication state -- every value arrives as a prop.
//
// Raw HTML is never enabled (no rehype-raw plugin is registered, so HTML
// tags in the Markdown source are inert text, not executed markup). `img`
// is allowed only through an explicit component override (S0197) that
// independently re-validates `src` against a bounded, exact
// `/media/documentation/{datasetSlug}/{32hex}.{ext}` pattern before
// rendering -- react-markdown's own default safe-URL transform (which
// strips unsafe schemes like `javascript:` down to an inert empty href)
// still applies first, but is never relied upon alone.
const ALLOWED_ELEMENTS = [
  "h1", "h2", "h3", "h4", "h5", "h6",
  "p", "strong", "em",
  "ul", "ol", "li",
  "blockquote",
  "code", "pre",
  "hr", "br",
  "a",
  "table", "thead", "tbody", "tr", "th", "td",
  "img",
];

function resolveMarkdownSource(content: DatasetDocumentationProps["content"]): string {
  if (typeof content === "string") {
    return content;
  }
  if (content && typeof content === "object" && content.format === "markdown") {
    return content.content;
  }
  return "";
}

function escapeForRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Exact match only -- no query strings, fragments, protocol-relative or
// absolute URLs, and no other dataset's or Home card's media namespace.
function buildSafeDocumentationImagePattern(datasetSlug: string): RegExp {
  return new RegExp(`^/media/documentation/${escapeForRegExp(datasetSlug)}/[0-9a-f]{32}\\.(?:png|jpg|webp|avif)$`);
}

export default function DatasetDocumentation({ content, datasetSlug }: DatasetDocumentationProps) {
  const source = resolveMarkdownSource(content).trim();

  if (!source) {
    return (
      <div className="dataset-documentation dataset-documentation--empty">
        <p className="dataset-documentation__empty-state">No documentation has been published yet.</p>
      </div>
    );
  }

  const safeImagePattern = buildSafeDocumentationImagePattern(datasetSlug ?? "");

  return (
    <div className="dataset-documentation">
      <ReactMarkdown
        allowedElements={ALLOWED_ELEMENTS}
        components={{
          img: ({ alt, src }) => {
            if (typeof src !== "string" || !safeImagePattern.test(src)) {
              return null;
            }
            return <img alt={alt ?? ""} decoding="async" loading="lazy" src={src} />;
          },
          table: ({ children }) => (
            <div className="dataset-documentation__table-wrapper">
              <table>{children}</table>
            </div>
          ),
        }}
        remarkPlugins={[remarkGfm]}
        unwrapDisallowed
      >
        {source}
      </ReactMarkdown>
    </div>
  );
}
