import { useState, type FormEvent } from "react";

import { Badge, Button, Card, ErrorBox, Field, Input, Loading, PageHeader, Table, Td, formatDate } from "../components/ui";
import { api } from "../lib/api";
import { useAction, useApi } from "../lib/hooks";
import type { Department } from "../lib/types";

export function DepartmentsPage() {
  const list = useApi<(Department & { created_at: string })[]>("/departments");
  const [form, setForm] = useState({ code: "", name: "" });
  const action = useAction();

  const add = (event: FormEvent) => {
    event.preventDefault();
    action.run(async () => {
      await api.post("/departments", form);
      setForm({ code: "", name: "" });
      list.reload();
    });
  };

  const toggle = (d: Department) =>
    action.run(async () => {
      await api.patch(`/departments/${d.id}`, { is_active: !d.is_active });
      list.reload();
    });

  return (
    <>
      <PageHeader title="Departments" />
      <ErrorBox error={list.error || action.error} />
      <Card title="Add department" className="mb-4">
        <form onSubmit={add} className="grid items-end gap-3 md:grid-cols-4">
          <Field label="Code" hint="e.g. SCM, QA">
            <Input value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
          </Field>
          <Field label="Name" className="md:col-span-2">
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
          </Field>
          <Button type="submit" disabled={action.busy}>
            Add
          </Button>
        </form>
      </Card>
      <Card>
        {list.loading && !list.data ? (
          <Loading />
        ) : (
          <Table headers={["Code", "Name", "Status", "Created", ""]} empty={list.data?.length === 0}>
            {list.data?.map((d) => (
              <tr key={d.id}>
                <Td className="font-medium">{d.code}</Td>
                <Td>{d.name}</Td>
                <Td>{d.is_active ? <Badge tone="green">active</Badge> : <Badge>inactive</Badge>}</Td>
                <Td>{formatDate(d.created_at)}</Td>
                <Td className="text-right">
                  <Button variant="ghost" onClick={() => toggle(d)}>
                    {d.is_active ? "Deactivate" : "Activate"}
                  </Button>
                </Td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </>
  );
}
