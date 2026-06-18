import ReactMarkdown from "react-markdown";

type ModelCardPayload = {
  content: string;
  format: "markdown";
};

type Props = {
  modelCard: ModelCardPayload;
};

export default function ModelCard({ modelCard }: Props) {
  return (
    <section className="model-card">
      <h2>Model Card</h2>
      <div className="model-card__content">
        <ReactMarkdown
          allowedElements={[
            "h1", "h2", "h3", "h4", "h5", "h6",
            "p", "ul", "ol", "li", "blockquote",
            "strong", "em", "code", "pre",
            "a", "hr", "br",
          ]}
          unwrapDisallowed
        >
          {modelCard.content}
        </ReactMarkdown>
      </div>
    </section>
  );
}
