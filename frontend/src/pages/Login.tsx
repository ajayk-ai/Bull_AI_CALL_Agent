import { useState, type FormEvent } from "react";

import { Button, ErrorBox, Field, Input } from "../components/ui";
import { useAuth } from "../lib/auth";
import { useAction } from "../lib/hooks";

export function LoginPage() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const { busy, error, run } = useAction();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(() => signIn(email, password));
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-900 px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl">
        <h1 className="text-lg font-semibold">
          <span className="text-brand-600">Bull</span> AI Calling
        </h1>
        <p className="mb-5 text-sm text-slate-500">Sign in with your company account.</p>
        <ErrorBox error={error} />
        <div className="space-y-3">
          <Field label="Email">
            <Input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
          </Field>
          <Field label="Password">
            <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </Field>
          <Button type="submit" className="w-full" disabled={busy}>
            {busy ? "Signing in..." : "Sign in"}
          </Button>
        </div>
      </form>
    </div>
  );
}
