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

// Project Spec S0196/S0199: the single shared, presentation-only Markdown
// Documentation renderer used by both the Admin Documentation tab/Live
// Preview and the public Dataset Detail Documentation tab. Deliberately has
// no data fetching and no knowledge of Admin state, route params, profile
// stores, or publication state -- every value arrives as a prop.
//
// Raw HTML is never enabled (no rehype-raw plugin is registered, so HTML
// tags in the Markdown source are inert text, not executed markup). `img`
// is allowed only through an explicit component override (S0199) that
// independently re-validates `src` against a bounded, exact external
// `https://raw.githubusercontent.com/...` image policy before rendering --
// react-markdown's own default safe-URL transform (which strips unsafe
// schemes like `javascript:` down to an inert empty href) still applies
// first, but is never relied upon alone.
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

const RAW_GITHUB_IMAGE_HOSTNAME = "raw.githubusercontent.com";
// owner/repository/ref/path -- the minimum segment count for a real raw
// GitHub file reference.
const MIN_RAW_GITHUB_PATH_SEGMENTS = 4;
const ALLOWED_RAW_GITHUB_IMAGE_EXTENSIONS = new Set(["png", "jpg", "jpeg", "webp", "avif"]);

function resolveMarkdownSource(content: DatasetDocumentationProps["content"]): string {
  if (typeof content === "string") {
    return content;
  }
  if (content && typeof content === "object" && content.format === "markdown") {
    return content.content;
  }
  return "";
}

// Project Spec S0199: bounded external-image source policy. Only an exact
// `https://raw.githubusercontent.com` reference -- no credentials, no
// explicit non-default port, no query string or fragment, an
// owner/repository/ref/path-shaped absolute path, and an approved image
// extension -- is accepted. Parsed with the platform `URL` constructor
// (never substring/`includes` matching, which an attacker-controlled
// hostname like `raw.githubusercontent.com.evil.example` could bypass).
// `github.com/.../blob/...` pages are never auto-converted -- explicit
// author intent in the Markdown source is preserved.
function isAllowedExternalImageSource(src: string): boolean {
  let url: URL;
  try {
    url = new URL(src);
  } catch {
    return false;
  }

  if (url.protocol !== "https:") return false;
  if (url.hostname !== RAW_GITHUB_IMAGE_HOSTNAME) return false;
  if (url.username || url.password) return false;
  // The URL parser normalizes an explicit default port (443 for https:)
  // away to "" -- only a genuinely non-default explicit port survives here.
  if (url.port !== "") return false;
  if (url.search !== "") return false;
  if (url.hash !== "") return false;

  const segments = url.pathname.split("/").filter(Boolean);
  if (segments.length < MIN_RAW_GITHUB_PATH_SEGMENTS) return false;

  const finalSegment = segments[segments.length - 1];
  const extensionMatch = /\.([a-z0-9]+)$/i.exec(finalSegment);
  const extension = extensionMatch?.[1]?.toLowerCase();
  return !!extension && ALLOWED_RAW_GITHUB_IMAGE_EXTENSIONS.has(extension);
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
          img: ({ alt, src }) => {
            if (typeof src !== "string" || !isAllowedExternalImageSource(src)) {
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
