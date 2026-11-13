import { useEffect, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router";

import { Badge, Button, Card, ErrorBox, Field, Input, LANGUAGE_NAMES, Loading, NextSteps, PageHeader, Pager, Select, StatusBadge, Table, Td, formatDate } from "../components/ui";
import { api, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useExamples } from "../lib/examples";
import { useAction, useApi } from "../lib/hooks";
import type { Approval, Campaign, CampaignContact, Page, Script, ScriptVersion } from "../lib/types";
import { usePublishedVersions } from "./Campaigns";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const PAGE_SIZE = 50;

export function CampaignDetailPage() {
  const { id } = useParams();
  const { me, can } = useAuth();
  const selfApprove = me?.second_approver_required === false && can("campaigns:approve");
  const campaign = useApi<Campaign>(`/campaigns/${id}`);
  const [page, setPage] = useState(1);
  const contacts = useApi<Page<CampaignContact>>(`/campaigns/${id}/contacts${query({ page, page_size: PAGE_SIZE })}`);
  const approvals = useApi<Approval[]>(`/campaigns/${id}/approvals`);
  const version = useApi<ScriptVersion>(campaign.data?.script_version_id ? `/script-versions/${campaign.data.script_version_id}` : null);
  const script = useApi<Script>(version.data ? `/scripts/${version.data.script_id}` : null);
  const [comments, setComments] = useState("");
  const action = useAction();
  const ex = useExamples(campaign.data?.department_id);

  if (!campaign.data) return campaign.error ? <ErrorBox error={campaign.error} /> : <Loading />;
  const c = campaign.data;
  const isDraft = c.status === "draft";
  const reloadAll = () => {
    campaign.reload();
    contacts.reload();
    approvals.reload();
  };

  const run = (name: "start" | "pause" | "resume") =>
    action.run(async () => {
      await api.post(`/campaigns/${c.id}/${name}`);
      reloadAll();
    });

  const approveNow = () =>
    action.run(async () => {
      await api.post(`/campaigns/${c.id}/submit`, {});
      await api.post(`/campaigns/${c.id}/approve`, { comments: null });
      reloadAll();
    });

  const step = (name: "submit" | "approve" | "reject" | "cancel") => {
    if (name === "cancel" && !window.confirm("Cancel this campaign? This cannot be undone.")) return;
    action.run(async () => {
      await api.post(`/campaigns/${c.id}/${name}`, name === "submit" ? {} : { comments: comments || null });
      setComments("");
      reloadAll();
    });
  };

  const removeContact = (contactId: string) =>
    action.run(async () => {
      await api.delete(`/campaigns/${c.id}/contacts/${contactId}`);
      reloadAll();
    });

  const contextKeys = version.data?.config.context_fields.map((f) => f.key) ?? [];

  return (
    <>
      <PageHeader
        title={c.name}
        subtitle={c.description ?? undefined}
        actions={
          <>
            <StatusBadge status={c.status} />
            {isDraft && can("imports:write") && (
              <Link to={`/imports/new?campaign=${c.id}`}>
                <Button variant="secondary">Upload contacts</Button>
              </Link>
            )}
          </>
        }
      />
      <ErrorBox error={action.error} />
      {!["completed", "cancelled"].includes(c.status) && (
        <NextSteps
          title="Getting this campaign ready"
          steps={[
            {
              title: "Choose a script",
              done: !!c.script_version_id,
              text: `Pick what the AI should say and ask, in Settings below. Example: "${ex.scriptName}".`,
            },
            {
              title: "Add contacts",
              done: c.contact_count > 0,
              text: `Add the ${ex.who} to call: upload an Excel or CSV with a name and phone number on each row, or fetch the list from a connected app. The upload page shows an example and a sample file.`,
              action: isDraft && can("imports:write") && (
                <Link to={`/imports/new?campaign=${c.id}`}>
                  <Button>Upload contacts</Button>
                </Link>
              ),
            },
            {
              title: "Approve",
              done: !["draft", "pending_approval"].includes(c.status),
              text:
                c.status === "pending_approval"
                  ? "Waiting for a colleague or an admin to approve it, in the Approval box on the right."
                  : "Check the calling days, hours and contacts, then approve in the Approval box on the right. Nothing is called before this.",
            },
            {
              title: "Start calling",
              done: ["running", "paused"].includes(c.status),
              text: "Press Start in the Calling box above. The AI calls everyone during calling hours; answers appear under Calls.",
            },
          ]}
        />
      )}
      {["approved", "running", "paused", "completed"].includes(c.status) && (
        <Calling campaign={c} canRun={can("campaigns:write")} busy={action.busy} onRun={run} onRefresh={reloadAll} />
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="min-w-0 space-y-4 lg:col-span-2">
          {isDraft && can("campaigns:write") ? <Settings campaign={c} onSaved={reloadAll} /> : <Summary campaign={c} version={version.data} scriptName={script.data?.name} />}

          <Card title={`Contacts (${contacts.data?.total ?? 0})`}>
            {contacts.loading && !contacts.data ? (
              <Loading />
            ) : (
              <>
                <Table headers={["Contact", "Phone", "Items", "Status", "Attempts", ""]} empty={contacts.data?.items.length === 0}>
                  {contacts.data?.items.map((m) => (
                    <tr key={m.id}>
                      <Td>
                        {m.contact_name} {m.do_not_call && <Badge tone="red">Do not call</Badge>}
                        {m.company && m.company !== m.contact_name && <p className="text-xs text-slate-500">{m.company}</p>}
                      </Td>
                      <Td className="font-mono text-xs">{m.phone_masked}</Td>
                      <Td className="text-xs">
                        {(m.context.items ?? []).map((item, i) => (
                          <p key={i}>{(contextKeys.length ? contextKeys : Object.keys(item)).map((k) => item[k] ?? "-").join(" · ")}</p>
                        ))}
                        {!m.context.items?.length && <span className="text-amber-700">No campaign data</span>}
                      </Td>
                      <Td>
                        <StatusBadge status={m.status} />
                        {m.outcome && <p className="text-xs text-slate-500">{m.outcome}</p>}
                      </Td>
                      <Td className="text-xs">{m.attempts || "-"}</Td>
                      <Td className="text-right">
                        {isDraft && can("campaigns:write") && (
                          <Button variant="ghost" onClick={() => removeContact(m.contact_id)}>
                            Remove
                          </Button>
                        )}
                      </Td>
                    </tr>
                  ))}
                </Table>
                <Pager page={page} pageSize={PAGE_SIZE} total={contacts.data?.total ?? 0} onPage={setPage} />
              </>
            )}
          </Card>
        </div>

        <div className="min-w-0 space-y-4">
          <Card title="Approval">
            <div className="space-y-3">
              {isDraft && can("campaigns:write") && (
                <>
                  <p className="text-sm text-slate-600">
                    {selfApprove ? "Checks the script, the contacts and their campaign data, then marks the campaign ready to start." : "Submitting checks the script, the contacts and their campaign data."}
                  </p>
                  {selfApprove ? (
                    <Button onClick={approveNow} disabled={action.busy}>
                      Approve campaign
                    </Button>
                  ) : (
                    <Button onClick={() => step("submit")} disabled={action.busy}>
                      Submit for approval
                    </Button>
                  )}
                </>
              )}
              {c.status === "pending_approval" && can("campaigns:approve") && (
                <>
                  <Field label="Comments">
                    <Input value={comments} onChange={(e) => setComments(e.target.value)} />
                  </Field>
                  <div className="flex gap-2">
                    <Button onClick={() => step("approve")} disabled={action.busy}>
                      Approve
                    </Button>
                    <Button variant="danger" onClick={() => step("reject")} disabled={action.busy}>
                      Send back
                    </Button>
                  </div>
                </>
              )}
              <ul className="space-y-2 text-sm">
                {approvals.data?.map((a) => (
                  <li key={a.id} className="border-t border-slate-100 pt-2">
                    <StatusBadge status={a.decision} /> <span className="text-xs text-slate-500">requested {formatDate(a.requested_at, true)}</span>
                    {a.decided_at && <p className="text-xs text-slate-500">decided {formatDate(a.decided_at, true)}</p>}
                    {a.comments && <p className="text-slate-700">"{a.comments}"</p>}
                  </li>
                ))}
              </ul>
              {["draft", "pending_approval", "approved", "running", "paused"].includes(c.status) && can("campaigns:write") && (
                <Button variant="ghost" onClick={() => step("cancel")} disabled={action.busy}>
                  Cancel campaign
                </Button>
              )}
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}

function Summary({ campaign: c, version, scriptName }: { campaign: Campaign; version: ScriptVersion | null; scriptName?: string }) {
  const w = c.calling_window;
  return (
    <Card title="Settings">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm md:grid-cols-3">
        <Item label="Script">{version ? `${scriptName ?? "Script"} · v${version.version_no}` : "-"}</Item>
        <Item label="Language">{c.language ? (LANGUAGE_NAMES[c.language] ?? c.language) : "Script default"}</Item>
        <Item label="Dates">{c.start_date || c.end_date ? `${c.start_date ?? "..."} to ${c.end_date ?? "..."}` : "-"}</Item>
        <Item label="Calling hours">{`${w.days.map((d) => DAYS[d]).join(", ")} · ${w.start.slice(0, 5)}-${w.end.slice(0, 5)}`}</Item>
        <Item label="Simultaneous calls">{c.max_concurrency}</Item>
        <Item label="Attempts">{`${c.max_attempts}, ${c.retry_interval_minutes} min apart`}</Item>
      </dl>
    </Card>
  );
}

function Item({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd>{children}</dd>
    </div>
  );
}

function Settings({ campaign: c, onSaved }: { campaign: Campaign; onSaved: () => void }) {
  const versions = usePublishedVersions();
  const [form, setForm] = useState(() => toForm(c));
  const { busy, error, run } = useAction();
  useEffect(() => setForm(toForm(c)), [c]);

  const save = () =>
    run(async () => {
      await api.patch(`/campaigns/${c.id}`, {
        name: form.name,
        script_version_id: form.script_version_id || null,
        language: form.language || null,
        start_date: form.start_date || null,
        end_date: form.end_date || null,
        calling_window: { ...c.calling_window, days: form.days, start: form.start, end: form.end },
        max_concurrency: Number(form.max_concurrency),
        max_attempts: Number(form.max_attempts),
        retry_interval_minutes: Number(form.retry_interval_minutes),
      });
      onSaved();
    });

  const options = versions.options.filter((v) => v.departmentId === c.department_id);
  const currentMissing = c.script_version_id && !options.some((o) => o.id === c.script_version_id);

  return (
    <Card title="Settings" actions={<Button onClick={save} disabled={busy}>Save</Button>}>
      <ErrorBox error={error} />
      <div className="grid gap-3 md:grid-cols-3">
        <Field label="Name" className="md:col-span-2">
          <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="Script">
          <Select value={form.script_version_id} onChange={(e) => setForm({ ...form, script_version_id: e.target.value })}>
            <option value="">None</option>
            {currentMissing && <option value={c.script_version_id!}>Current (no longer published)</option>}
            {options.map((v) => (
              <option key={v.id} value={v.id}>
                {v.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Language">
          <Select value={form.language} onChange={(e) => setForm({ ...form, language: e.target.value })}>
            <option value="">Script default</option>
            {["ta-IN", "en-IN", "hi-IN"].map((code) => (
              <option key={code} value={code}>
                {LANGUAGE_NAMES[code]}
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
        <Field label="Calling days" className="md:col-span-3" hint="Default hours are a proposal awaiting confirmation by the compliance team.">
          <div className="flex flex-wrap gap-3 py-1">
            {DAYS.map((name, d) => (
              <label key={d} className="flex items-center gap-1 text-sm">
                <input
                  type="checkbox"
                  checked={form.days.includes(d)}
                  onChange={(e) => setForm({ ...form, days: e.target.checked ? [...form.days, d].sort() : form.days.filter((x) => x !== d) })}
                />
                {name}
              </label>
            ))}
          </div>
        </Field>
        <Field label="From">
          <Input type="time" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} />
        </Field>
        <Field label="Until">
          <Input type="time" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} />
        </Field>
        <Field label="Simultaneous calls" hint="Platform limit: 5">
          <Input type="number" min={1} max={5} value={form.max_concurrency} onChange={(e) => setForm({ ...form, max_concurrency: e.target.value })} />
        </Field>
        <Field label="Attempts per contact">
          <Input type="number" min={1} max={10} value={form.max_attempts} onChange={(e) => setForm({ ...form, max_attempts: e.target.value })} />
        </Field>
        <Field label="Minutes between attempts">
          <Input type="number" min={5} max={1440} value={form.retry_interval_minutes} onChange={(e) => setForm({ ...form, retry_interval_minutes: e.target.value })} />
        </Field>
      </div>
    </Card>
  );
}

function toForm(c: Campaign) {
  return {
    name: c.name,
    script_version_id: c.script_version_id ?? "",
    language: c.language ?? "",
    start_date: c.start_date ?? "",
    end_date: c.end_date ?? "",
    days: c.calling_window.days,
    start: c.calling_window.start.slice(0, 5),
    end: c.calling_window.end.slice(0, 5),
    max_concurrency: String(c.max_concurrency),
    max_attempts: String(c.max_attempts),
    retry_interval_minutes: String(c.retry_interval_minutes),
  };
}

const PROGRESS_ORDER = ["pending", "in_progress", "retry_scheduled", "completed", "failed", "skipped"];

/** Start / pause / resume, and where the campaign has got to. The server's dialer places the calls. */
function Calling({
  campaign: c,
  canRun,
  busy,
  onRun,
  onRefresh,
}: {
  campaign: Campaign;
  canRun: boolean;
  busy: boolean;
  onRun: (name: "start" | "pause" | "resume") => void;
  onRefresh: () => void;
}) {
  // While calling, refresh every 5 seconds so progress and statuses stay current.
  useEffect(() => {
    if (c.status !== "running") return;
    const timer = window.setInterval(onRefresh, 5000);
    return () => window.clearInterval(timer);
  }, [c.status, onRefresh]);

  const done = (c.progress.completed ?? 0) + (c.progress.failed ?? 0) + (c.progress.skipped ?? 0);
  return (
    <Card title="Calling" className="mb-4">
      <div className="flex flex-wrap items-center gap-3">
        {canRun && c.status === "approved" && (
          <Button onClick={() => onRun("start")} disabled={busy}>
            Start calling
          </Button>
        )}
        {canRun && c.status === "running" && (
          <Button variant="secondary" onClick={() => onRun("pause")} disabled={busy}>
            Pause
          </Button>
        )}
        {canRun && c.status === "paused" && (
          <Button onClick={() => onRun("resume")} disabled={busy}>
            Resume
          </Button>
        )}
        <p className="text-sm text-slate-600">
          {done} of {c.contact_count} done ·{" "}
          {PROGRESS_ORDER.filter((s) => c.progress[s])
            .map((s) => `${c.progress[s]} ${s.replace("_", " ")}`)
            .join(" · ") || "no contacts"}
        </p>
      </div>
      <p className="mt-2 text-xs text-slate-500">
        Calls go out one at a time, inside the calling hours. Unanswered calls are retried {c.retry_interval_minutes} minutes later, up to{" "}
        {c.max_attempts} attempts. Pausing lets the call in progress finish. Results are on the <Link className="underline" to={`/calls?campaign_id=${c.id}`}>Calls</Link> page.
      </p>
    </Card>
  );
}
