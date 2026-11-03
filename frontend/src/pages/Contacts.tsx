import { useState, type FormEvent } from "react";
import { Link } from "react-router";

import { DepartmentPicker, departmentPayload } from "../components/DepartmentPicker";
import { Badge, Button, Card, ErrorBox, Field, Input, LANGUAGE_NAMES, Loading, PageHeader, Pager, Select, Table, Td } from "../components/ui";
import { api, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction, useApi } from "../lib/hooks";
import type { Contact, Page } from "../lib/types";

const PAGE_SIZE = 50;

export function ContactsPage() {
  const { can } = useAuth();
  const [search, setSearch] = useState("");
  const [applied, setApplied] = useState("");
  const [page, setPage] = useState(1);
  const [adding, setAdding] = useState(false);
  const [revealed, setRevealed] = useState<Record<string, string>>({});
  const list = useApi<Page<Contact>>(`/contacts${query({ search: applied, page, page_size: PAGE_SIZE })}`);
  const action = useAction();

  const reveal = (id: string) =>
    action.run(async () => {
      const result = await api.get<{ phone: string }>(`/contacts/${id}/phone`);
      setRevealed((r) => ({ ...r, [id]: result.phone }));
    });

  const remove = (contact: Contact) => {
    if (!window.confirm(`Delete ${contact.name}? Call history is kept.`)) return;
    action.run(async () => {
      await api.delete(`/contacts/${contact.id}`);
      list.reload();
    });
  };

  return (
    <>
      <PageHeader
        title="Contacts"
        subtitle="Phone numbers are masked. Viewing a full number is recorded in the audit log."
        actions={
          can("contacts:write") && (
            <>
              <Link to="/imports/new">
                <Button variant="secondary">Upload file</Button>
              </Link>
              <Button onClick={() => setAdding(true)}>Add contact</Button>
            </>
          )
        }
      />
      {adding && (
        <AddContact
          onDone={() => {
            setAdding(false);
            list.reload();
          }}
          onCancel={() => setAdding(false)}
        />
      )}
      <ErrorBox error={list.error || action.error} />
      <Card>
        <form
          className="mb-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setPage(1);
            setApplied(search.trim());
          }}
        >
          <Input placeholder="Search name, company or full phone number" value={search} onChange={(e) => setSearch(e.target.value)} />
          <Button type="submit" variant="secondary">
            Search
          </Button>
        </form>
        {list.loading && !list.data ? (
          <Loading />
        ) : (
          <>
            <Table headers={["Name", "Company", "Phone", "Language", "Other fields", ""]} empty={list.data?.items.length === 0}>
              {list.data?.items.map((c) => (
                <tr key={c.id}>
                  <Td>
                    {c.name} {c.do_not_call && <Badge tone="red">Do not call</Badge>}
                  </Td>
                  <Td>{c.company ?? "-"}</Td>
                  <Td className="font-mono text-xs">
                    {revealed[c.id] ?? c.phone_masked}
                    {can("contacts:view_full_number") && !revealed[c.id] && (
                      <button className="ml-2 text-xs text-sky-700 hover:underline" onClick={() => reveal(c.id)}>
                        show
                      </button>
                    )}
                  </Td>
                  <Td>{c.language ? (LANGUAGE_NAMES[c.language] ?? c.language) : "-"}</Td>
                  <Td className="text-xs text-slate-600">
                    {Object.entries(c.custom_fields)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(", ") || "-"}
                  </Td>
                  <Td className="text-right">
                    {can("contacts:delete") && (
                      <Button variant="ghost" onClick={() => remove(c)}>
                        Delete
                      </Button>
                    )}
                  </Td>
                </tr>
              ))}
            </Table>
            <p className="mt-2 text-xs text-slate-500">{list.data?.total ?? 0} contacts</p>
            <Pager page={page} pageSize={PAGE_SIZE} total={list.data?.total ?? 0} onPage={setPage} />
          </>
        )}
      </Card>
    </>
  );
}

function AddContact({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const { me } = useAuth();
  const [form, setForm] = useState({ name: "", phone: "", company: "", language: "" });
  const [department, setDepartment] = useState("");
  const { busy, error, run } = useAction();
  const set = (key: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [key]: e.target.value });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(async () => {
      await api.post("/contacts", {
        name: form.name,
        phone: form.phone,
        company: form.company || null,
        language: form.language || null,
        ...departmentPayload(me?.role, department),
      });
      onDone();
    });
  };

  return (
    <Card title="Add contact" className="mb-4">
      <ErrorBox error={error} />
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
        <DepartmentPicker value={department} onChange={setDepartment} />
        <Field label="Name">
          <Input value={form.name} onChange={set("name")} required />
        </Field>
        <Field label="Phone" hint="10-digit mobile or with +91">
          <Input value={form.phone} onChange={set("phone")} required />
        </Field>
        <Field label="Company">
          <Input value={form.company} onChange={set("company")} />
        </Field>
        <Field label="Language">
          <Select value={form.language} onChange={set("language")}>
            <option value="">Not set</option>
            {Object.entries(LANGUAGE_NAMES).slice(0, 3).map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </Select>
        </Field>
        <div className="flex gap-2 md:col-span-2">
          <Button type="submit" disabled={busy}>
            Save
          </Button>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}
