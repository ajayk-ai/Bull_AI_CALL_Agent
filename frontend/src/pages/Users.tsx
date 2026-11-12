import { useEffect, useState, type FormEvent } from "react";

import {
  Avatar,
  Badge,
  Button,
  Card,
  ChoiceCards,
  Drawer,
  EmptyState,
  ErrorBox,
  Field,
  Icon,
  Input,
  Loading,
  Menu,
  Modal,
  PageHeader,
  Pager,
  ROLE_NAMES,
  Segmented,
  Select,
  Step,
  Table,
  Td,
  formatDate,
} from "../components/ui";
import { api, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction, useApi } from "../lib/hooks";
import type { Department, Page, Role, User, UserCredentials } from "../lib/types";

const PAGE_SIZE = 50;
const ROLES: Role[] = ["user", "admin"];
const USERNAME = /^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$/;

export const ROLE_ACCESS: Record<Role, string> = {
  user: "All the calling work of their own department: contacts, uploads, scripts, campaigns, calls and do-not-call. Approving a script or campaign needs a second person.",
  admin: "Everything, in every department. Creates accounts, manages departments and sees the audit log.",
};

/** A user ID suggested from the full name, e.g. "Priya Raman" -> "priya.raman". */
const suggestUsername = (name: string) =>
  name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9\s._-]/g, "")
    .trim()
    .replace(/\s+/g, ".")
    .replace(/^[._-]+/, "")
    .slice(0, 64);

type StatusFilter = "true" | "false" | "";
type RoleFilter = "" | Role;

export function UsersPage() {
  const { me, can } = useAuth();
  const isAdmin = can("users:manage");
  const departments = useApi<Department[]>("/departments");
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState({ search: "", department_id: "", role: "" as RoleFilter, is_active: "true" as StatusFilter });
  const [page, setPage] = useState(1);
  const list = useApi<Page<User>>(`/users${query({ ...filters, page, page_size: PAGE_SIZE })}`);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<User | null>(null);
  const [credentials, setCredentials] = useState<UserCredentials | null>(null);
  const action = useAction();
  const deptName = (id: string | null) => (id ? (departments.data?.find((d) => d.id === id)?.code ?? "-") : "All");

  // Search as the admin types, without a request per keystroke.
  useEffect(() => {
    const t = setTimeout(() => {
      if (search !== filters.search) {
        setPage(1);
        setFilters((f) => ({ ...f, search }));
      }
    }, 300);
    return () => clearTimeout(t);
  }, [search, filters.search]);

  const filter = (change: Partial<typeof filters>) => {
    setPage(1);
    setFilters({ ...filters, ...change });
  };

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

  const items = list.data?.items ?? [];
  const filtered = !!(filters.search || filters.department_id || filters.role || filters.is_active !== "true");

  return (
    <>
      <PageHeader
        title="Users and access"
        subtitle="Accounts for every department. Only the admin creates accounts and gives access."
        actions={
          isAdmin && (
            <Button onClick={() => setCreating(true)}>
              <Icon name="plus" />
              New account
            </Button>
          )
        }
      />
      <ErrorBox error={list.error || action.error} />

      <Card flush>
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-5 py-4">
          <div className="relative min-w-56 flex-1">
            <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input className="pl-9" placeholder="Search by user ID, name or email" value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          {me?.role === "admin" && (
            <Select className="w-auto" value={filters.department_id} onChange={(e) => filter({ department_id: e.target.value })}>
              <option value="">All departments</option>
              {departments.data?.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.code}
                </option>
              ))}
            </Select>
          )}
          <Segmented<RoleFilter>
            value={filters.role}
            onChange={(role) => filter({ role })}
            options={[
              { value: "", label: "Everyone" },
              { value: "user", label: "Users" },
              { value: "admin", label: "Admins" },
            ]}
          />
          <Segmented<StatusFilter>
            value={filters.is_active}
            onChange={(is_active) => filter({ is_active })}
            options={[
              { value: "true", label: "Active" },
              { value: "false", label: "Deactivated" },
              { value: "", label: "All" },
            ]}
          />
        </div>

        {list.loading && !list.data ? (
          <Loading />
        ) : items.length === 0 ? (
          <EmptyState
            title={filtered ? "No accounts match" : "No accounts yet"}
            description={filtered ? "Try another search or clear the filters." : "Create the first account to give someone access."}
            action={
              filtered ? (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setSearch("");
                    filter({ search: "", department_id: "", role: "", is_active: "true" });
                  }}
                >
                  Clear filters
                </Button>
              ) : (
                isAdmin && <Button onClick={() => setCreating(true)}>New account</Button>
              )
            }
          />
        ) : (
          <Table headers={["Name", "User ID", "Access", "Department", "Last sign-in", ""]}>
            {items.map((u) => (
              <tr key={u.id} className={u.is_active ? "" : "opacity-60"}>
                <Td>
                  <div className="flex items-center gap-3">
                    <Avatar name={u.full_name} />
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-1.5 font-medium text-slate-900">
                        {u.full_name}
                        {u.id === me?.id && <Badge tone="blue">you</Badge>}
                        {!u.is_active && <Badge>deactivated</Badge>}
                        {u.locked && <Badge tone="red">locked</Badge>}
                        {u.must_change_password && u.is_active && <Badge tone="amber">new password pending</Badge>}
                      </p>
                      {u.email && <p className="truncate text-xs text-slate-500">{u.email}</p>}
                    </div>
                  </div>
                </Td>
                <Td className="font-mono text-xs text-slate-600">{u.username}</Td>
                <Td>
                  <span className="inline-flex items-center gap-1.5 text-slate-700">
                    <Icon name={u.role === "admin" ? "shield" : "user"} className="h-4 w-4 text-slate-400" />
                    {ROLE_NAMES[u.role]}
                  </span>
                </Td>
                <Td className="text-slate-700">{deptName(u.department_id)}</Td>
                <Td className="whitespace-nowrap text-slate-600">{u.last_login_at ? formatDate(u.last_login_at, true) : <span className="text-slate-400">Never</span>}</Td>
                <Td className="whitespace-nowrap text-right">
                  {isAdmin && (
                    <div className="flex items-center justify-end gap-1">
                      <Button variant="ghost" onClick={() => setEditing(u)}>
                        Edit
                      </Button>
                      <Menu
                        items={[
                          { label: "Reset password", onSelect: () => reset(u) },
                          u.locked && { label: "Unlock", onSelect: () => act(() => api.post(`/users/${u.id}/unlock`)) },
                          u.id !== me?.id && { label: u.is_active ? "Deactivate" : "Activate", onSelect: () => toggle(u), danger: u.is_active },
                        ]}
                      />
                    </div>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
        {items.length > 0 && (
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-5 py-3">
            <p className="text-xs text-slate-500">
              {list.data?.total ?? 0} account{list.data?.total === 1 ? "" : "s"}
            </p>
            <Pager page={page} pageSize={PAGE_SIZE} total={list.data?.total ?? 0} onPage={setPage} />
          </div>
        )}
      </Card>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {ROLES.map((r) => (
          <div key={r} className="flex gap-3 rounded-xl border border-slate-200 bg-white p-4">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
              <Icon name={r === "admin" ? "shield" : "user"} />
            </span>
            <div>
              <p className="text-sm font-semibold text-slate-900">{ROLE_NAMES[r]}</p>
              <p className="mt-0.5 text-sm leading-relaxed text-slate-500">{ROLE_ACCESS[r]}</p>
            </div>
          </div>
        ))}
      </div>

      {creating && (
        <AccountForm
          departments={departments.data ?? []}
          onDepartmentsChanged={departments.reload}
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
          onDepartmentsChanged={departments.reload}
          user={editing}
          onCancel={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            list.reload();
          }}
        />
      )}
      {credentials && <CredentialsDialog credentials={credentials} onClose={() => setCredentials(null)} />}
    </>
  );
}

function CredentialsDialog({ credentials, onClose }: { credentials: UserCredentials; onClose: () => void }) {
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
    <Modal
      title={`Sign-in details for ${user.full_name}`}
      onClose={onClose}
      icon={
        <span className="mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
          <Icon name="check" className="h-5 w-5" />
        </span>
      }
      footer={
        <>
          <Button variant="secondary" onClick={copy}>
            <Icon name={copied ? "check" : "copy"} />
            {copied ? "Copied" : "Copy details"}
          </Button>
          <Button onClick={onClose}>Done</Button>
        </>
      }
    >
      <p className="text-sm text-slate-500">Give these to the user. The temporary password is shown only now; they must change it at first sign-in.</p>
      <dl className="mt-4 divide-y divide-slate-200 rounded-xl bg-slate-50 ring-1 ring-slate-200">
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <dt className="text-sm text-slate-500">User ID</dt>
          <dd className="font-mono text-sm text-slate-900">{user.username}</dd>
        </div>
        <div className="flex items-center justify-between gap-3 px-4 py-3">
          <dt className="text-sm text-slate-500">Temporary password</dt>
          <dd className="select-all font-mono text-base font-semibold tracking-wide text-slate-900">{temporary_password}</dd>
        </div>
      </dl>
    </Modal>
  );
}

function AccountForm({
  departments,
  onDepartmentsChanged,
  user,
  onCancel,
  onCreated,
  onSaved,
}: {
  departments: Department[];
  onDepartmentsChanged: () => void;
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
  // Until the admin edits the user ID, it follows the full name.
  const [usernameTouched, setUsernameTouched] = useState(!!user);
  const { busy, error, run } = useAction();
  const editingSelf = user?.id === me?.id;
  const [newDept, setNewDept] = useState<{ code: string; name: string } | null>(null);
  const deptAction = useAction();
  const activeDepartments = departments.filter((d) => d.is_active);

  const addDepartment = () => {
    if (!newDept || !newDept.code.trim() || !newDept.name.trim()) return;
    deptAction.run(async () => {
      const created = await api.post<Department>("/departments", { code: newDept.code.trim(), name: newDept.name.trim() });
      onDepartmentsChanged();
      setForm((f) => ({ ...f, department_id: created.id }));
      setNewDept(null);
    });
  };

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

  const personDone = !!form.full_name.trim() && (!!user || USERNAME.test(form.username));
  const accessDone = form.role === "admin" || !!form.department_id;
  const passwordDone = form.passwordMode === "generate" || form.password.length >= 10;

  return (
    <Drawer
      title={user ? `Edit ${user.full_name}` : "New account"}
      subtitle={user ? "Change their details or what they can do." : "Three short steps. You will get the sign-in details at the end."}
      onClose={onCancel}
      onSubmit={submit}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "Saving..." : user ? "Save changes" : "Create account"}
          </Button>
        </>
      }
    >
      <ErrorBox error={error} />

      <Step plain n={1} title="Who is this?" help="Their name as colleagues know it, and the ID they sign in with." done={personDone}>
        <div className="grid gap-4">
          <Field label="Full name">
            <Input
              autoFocus
              value={form.full_name}
              placeholder="e.g. Priya Raman"
              required
              onChange={(e) => {
                const full_name = e.target.value;
                setForm((f) => ({ ...f, full_name, username: usernameTouched ? f.username : suggestUsername(full_name) }));
              }}
            />
          </Field>
          <Field label="User ID" hint={user ? "User IDs cannot be changed." : "Used to sign in. Letters, digits, dot, dash or underscore; at least 3 characters."}>
            <Input
              className="font-mono"
              value={form.username}
              placeholder="e.g. priya.raman"
              onChange={(e) => {
                setUsernameTouched(true);
                setForm({ ...form, username: e.target.value });
              }}
              disabled={!!user}
              required
              pattern="[A-Za-z0-9][A-Za-z0-9._\-]{2,63}"
              autoCapitalize="none"
              autoComplete="off"
            />
          </Field>
          <Field label="Email" hint="Optional. They can also sign in with it.">
            <Input type="email" value={form.email} placeholder="name@bullmachine.com" onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </Field>
        </div>
      </Step>

      <Step plain n={2} last={!!user} title="What can they do?" help={editingSelf ? "You cannot change your own access." : "Pick the access level, then their department."} done={accessDone}>
        <ChoiceCards<Role>
          value={form.role}
          onChange={(role) => setForm({ ...form, role })}
          disabled={editingSelf}
          options={ROLES.map((r) => ({ value: r, label: ROLE_NAMES[r], description: ROLE_ACCESS[r], icon: r === "admin" ? "shield" : "user" }))}
        />
        {form.role === "admin" ? (
          <p className="mt-3 flex items-center gap-2 text-sm text-slate-500">
            <Icon name="info" className="h-4 w-4 text-slate-400" />
            Admins work across all departments.
          </p>
        ) : (
          <div className="mt-4">
            <Field label="Department" hint={activeDepartments.length ? undefined : "No departments yet. Add one below."}>
              <Select value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })} required disabled={editingSelf}>
                <option value="">Choose a department...</option>
                {activeDepartments.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.code} · {d.name}
                  </option>
                ))}
              </Select>
            </Field>
            {!editingSelf &&
              (newDept ? (
                <div className="mt-3 rounded-xl bg-slate-50 p-3 ring-1 ring-slate-200">
                  <p className="mb-2 text-sm font-medium text-slate-700">New department</p>
                  <ErrorBox error={deptAction.error} />
                  <div className="grid gap-2 sm:grid-cols-[7rem_1fr]">
                    <Input placeholder="Code, e.g. SCM" value={newDept.code} onChange={(e) => setNewDept({ ...newDept, code: e.target.value })} />
                    <Input
                      placeholder="Name, e.g. Supply Chain Management"
                      value={newDept.name}
                      onChange={(e) => setNewDept({ ...newDept, name: e.target.value })}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          e.preventDefault();
                          addDepartment();
                        }
                      }}
                    />
                  </div>
                  <div className="mt-2 flex gap-2">
                    <Button onClick={addDepartment} disabled={deptAction.busy || !newDept.code.trim() || !newDept.name.trim()}>
                      Add department
                    </Button>
                    <Button variant="ghost" onClick={() => setNewDept(null)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <Button variant="ghost" className="mt-2 -ml-2" onClick={() => setNewDept({ code: "", name: "" })}>
                  <Icon name="plus" />
                  New department
                </Button>
              ))}
          </div>
        )}
      </Step>

      {!user && (
        <Step plain last n={3} title="First password" help="Either way, they choose their own password when they first sign in." done={passwordDone}>
          <ChoiceCards<"generate" | "set">
            columns={1}
            value={form.passwordMode}
            onChange={(passwordMode) => setForm({ ...form, passwordMode })}
            options={[
              { value: "generate", label: "Generate a temporary password", description: "Recommended. Shown once after the account is created, ready to copy.", icon: "key" },
              { value: "set", label: "Set one myself", description: "Type a temporary password of at least 10 characters.", icon: "lock" },
            ]}
          />
          {form.passwordMode === "set" && (
            <Field label="Temporary password" className="mt-4">
              <Input type="text" autoComplete="off" minLength={10} placeholder="At least 10 characters" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
            </Field>
          )}
        </Step>
      )}
    </Drawer>
  );
}
