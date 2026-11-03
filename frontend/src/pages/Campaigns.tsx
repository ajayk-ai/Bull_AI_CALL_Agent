import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { DepartmentPicker, departmentPayload } from "../components/DepartmentPicker";
import { Button, Card, ErrorBox, Field, Input, LANGUAGE_NAMES, Loading, PageHeader, Pager, Select, StatusBadge, Table, Td, formatDate } from "../components/ui";
import { api, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction, useApi } from "../lib/hooks";
import type { Campaign, CampaignStatus, Page, Script } from "../lib/types";

const PAGE_SIZE = 25;
const STATUSES: CampaignStatus[] = ["draft", "pending_approval", "approved", "running", "paused", "completed", "cancelled"];

export function CampaignsPage() {
  const { can } = useAuth();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const list = useApi<Page<Campaign>>(`/campaigns${query({ status, page, page_size: PAGE_SIZE })}`);

  return (
    <>
      <PageHeader
        title="Campaigns"
        subtitle="A campaign calls a list of contacts with one approved script."
        actions={can("campaigns:write") && <Button onClick={() => setCreating(true)}>New campaign</Button>}
      />
      {creating && <NewCampaign onCancel={() => setCreating(false)} />}
      <ErrorBox error={list.error} />
      <Card>
        <div className="mb-3 w-56">
          <Select value={status} onChange={(e) => {
              setPage(1);
              setStatus(e.target.value);
            }}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace("_", " ")}
              </option>
            ))}
          </Select>
        </div>
        {list.loading && !list.data ? (
          <Loading />
        ) : (
          <>
            <Table headers={["Campaign", "Status", "Contacts", "Language", "Dates", "Created"]} empty={list.data?.items.length === 0}>
              {list.data?.items.map((c) => (
                <tr key={c.id}>
                  <Td>
                    <Link to={`/campaigns/${c.id}`} className="font-medium text-sky-800 hover:underline">
                      {c.name}
                    </Link>
                  </Td>
                  <Td>
                    <StatusBadge status={c.status} />
                  </Td>
                  <Td>{c.contact_count}</Td>
                  <Td>{c.language ? (LANGUAGE_NAMES[c.language] ?? c.language) : "Script default"}</Td>
                  <Td className="whitespace-nowrap text-xs">
                    {c.start_date || c.end_date ? `${c.start_date ?? "..."} to ${c.end_date ?? "..."}` : "-"}
                  </Td>
                  <Td>{formatDate(c.created_at)}</Td>
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

/** Published script versions the user can assign, as "Script name · v2". */
export function usePublishedVersions() {
  const scripts = useApi<Script[]>("/scripts");
  const options = (scripts.data ?? []).flatMap((s) =>
    s.versions.filter((v) => v.status === "published").map((v) => ({ id: v.id, label: `${s.name} · v${v.version_no}`, departmentId: s.department_id })),
  );
  return { options, loading: scripts.loading };
}

function NewCampaign({ onCancel }: { onCancel: () => void }) {
  const { me } = useAuth();
  const navigate = useNavigate();
  const versions = usePublishedVersions();
  const [department, setDepartment] = useState("");
  const [form, setForm] = useState({ name: "", script_version_id: "", start_date: "", end_date: "" });
  const { busy, error, run } = useAction();

  const choices = versions.options.filter((v) => me?.role !== "admin" || !department || v.departmentId === department);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(async () => {
      const created = await api.post<Campaign>("/campaigns", {
        name: form.name,
        script_version_id: form.script_version_id || null,
        start_date: form.start_date || null,
        end_date: form.end_date || null,
        ...departmentPayload(me?.role, department),
      });
      navigate(`/campaigns/${created.id}`);
    });
  };

  return (
    <Card title="New campaign" className="mb-4">
      <ErrorBox error={error} />
      <form onSubmit={submit} className="grid gap-3 md:grid-cols-2">
        <DepartmentPicker value={department} onChange={setDepartment} />
        <Field label="Name">
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. SCM delivery confirmation - Nov week 2" required />
        </Field>
        <Field label="Script" hint={choices.length === 0 && !versions.loading ? "No approved script yet. Approve one under Scripts first." : undefined}>
          <Select value={form.script_version_id} onChange={(e) => setForm({ ...form, script_version_id: e.target.value })}>
            <option value="">Choose later</option>
            {choices.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Start date">
          <Input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
        </Field>
        <Field label="End date">
          <Input type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
        </Field>
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
