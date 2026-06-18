type Props = {
  label?: string;
};

export default function LoadingState({ label }: Props) {
  return <p aria-live="polite">{label ?? "Loading…"}</p>;
}
