export type Feature = {
  name: string;
  label: string;
  input_type: "number" | "select" | "checkbox";
  optional: boolean;
  display_order: number;
  description?: string;
};

export type ContractPayload = {
  schema_version: string;
  features: Feature[];
};

type Props = {
  contract: ContractPayload;
};

export default function InferenceForm({ contract }: Props) {
  const sorted = [...contract.features].sort(
    (a, b) => a.display_order - b.display_order
  );

  return (
    <section aria-label="Inference Form">
      <h2>Make a Prediction</h2>
      <form>
        {sorted.map((feature) => (
          <div key={feature.name}>
            <label htmlFor={`field-${feature.name}`}>
              {feature.label}
              {feature.input_type === "select" && " (categorical field)"}
              {!feature.optional && <span aria-hidden="true"> *</span>}
            </label>
            {feature.input_type === "checkbox" ? (
              <input
                type="checkbox"
                id={`field-${feature.name}`}
                name={feature.name}
                required={!feature.optional}
              />
            ) : (
              <input
                type={feature.input_type === "number" ? "number" : "text"}
                id={`field-${feature.name}`}
                name={feature.name}
                required={!feature.optional}
              />
            )}
            {feature.description && <p>{feature.description}</p>}
          </div>
        ))}
        <button type="submit" disabled>
          Submit
        </button>
      </form>
    </section>
  );
}
