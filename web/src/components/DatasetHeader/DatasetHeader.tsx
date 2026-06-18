type DatasetHeaderProps = {
  title: string;
  summary: string;
};

export default function DatasetHeader({ title, summary }: DatasetHeaderProps) {
  return (
    <header className="dataset-header">
      <section className="intro" aria-labelledby="dataset-title">
        <p className="eyebrow">Atlas DataFlow</p>
        <h1 id="dataset-title">{title}</h1>
        {summary && <p className="summary">{summary}</p>}
      </section>
    </header>
  );
}
