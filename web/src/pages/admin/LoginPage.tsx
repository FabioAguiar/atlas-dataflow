import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";

import { useAdminAuth, type AdminSignInResult } from "../../auth/AdminAuthContext";

const UNAVAILABLE_MESSAGE = "Admin sign-in is unavailable.";
const FAILURE_MESSAGE = "Sign-in failed. Check your credentials and try again.";
const VERIFICATION_FAILURE_MESSAGE = "Security verification failed. Please try signing in again.";
const PENDING_MESSAGE = "Verifying and signing in…";

export default function LoginPage() {
  const { signInWithEmailPassword, status } = useAdminAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [failure, setFailure] = useState<Exclude<AdminSignInResult, "authenticated"> | null>(null);
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
    setFailure(null);
    const result = await signInWithEmailPassword(email.trim(), password);
    setPassword("");
    setSubmitting(false);
    if (result === "authenticated") {
      navigate("/admin/dashboard", { replace: true });
    } else {
      setFailure(result === "verification_failed" ? "verification_failed" : "failed");
    }
  }

  return (
    <main aria-label="Admin sign-in" style={{ margin: "10vh auto 0", maxWidth: "24rem", padding: "1.5rem" }}>
      <h1>Admin sign-in</h1>
      {unavailable ? <p role="alert">{UNAVAILABLE_MESSAGE}</p> : null}
      {failure && !unavailable ? (
        <p role="alert">{failure === "verification_failed" ? VERIFICATION_FAILURE_MESSAGE : FAILURE_MESSAGE}</p>
      ) : null}
      {submitting ? <p role="status">{PENDING_MESSAGE}</p> : null}
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
