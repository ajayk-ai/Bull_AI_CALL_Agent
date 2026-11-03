import { useState, type FormEvent } from "react";

import { DepartmentPicker, departmentPayload } from "../components/DepartmentPicker";
import { Badge, Button, Card, ErrorBox, Field, Input, Loading, PageHeader, ROLE_NAMES, Select, Table, Td, formatDate } from "../components/ui";
import { api, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction, useApi } from "../lib/hooks";
import type { Department, Page, Role, User } from "../lib/types";

export function UsersPage() {
  const { me, can } = useAuth();
  const list = useApi<Page<User>>(`/users${query({ page_size: 200 })}`);
  const departments = useApi<Department[]>("/departments");
  const [adding, setAdding] = useState(false);
  const action = useAction();
  const deptName = (id: string | null) => departments.data?.find((d) => d.id === id)?.code ?? "-";

  const toggle = (user: User) =>
    action.run(async () => {
      await api.patch(`/users/${user.id}`, { is_active: !user.is_active });
      list.reload();
    });

  const resetPassword = (user: User) => {
    const password = window.prompt(`New password for ${user.email} (at least 10 characters):`);
    if (!password) return;
    action.run(() => api.post(`/users/${user.id}/reset-password`, { new_password: password }));
  };

  return (
    <>
      <PageHeader
        title="Users"
        subtitle={me?.role === "admin" ? "All departments" : "Your department"}
        actions={can("users:manage") && <Button onClick={() => setAdding(true)}>Add user</Button>}
      />
      <ErrorBox error={list.error || action.error} />
      {adding && (
        <AddUser
          onDone={() => {
            setAdding(false);
            list.reload();
          }}
          onCancel={() => setAdding(false)}
        />
      )}
      <Card>
        {list.loading && !list.data ? (
          <Loading />
        ) : (
          <Table headers={["Name", "Email", "Role", "Department", "Last sign-in", ""]} empty={list.data?.items.length === 0}>
            {list.data?.items.map((u) => (
              <tr key={u.id} className={u.is_active ? "" : "text-slate-400"}>
                <Td>
                  {u.full_name} {!u.is_active && <Badge>inactive</Badge>}
                </Td>
                <Td>{u.email}</Td>
                <Td>{ROLE_NAMES[u.role]}</Td>
                <Td>{deptName(u.department_id)}</Td>
                <Td>{formatDate(u.last_login_at, true)}</Td>
                <Td className="whitespace-nowrap text-right">
                  {can("users:manage") && u.id !== me?.id && (
                    <>
                      <Button variant="ghost" onClick={() => resetPassword(u)}>
                        Reset password
                      </Button>
                      <Button variant="ghost" onClick={() => toggle(u)}>
                        {u.is_active ? "Deactivate" : "Activate"}
                      </Button>
                    </>
                  )}
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}

function AddUser({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const { me } = useAuth();
  const roles: Role[] = me?.role === "admin" ? ["operator", "campaign_manager", "hod", "admin"] : ["operator", "campaign_manager"];
  const [form, setForm] = useState({ full_name: "", email: "", password: "", role: "operator" as Role });
  const [department, setDepartment] = useState("");
  const { busy, error, run } = useAction();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(async () => {
      await api.post("/users", { ...form, ...(form.role === "admin" ? {} : departmentPayload(me?.role, department)) });
      onDone();
    });
  };

  return (
    <Card title="Add user" className="mb-4">
      <ErrorBox error={error} />
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
        <Field label="Full name">
          <Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required />
        </Field>
        <Field label="Email">
          <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required />
        </Field>
        <Field label="Initial password" hint="At least 10 characters. Ask the user to change it after first sign-in.">
          <Input type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required minLength={10} />
        </Field>
        <Field label="Role">
          <Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            {roles.map((r) => (
              <option key={r} value={r}>
                {ROLE_NAMES[r]}
              </option>
            ))}
          </Select>
        </Field>
        {form.role !== "admin" && <DepartmentPicker value={department} onChange={setDepartment} />}
        <div className="flex gap-2 md:col-span-2">
          <Button type="submit" disabled={busy}>
            Create
          </Button>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}
