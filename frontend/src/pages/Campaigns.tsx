import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { DepartmentPicker, departmentPayload } from "../components/DepartmentPicker";
import {
  Button,
  Card,
  Drawer,
  EmptyState,
  ErrorBox,
  Field,
  Guide,
  Icon,
  Input,
  LANGUAGE_NAMES,
  Loading,
  Notice,
  PageHeader,
  Pager,
  Select,
  StatusBadge,
  Step,
  Table,
  Td,
  formatDate,
} from "../components/ui";
import { api, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useExamples } from "../lib/examples";
import { useAction, useApi } from "../lib/hooks";
import type { Campaign, CampaignStatus, Page, Script } from "../lib/types";

const PAGE_SIZE = 25;
const STATUSES: CampaignStatus[] = ["draft", "pending_approval", "approved", "running", "paused", "completed", "cancelled"];

export function CampaignsPage() {
  const { can } = useAuth();
  const ex = useExamples();
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const list = useApi<Page<Campaign>>(`/campaigns${query({ status, page, page_size: PAGE_SIZE })}`);
  const empty = list.data?.total === 0 && !status;

  return (
    <>
      <PageHeader
        title="Campaigns"
        subtitle="A campaign is one round of AI phone calls: a list of people, one script, and the days to call."
        actions={
          can("campaigns:write") && (
            <Button onClick={() => setCreating(true)}>
              <Icon name="plus" />
              New campaign
            </Button>
          )
        }
      />
      <Guide
        id="campaigns"
        title="How a campaign works"
        forceOpen={empty}
        steps={[
          { title: "Create it", text: <>Give it a name and pick a script. Example: "{ex.campaignNames[0]}" with the "{ex.scriptName}" script.</> },
          {
            title: "Add the people",
            text: <>Upload an Excel or CSV with a name and phone number on each row, or fetch it from a connected app. Example: your list of {ex.who}.</>,
          },
          { title: "Approve", text: <>Check the settings and approve. Nothing is called until then.</> },
          { title: "Start calling", text: <>Press Start. The AI calls everyone during calling hours; answers appear under Calls.</> },
        ]}
      />
      {creating && <NewCampaign onCancel={() => setCreating(false)} />}
      <ErrorBox error={list.error} />
      <Card flush>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-4">
          <Select
            className="w-56"
            value={status}
            onChange={(e) => {
              setPage(1);
              setStatus(e.target.value);
            }}
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s.replace("_", " ")}
              </option>
            ))}
          </Select>
          {list.data && <span className="text-xs text-slate-500">{list.data.total} campaigns</span>}
        </div>
        {list.loading && !list.data ? (
          <Loading />
        ) : list.data?.items.length === 0 ? (
          <EmptyState
            title={status ? "No campaigns with this status" : "No campaigns yet"}
            description={status ? "Choose another status above." : "Create your first campaign. It takes about a minute, and nothing is called until you approve and start it."}
            action={!status && can("campaigns:write") && <Button onClick={() => setCreating(true)}>Create your first campaign</Button>}
          />
        ) : (
          <div className="pb-1">
            <Table headers={["Campaign", "Status", "Contacts", "Language", "Dates", "Created"]}>
              {list.data?.items.map((c) => (
                <tr key={c.id}>
                  <Td>
                    <Link to={`/campaigns/${c.id}`} className="font-medium text-slate-900 hover:text-brand-700 hover:underline">
                      {c.name}
                    </Link>
                  </Td>
                  <Td>
                    <StatusBadge status={c.status} />
                  </Td>
                  <Td>{c.contact_count || <span className="text-slate-400">None yet</span>}</Td>
                  <Td>{c.language ? (LANGUAGE_NAMES[c.language] ?? c.language) : "Script default"}</Td>
                  <Td className="whitespace-nowrap text-xs">{c.start_date || c.end_date ? `${c.start_date ?? "..."} to ${c.end_date ?? "..."}` : "-"}</Td>
                  <Td>{formatDate(c.created_at)}</Td>
                </tr>
              ))}
            </Table>
          </div>
        )}
        <div className="px-5 pb-4">
          <Pager page={page} pageSize={PAGE_SIZE} total={list.data?.total ?? 0} onPage={setPage} />
        </div>
      </Card>
    </>
  );
}

/** Published script versions the user can assign, as "Script name · v2". */
export function usePublishedVersions() {
  const scripts = useApi<Script[]>("/scripts");
  const options = (scripts.data ?? []).flatMap((s) =>
    s.versions.filter((v) => v.status === "published").map((v) => ({ id: v.id, label: `${s.name} · v${v.version_no}`, departmentId: s.department_id, description: s.description })),
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
  const ex = useExamples(department || null);

  const choices = versions.options.filter((v) => me?.role !== "admin" || !department || v.departmentId === department);
  const chosen = choices.find((v) => v.id === form.script_version_id);

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
    <Drawer
      title="New campaign"
      subtitle="Three quick steps. Nothing is called until you approve and start the campaign."
      onClose={onCancel}
      onSubmit={submit}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "Creating..." : "Create and add contacts"}
          </Button>
        </>
      }
    >
      <ErrorBox error={error} />

      <Step plain n={1} title="Name it" help="Something your team will recognise in the list. The people you call never see it." done={!!form.name.trim()}>
        <div className="grid gap-4">
          <DepartmentPicker value={department} onChange={setDepartment} />
          <Field label="Campaign name">
            <Input autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder={`e.g. ${ex.campaignNames[0]}`} required />
          </Field>
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
            <span>Examples:</span>
            {ex.campaignNames.map((n) => (
              <button key={n} type="button" onClick={() => setForm({ ...form, name: n })} className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700 hover:bg-slate-200">
                {n}
              </button>
            ))}
          </div>
        </div>
      </Step>

      <Step plain n={2} title="Choose the script" help="The script is what the AI says and asks on each call. Only published scripts appear here." done={!!form.script_version_id}>
        {choices.length === 0 && !versions.loading ? (
          <Notice>
            There is no published script yet. Create one under{" "}
            <Link to="/scripts" className="font-medium underline">
              Scripts
            </Link>{" "}
            first, or create the campaign now and choose the script later.
          </Notice>
        ) : (
          <Field label="Script" hint="Not sure? You can leave it and choose later, before approving.">
            <Select value={form.script_version_id} onChange={(e) => setForm({ ...form, script_version_id: e.target.value })}>
              <option value="">Choose later</option>
              {choices.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </Select>
          </Field>
        )}
        {chosen?.description && (
          <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-600 ring-1 ring-slate-200">
            <span className="font-medium text-slate-800">This script: </span>
            {chosen.description}
          </p>
        )}
      </Step>

      <Step plain last n={3} title="When to call (optional)" help="Leave empty to call as soon as the campaign is started. Calling days and hours can be set on the next page.">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="First day">
            <Input type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
          </Field>
          <Field label="Last day">
            <Input type="date" value={form.end_date} min={form.start_date || undefined} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
          </Field>
        </div>
        <p className="mt-4 flex items-start gap-2 rounded-lg bg-sky-50 px-3 py-2.5 text-sm text-sky-900">
          <Icon name="info" className="mt-0.5 h-4 w-4 text-sky-500" />
          After you create it, you will add the {ex.who} to call: an Excel or CSV file with names and phone numbers, or a list from a connected app.
        </p>
      </Step>
    </Drawer>
  );
}
