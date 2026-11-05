import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";

import { Button, Card, ErrorBox, Field, Input, Notice, PageHeader } from "../components/ui";
import { api, tokens } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction } from "../lib/hooks";

const MIN_LENGTH = 10;

function PasswordForm({ onDone, submitLabel, currentLabel = "Current password" }: { onDone: () => void; submitLabel: string; currentLabel?: string }) {
  const [form, setForm] = useState({ current: "", next: "", repeat: "" });
  const [mismatch, setMismatch] = useState(false);
  const { busy, error, run } = useAction();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (form.next !== form.repeat) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    run(async () => {
      const result = await api.post<{ access_token: string; refresh_token: string }>("/auth/change-password", {
        current_password: form.current,
        new_password: form.next,
      });
      // Changing the password signs out other sessions; this one continues with the new tokens.
      tokens.set(result.access_token, result.refresh_token);
      onDone();
    });
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <ErrorBox error={error} />
      {mismatch && <ErrorBox error={new Error("The two new passwords are not the same")} />}
      <Field label={currentLabel}>
        <Input type="password" autoComplete="current-password" value={form.current} onChange={(e) => setForm({ ...form, current: e.target.value })} required />
      </Field>
      <Field label="New password" hint={`At least ${MIN_LENGTH} characters`}>
        <Input type="password" autoComplete="new-password" minLength={MIN_LENGTH} value={form.next} onChange={(e) => setForm({ ...form, next: e.target.value })} required />
      </Field>
      <Field label="New password again">
        <Input type="password" autoComplete="new-password" minLength={MIN_LENGTH} value={form.repeat} onChange={(e) => setForm({ ...form, repeat: e.target.value })} required />
      </Field>
      <Button type="submit" disabled={busy}>
        {submitLabel}
      </Button>
    </form>
  );
}

/** Shown instead of the app when the admin set this user's password. */
export function ForcedPasswordChange() {
  const { me, refreshMe, signOut } = useAuth();
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-900 px-4">
      <div className="w-full max-w-sm rounded-lg bg-white p-6 shadow-xl">
        <h1 className="text-lg font-semibold">Choose your password</h1>
        <p className="mb-4 text-sm text-slate-500">
          Welcome, {me?.full_name}. Your password was set by the admin; choose your own to continue. Your user ID is{" "}
          <b className="font-mono">{me?.username}</b>.
        </p>
        <PasswordForm onDone={refreshMe} submitLabel="Save and continue" currentLabel="Temporary password (from the admin)" />
        <button className="mt-4 text-xs text-slate-500 hover:text-slate-900" onClick={signOut}>
          Sign out
        </button>
      </div>
    </div>
  );
}

export function ChangePasswordPage() {
  const navigate = useNavigate();
  const [done, setDone] = useState(false);
  return (
    <>
      <PageHeader title="Change password" subtitle="Other signed-in sessions are signed out." />
      <Card className="max-w-md">
        {done ? (
          <>
            <Notice tone="green">Password changed.</Notice>
            <Button onClick={() => navigate("/")}>Done</Button>
          </>
        ) : (
          <PasswordForm onDone={() => setDone(true)} submitLabel="Change password" />
        )}
      </Card>
    </>
  );
}
