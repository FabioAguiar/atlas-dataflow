type Props = {
  message: string;
};

export default function ErrorState({ message }: Props) {
  return <p role="alert">{message}</p>;
}
