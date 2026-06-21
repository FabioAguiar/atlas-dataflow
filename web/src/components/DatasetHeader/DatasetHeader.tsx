type DatasetHeaderProps = {
  title: string;
  summary: string;
  domain?: string;
  tags?: string[];
  useCase?: string;
  problemType?: string;
  predictionTargetDescription?: string;
};

export default function DatasetHeader({
  title,
  summary,
  domain,
  tags = [],
  useCase,
  problemType,
  predictionTargetDescription,
}: DatasetHeaderProps) {
  const narrative = [
    { label: "Use case", value: useCase },
    { label: "Problem type", value: problemType },
    { label: "Prediction target", value: predictionTargetDescription },
  ].filter((item) => item.value);

  return (
    <header className="dataset-header">
      <section className="intro" aria-labelledby="dataset-title">
        <p className="eyebrow">Atlas DataFlow</p>
        <h1 id="dataset-title">{title}</h1>
        {summary && <p className="summary">{summary}</p>}
        {(domain || tags.length > 0) && (
          <div className="context-meta" aria-label="Dataset context">
            {domain && <span className="context-domain">{domain}</span>}
            {tags.length > 0 && (
              <ul className="tag-list" aria-label="Dataset tags">
                {tags.map((tag) => (
                  <li key={tag}>{tag}</li>
                ))}
              </ul>
            )}
          </div>
        )}
        {narrative.length > 0 && (
          <dl className="context-narrative">
            {narrative.map((item) => (
              <div key={item.label}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>
    </header>
  );
}
