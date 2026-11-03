import { useState, type FormEvent } from "react";

import { DepartmentPicker, departmentPayload } from "../components/DepartmentPicker";
import { Badge, Button, Card, ErrorBox, Field, Input, Loading, PageHeader, Pager, Table, Td, formatDate } from "../components/ui";
import { api, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction, useApi } from "../lib/hooks";
import type { DncEntry, Page } from "../lib/types";

const PAGE_SIZE = 50;

export function DncPage() {
  const { me, can } = useAuth();
  const [page, setPage] = useState(1);
  const list = useApi<Page<DncEntry>>(`/dnc${query({ page, page_size: PAGE_SIZE })}`);
  const [form, setForm] = useState({ phone: "", reason: "", global: false });
  const [department, setDepartment] = useState("");
  const action = useAction();

  const add = (event: FormEvent) => {
    event.preventDefault();
    action.run(async () => {
      await api.post("/dnc", {
        phone: form.phone,
        reason: form.reason,
        source: "manual",
        global_scope: form.global,
        ...(form.global ? {} : departmentPayload(me?.role, department)),
      });
      setForm({ phone: "", reason: "", global: false });
      list.reload();
    });
  };

  const remove = (entry: DncEntry) => {
    if (!window.confirm(`Remove ${entry.phone_masked} from the do-not-call list? It may be called again.`)) return;
    action.run(async () => {
      await api.delete(`/dnc/${entry.id}`);
      list.reload();
    });
  };

  return (
    <>
      <PageHeader title="Do not call" subtitle="Numbers here are never dialled. Department entries apply to that department; global entries to all." />
      <ErrorBox error={list.error || action.error} />
      {can("dnc:write") && (
        <Card title="Add a number" className="mb-4">
          <form onSubmit={add} className="grid items-end gap-3 md:grid-cols-4">
            {!form.global && <DepartmentPicker value={department} onChange={setDepartment} />}
            <Field label="Phone">
              <Input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} required />
            </Field>
            <Field label="Reason" className="md:col-span-2">
              <Input value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} placeholder="e.g. Asked not to be called" required />
            </Field>
            {can("dnc:global") && (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={form.global} onChange={(e) => setForm({ ...form, global: e.target.checked })} />
                All departments
              </label>
            )}
            <Button type="submit" disabled={action.busy}>
              Add
            </Button>
          </form>
        </Card>
      )}
      <Card>
        {list.loading && !list.data ? (
          <Loading />
        ) : (
          <>
            <Table headers={["Phone", "Scope", "Reason", "Source", "Added", ""]} empty={list.data?.items.length === 0}>
              {list.data?.items.map((e) => (
                <tr key={e.id}>
                  <Td className="font-mono text-xs">{e.phone_masked}</Td>
                  <Td>{e.department_id ? <Badge>Department</Badge> : <Badge tone="red">Global</Badge>}</Td>
                  <Td>{e.reason}</Td>
                  <Td>{e.source}</Td>
                  <Td>{formatDate(e.created_at)}</Td>
                  <Td className="text-right">
                    {can("dnc:delete") && (e.department_id || can("dnc:global")) && (
                      <Button variant="ghost" onClick={() => remove(e)}>
                        Remove
                      </Button>
                    )}
                  </Td>
                </tr>
              ))}
            </Table>
            <Pager page={page} pageSize={PAGE_SIZE} total={list.data?.total ?? 0} onPage={setPage} />
          </>
        )}
      </Card>
    </>
  );
}
