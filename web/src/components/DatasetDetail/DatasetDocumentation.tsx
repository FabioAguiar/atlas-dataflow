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
};

// Project Spec S0196: the single shared, presentation-only Markdown
// Documentation renderer used by both the Admin Documentation tab/Live
// Preview and the public Dataset Detail Documentation tab. Deliberately has
// no data fetching and no knowledge of Admin state, route params, profile
// stores, or publication state -- every value arrives as a prop.
//
// Raw HTML is never enabled (no rehype-raw plugin is registered, so HTML
// tags in the Markdown source are inert text, not executed markup) and
// `img` is deliberately excluded from allowedElements -- Markdown image
// syntax renders no `img` element in S0196. Link/image URLs are bounded by
// react-markdown's own default safe-URL transform, which strips unsafe
// schemes like `javascript:` down to an inert empty href.
const ALLOWED_ELEMENTS = [
  "h1", "h2", "h3", "h4", "h5", "h6",
  "p", "strong", "em",
  "ul", "ol", "li",
  "blockquote",
  "code", "pre",
  "hr", "br",
  "a",
  "table", "thead", "tbody", "tr", "th", "td",
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

export default function DatasetDocumentation({ content }: DatasetDocumentationProps) {
  const source = resolveMarkdownSource(content).trim();

  if (!source) {
    return (
      <div className="dataset-documentation dataset-documentation--empty">
        <p className="dataset-documentation__empty-state">No documentation has been published yet.</p>
      </div>
    );
  }

  return (
    <div className="dataset-documentation">
      <ReactMarkdown
        allowedElements={ALLOWED_ELEMENTS}
        components={{
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
