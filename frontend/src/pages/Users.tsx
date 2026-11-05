import { useState, type FormEvent } from "react";

import { Badge, Button, Card, ErrorBox, Field, Input, Loading, Notice, PageHeader, Pager, ROLE_NAMES, Select, Table, Td, formatDate } from "../components/ui";
import { api, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction, useApi } from "../lib/hooks";
import type { Department, Page, Role, User, UserCredentials } from "../lib/types";

const PAGE_SIZE = 50;
const ROLES: Role[] = ["user", "admin"];

export const ROLE_ACCESS: Record<Role, string> = {
  user: "All the calling work of their own department: contacts, uploads, scripts, campaigns, calls and do-not-call. Approving a script or campaign needs a second person.",
  admin: "Everything, in every department. Creates accounts, manages departments and sees the audit log.",
};

export function UsersPage() {
  const { me, can } = useAuth();
  const isAdmin = can("users:manage");
  const departments = useApi<Department[]>("/departments");
  const [filters, setFilters] = useState({ search: "", department_id: "", role: "", is_active: "true" });
  const [applied, setApplied] = useState(filters);
  const [page, setPage] = useState(1);
  const list = useApi<Page<User>>(`/users${query({ ...applied, page, page_size: PAGE_SIZE })}`);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [credentials, setCredentials] = useState<UserCredentials | null>(null);
  const action = useAction();
  const deptName = (id: string | null) => (id ? (departments.data?.find((d) => d.id === id)?.code ?? "-") : "All");

  const act = (fn: () => Promise<unknown>) =>
    action.run(async () => {
      await fn();
      list.reload();
    });

  const reset = (user: User) => {
    if (!window.confirm(`Reset the password of ${user.full_name} (${user.username})? They will be signed out and get a temporary password.`)) return;
    act(async () => setCredentials(await api.post<UserCredentials>(`/users/${user.id}/reset-password`, {})));
  };

  const toggle = (user: User) => {
    if (user.is_active && !window.confirm(`Deactivate ${user.full_name}? They will be signed out and cannot sign in.`)) return;
    act(() => api.patch(`/users/${user.id}`, { is_active: !user.is_active }));
  };

  return (
    <>
      <PageHeader
        title="Users and access"
        subtitle="Accounts for every department. Only the admin creates accounts and gives access."
        actions={
          isAdmin && (
            <Button
              onClick={() => {
                setCredentials(null);
                setCreating(true);
              }}
            >
              New account
            </Button>
          )
        }
      />
      <ErrorBox error={list.error || action.error} />
      {credentials && <CredentialsPanel credentials={credentials} onClose={() => setCredentials(null)} />}
      {creating && (
        <AccountForm
          departments={departments.data ?? []}
          onCancel={() => setCreating(false)}
          onCreated={(c) => {
            setCreating(false);
            setCredentials(c);
            list.reload();
          }}
        />
      )}
      {editing && (
        <AccountForm
          departments={departments.data ?? []}
          user={editing}
          onCancel={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            list.reload();
          }}
        />
      )}

      <Card>
        <form
          className="mb-3 grid gap-2 md:grid-cols-[2fr_1fr_1fr_1fr_auto]"
          onSubmit={(e) => {
            e.preventDefault();
            setPage(1);
            setApplied(filters);
          }}
        >
          <Input placeholder="Search user ID, name or email" value={filters.search} onChange={(e) => setFilters({ ...filters, search: e.target.value })} />
          {me?.role === "admin" ? (
            <Select value={filters.department_id} onChange={(e) => setFilters({ ...filters, department_id: e.target.value })}>
              <option value="">All departments</option>
              {departments.data?.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.code}
                </option>
              ))}
            </Select>
          ) : (
            <span />
          )}
          <Select value={filters.role} onChange={(e) => setFilters({ ...filters, role: e.target.value })}>
            <option value="">Users and admins</option>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_NAMES[r]}
              </option>
            ))}
          </Select>
          <Select value={filters.is_active} onChange={(e) => setFilters({ ...filters, is_active: e.target.value })}>
            <option value="true">Active</option>
            <option value="false">Deactivated</option>
            <option value="">Active and deactivated</option>
          </Select>
          <Button type="submit" variant="secondary">
            Filter
          </Button>
        </form>

        {list.loading && !list.data ? (
          <Loading />
        ) : (
          <>
            <Table headers={["User ID", "Name", "Access", "Department", "Last sign-in", ""]} empty={list.data?.items.length === 0}>
              {list.data?.items.map((u) => (
                <tr key={u.id} className={u.is_active ? "" : "text-slate-400"}>
                  <Td className="font-mono text-xs">{u.username}</Td>
                  <Td>
                    <p>
                      {u.full_name} {!u.is_active && <Badge>deactivated</Badge>} {u.locked && <Badge tone="red">locked</Badge>}{" "}
                      {u.must_change_password && u.is_active && <Badge tone="amber">password not yet changed</Badge>}
                    </p>
                    {u.email && <p className="text-xs text-slate-500">{u.email}</p>}
                  </Td>
                  <Td>{ROLE_NAMES[u.role]}</Td>
                  <Td>{deptName(u.department_id)}</Td>
                  <Td className="whitespace-nowrap">{u.last_login_at ? formatDate(u.last_login_at, true) : "Never"}</Td>
                  <Td className="whitespace-nowrap text-right">
                    {isAdmin && (
                      <div className="flex flex-wrap justify-end gap-1">
                        <Button variant="ghost" onClick={() => setEditing(u)}>
                          Edit
                        </Button>
                        <Button variant="ghost" onClick={() => reset(u)}>
                          Reset password
                        </Button>
                        {u.locked && (
                          <Button variant="ghost" onClick={() => act(() => api.post(`/users/${u.id}/unlock`))}>
                            Unlock
                          </Button>
                        )}
                        {u.id !== me?.id && (
                          <Button variant="ghost" onClick={() => toggle(u)}>
                            {u.is_active ? "Deactivate" : "Activate"}
                          </Button>
                        )}
                      </div>
                    )}
                  </Td>
                </tr>
              ))}
            </Table>
            <p className="mt-2 text-xs text-slate-500">{list.data?.total ?? 0} accounts</p>
            <Pager page={page} pageSize={PAGE_SIZE} total={list.data?.total ?? 0} onPage={setPage} />
          </>
        )}
      </Card>

      <Card title="What each account can do" className="mt-4">
        <dl className="grid gap-3 text-sm md:grid-cols-2">
          {ROLES.map((r) => (
            <div key={r}>
              <dt className="font-medium">{ROLE_NAMES[r]}</dt>
              <dd className="text-slate-600">{ROLE_ACCESS[r]}</dd>
            </div>
          ))}
        </dl>
      </Card>
    </>
  );
}

function CredentialsPanel({ credentials, onClose }: { credentials: UserCredentials; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const { user, temporary_password } = credentials;
  const text = `Bull AI Calling\nAddress: ${window.location.origin}${import.meta.env.BASE_URL}\nUser ID: ${user.username}\nTemporary password: ${temporary_password}\nYou will be asked to choose your own password at first sign-in.`;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  return (
    <Card title={`Sign-in details for ${user.full_name}`} className="mb-4 border-emerald-300">
      <Notice tone="green">Give these to the user. The temporary password is shown only now; they must change it at first sign-in.</Notice>
      <dl className="mb-3 grid max-w-md grid-cols-[11rem_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-slate-500">User ID</dt>
        <dd className="font-mono">{user.username}</dd>
        <dt className="text-slate-500">Temporary password</dt>
        <dd className="font-mono text-base">{temporary_password}</dd>
      </dl>
      <div className="flex gap-2">
        <Button variant="secondary" onClick={copy}>
          {copied ? "Copied" : "Copy details"}
        </Button>
        <Button variant="ghost" onClick={onClose}>
          Done
        </Button>
      </div>
    </Card>
  );
}

function AccountForm({
  departments,
  user,
  onCancel,
  onCreated,
  onSaved,
}: {
  departments: Department[];
  user?: User;
  onCancel: () => void;
  onCreated?: (c: UserCredentials) => void;
  onSaved?: () => void;
}) {
  const { me } = useAuth();
  const [form, setForm] = useState({
    username: user?.username ?? "",
    full_name: user?.full_name ?? "",
    email: user?.email ?? "",
    role: (user?.role ?? "user") as Role,
    department_id: user?.department_id ?? "",
    passwordMode: "generate" as "generate" | "set",
    password: "",
  });
  const { busy, error, run } = useAction();
  const editingSelf = user?.id === me?.id;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const department = form.role === "admin" ? null : form.department_id || null;
    run(async () => {
      if (user) {
        await api.patch(`/users/${user.id}`, {
          full_name: form.full_name,
          email: form.email || null,
          ...(editingSelf ? {} : { role: form.role, department_id: department }),
        });
        onSaved?.();
      } else {
        onCreated?.(
          await api.post<UserCredentials>("/users", {
            username: form.username,
            full_name: form.full_name,
            email: form.email || null,
            role: form.role,
            department_id: department,
            password: form.passwordMode === "set" ? form.password : null,
          }),
        );
      }
    });
  };

  return (
    <Card title={user ? `Edit ${user.full_name}` : "New account"} className="mb-4">
      <ErrorBox error={error} />
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
        <Field label="User ID" hint={user ? "User IDs cannot be changed" : "Used to sign in. Letters, digits, dot, dash, underscore; at least 3 characters."}>
          <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} disabled={!!user} required pattern="[A-Za-z0-9][A-Za-z0-9._\-]{2,63}" />
        </Field>
        <Field label="Full name">
          <Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required />
        </Field>
        <Field label="Email (optional)">
          <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </Field>
        <Field label="Access" hint={editingSelf ? "You cannot change your own access." : ROLE_ACCESS[form.role]}>
          <Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })} disabled={editingSelf}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE_NAMES[r]}
              </option>
            ))}
          </Select>
        </Field>
        {form.role !== "admin" && (
          <Field label="Department">
            <Select value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })} required disabled={editingSelf}>
              <option value="">Choose...</option>
              {departments
                .filter((d) => d.is_active)
                .map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.code} · {d.name}
                  </option>
                ))}
            </Select>
          </Field>
        )}
        {!user && (
          <div className="md:col-span-2">
            <span className="mb-1 block text-xs font-medium uppercase tracking-wide text-slate-600">Password</span>
            <div className="flex flex-wrap items-center gap-4 text-sm">
              <label className="flex items-center gap-1">
                <input type="radio" checked={form.passwordMode === "generate"} onChange={() => setForm({ ...form, passwordMode: "generate" })} />
                Generate a temporary password
              </label>
              <label className="flex items-center gap-1">
                <input type="radio" checked={form.passwordMode === "set"} onChange={() => setForm({ ...form, passwordMode: "set" })} />
                Set one myself
              </label>
              {form.passwordMode === "set" && (
                <Input className="max-w-xs" type="text" autoComplete="off" minLength={10} placeholder="At least 10 characters" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
              )}
            </div>
            <p className="mt-1 text-xs text-slate-500">Either way, the user must choose their own password at first sign-in.</p>
          </div>
        )}
        <div className="flex gap-2 md:col-span-2">
          <Button type="submit" disabled={busy}>
            {user ? "Save" : "Create account"}
          </Button>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}
