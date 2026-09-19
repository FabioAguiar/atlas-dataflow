import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { useAdminAuth } from "../../auth/AdminAuthContext";

const UNAVAILABLE_MESSAGE = "Admin sign-in is unavailable.";
const FAILURE_MESSAGE = "Sign-in failed. Check your credentials and try again.";

export default function LoginPage() {
  const { signInWithEmailPassword, status } = useAdminAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [failed, setFailed] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  if (status === "loading") {
    return null;
  }
  if (status === "authenticated") {
    return <Navigate replace to="/admin/dashboard" />;
  }

  const unavailable = status === "unrecoverable";

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (unavailable || submitting) {
      return;
    }
    setSubmitting(true);
    setFailed(false);
    const ok = await signInWithEmailPassword(email.trim(), password);
    setPassword("");
    setSubmitting(false);
    if (ok) {
      navigate("/admin/dashboard", { replace: true });
    } else {
      setFailed(true);
    }
  }

  return (
    <main aria-label="Admin sign-in" style={{ margin: "10vh auto 0", maxWidth: "24rem", padding: "1.5rem" }}>
      <h1>Admin sign-in</h1>
      {unavailable ? <p role="alert">{UNAVAILABLE_MESSAGE}</p> : null}
      {failed && !unavailable ? <p role="alert">{FAILURE_MESSAGE}</p> : null}
      <form onSubmit={handleSubmit} style={{ display: "grid", gap: "0.75rem" }}>
        <label style={{ display: "grid", gap: "0.25rem" }}>
          Email
          <input
            autoComplete="username"
            disabled={unavailable}
            name="email"
            onChange={(event) => setEmail(event.target.value)}
            required
            type="email"
            value={email}
          />
        </label>
        <label style={{ display: "grid", gap: "0.25rem" }}>
          Password
          <input
            autoComplete="current-password"
            disabled={unavailable}
            name="password"
            onChange={(event) => setPassword(event.target.value)}
            required
            type="password"
            value={password}
          />
        </label>
        <button disabled={unavailable || submitting} type="submit">
          Sign in
        </button>
      </form>
    </main>
  );
}
