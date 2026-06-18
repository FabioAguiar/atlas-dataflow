import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type ChartDataPoint = {
  name: string;
  value: number;
};

type Chart = {
  id: string;
  title: string;
  type: "bar" | "line";
  x_label?: string;
  y_label?: string;
  data: ChartDataPoint[];
};

export type VisualizationsPayload = {
  charts: Chart[];
};

type Props = {
  visualizations: VisualizationsPayload;
};

function renderChart(chart: Chart) {
  if (chart.type === "bar") {
    return (
      <BarChart data={chart.data}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="name" />
        <YAxis />
        <Tooltip />
        <Bar dataKey="value" fill="#4f46e5" />
      </BarChart>
    );
  }
  return (
    <LineChart data={chart.data}>
      <CartesianGrid strokeDasharray="3 3" />
      <XAxis dataKey="name" />
      <YAxis />
      <Tooltip />
      <Line type="monotone" dataKey="value" stroke="#4f46e5" dot={false} />
    </LineChart>
  );
}

export default function DatasetVisualizations({ visualizations }: Props) {
  return (
    <section aria-label="Dataset Visualizations">
      {visualizations.charts.map((chart) => (
        <div key={chart.id}>
          <h3>{chart.title}</h3>
          <ResponsiveContainer width="100%" height={300}>
            {renderChart(chart)}
          </ResponsiveContainer>
        </div>
      ))}
    </section>
  );
}
