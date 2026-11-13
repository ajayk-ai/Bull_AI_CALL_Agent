import { useState, type FormEvent } from "react";

import { DepartmentPicker } from "../components/DepartmentPicker";
import {
  Badge,
  Button,
  ChoiceCards,
  Drawer,
  ErrorBox,
  Field,
  Guide,
  Icon,
  Input,
  Loading,
  Menu,
  Notice,
  PageHeader,
  Step,
  TextArea,
  formatDate,
  type IconName,
} from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useExamples, type DeptExample } from "../lib/examples";
import { ApiKeysSection } from "./ApiKeys";
import { useAction, useApi } from "../lib/hooks";
import type { Campaign, Connection, ConnectionAuth, ConnectionKind, ConnectionTest, Page } from "../lib/types";

const KINDS: Record<ConnectionKind, { title: string; short: string; icon: IconName; method: string }> = {
  fetch_contacts: { title: "Bring people in", short: "Fetches the list of people to call from your app", icon: "download", method: "GET" },
  send_results: { title: "Send results out", short: "Sends each call's answers to your app", icon: "upload", method: "POST" },
};

const AUTH: Record<ConnectionAuth, string> = {
  none: "No sign-in",
  bearer: "Token (Bearer)",
  api_key: "API key in a header",
  basic: "User name and password",
};

const host = (url: string) => {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
};

const lines = (map: Record<string, string>, sep: string) =>
  Object.entries(map)
    .map(([k, v]) => `${k}${sep}${v}`)
    .join("\n");

const parseLines = (text: string, sep: string): Record<string, string> =>
  Object.fromEntries(
    text
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean)
      .map((l) => {
        const i = l.indexOf(sep);
        return i < 0 ? [l, ""] : [l.slice(0, i).trim(), l.slice(i + sep.length).trim()];
      }),
  );

export function IntegrationsPage() {
  const { can } = useAuth();
  const ex = useExamples();
  const list = useApi<Connection[]>("/integrations");
  const [editing, setEditing] = useState<Connection | "new" | null>(null);
  const [tests, setTests] = useState<Record<string, ConnectionTest | "running">>({});
  const action = useAction();

  const runTest = (c: Pick<Connection, "id">) => {
    setTests((t) => ({ ...t, [c.id]: "running" }));
    action.run(async () => {
      try {
        const result = await api.post<ConnectionTest>(`/integrations/${c.id}/test`);
        setTests((t) => ({ ...t, [c.id]: result }));
      } finally {
        list.reload();
      }
    });
  };

  const remove = (c: Connection) => {
    if (!window.confirm(`Delete the connection "${c.name}"? Calls already made are not affected.`)) return;
    action.run(async () => {
      await api.delete(`/integrations/${c.id}`);
      list.reload();
    });
  };

  const toggle = (c: Connection) =>
    action.run(async () => {
      await api.put(`/integrations/${c.id}`, { ...toBody(c), is_active: !c.is_active });
      list.reload();
    });

  const items = list.data ?? [];

  return (
    <>
      <PageHeader
        title="Connected apps"
        subtitle={`Link your department's own ${ex.system}. Bring the people to call in automatically, and send every call's answers straight back.`}
        actions={
          <Button onClick={() => setEditing("new")}>
            <Icon name="plus" />
            Connect an app
          </Button>
        }
      />
      <Guide
        id="integrations"
        title="How connected apps work"
        forceOpen={list.data?.length === 0}
        steps={[
          {
            title: "Bring people in",
            text: (
              <>
                Instead of uploading Excel, fetch the list from your app. Example: the {ex.who} in your {ex.system}, from an address like{" "}
                <span className="break-all font-mono text-xs">{host(ex.fetchUrl)}</span>.
              </>
            ),
          },
          { title: "Check and import", text: <>The list goes through the same column matching and checks as a file, so nothing reaches a campaign unchecked.</> },
          { title: "Calls happen", text: <>The campaign calls everyone as usual, during calling hours.</> },
          {
            title: "Send results out",
            text: <>After each call, its answers are sent to your app automatically, e.g. to update the record in your {ex.system}.</>,
          },
        ]}
      />
      <ErrorBox error={list.error || action.error} />

      {list.loading && !list.data ? (
        <Loading />
      ) : (
        <div className="space-y-8">
          {(Object.keys(KINDS) as ConnectionKind[]).map((kind) => {
            const ofKind = items.filter((c) => c.kind === kind);
            return (
              <section key={kind}>
                <div className="mb-3 flex items-center gap-2">
                  <Icon name={KINDS[kind].icon} className="h-4 w-4 text-slate-400" />
                  <h2 className="text-[15px] font-semibold text-slate-900">{KINDS[kind].title}</h2>
                  <span className="text-sm text-slate-500">· {KINDS[kind].short}</span>
                </div>
                {ofKind.length === 0 ? (
                  <button
                    type="button"
                    onClick={() => setEditing("new")}
                    className="flex w-full items-center gap-3 rounded-xl border-2 border-dashed border-slate-200 px-5 py-5 text-left text-sm text-slate-500 hover:border-slate-300 hover:bg-white"
                  >
                    <Icon name="plus" className="h-5 w-5 text-slate-400" />
                    {kind === "fetch_contacts"
                      ? `Nothing connected yet. Example: fetch ${ex.who} from your ${ex.system}.`
                      : `Nothing connected yet. Example: send each call's answers back to your ${ex.system}.`}
                  </button>
                ) : (
                  <div className="grid gap-4 lg:grid-cols-2">
                    {ofKind.map((c) => (
                      <ConnectionCard key={c.id} connection={c} test={tests[c.id]} onTest={() => runTest(c)} onEdit={() => setEditing(c)} onToggle={() => toggle(c)} onDelete={() => remove(c)} />
                    ))}
                  </div>
                )}
              </section>
            );
          })}

          {can("api_keys:manage") && <ApiKeysSection />}
        </div>
      )}

      {editing && (
        <ConnectionForm
          connection={editing === "new" ? null : editing}
          ex={ex}
          onCancel={() => setEditing(null)}
          onSaved={(saved, isNew) => {
            setEditing(null);
            list.reload();
            if (isNew) runTest(saved);
          }}
        />
      )}
    </>
  );
}

function ConnectionCard({
  connection: c,
  test,
  onTest,
  onEdit,
  onToggle,
  onDelete,
}: {
  connection: Connection;
  test: ConnectionTest | "running" | undefined;
  onTest: () => void;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
}) {
  const last = c.last_result;
  return (
    <article className={`flex flex-col rounded-xl border border-slate-200 bg-white shadow-sm ${c.is_active ? "" : "opacity-70"}`}>
      <div className="flex items-start gap-3 px-5 pt-4">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
          <Icon name={KINDS[c.kind].icon} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-2 font-semibold text-slate-900">
            {c.name}
            {!c.is_active && <Badge>off</Badge>}
          </p>
          <p className="mt-0.5 truncate font-mono text-xs text-slate-500" title={c.url}>
            {KINDS[c.kind].method} {c.url}
          </p>
        </div>
        <Menu
          items={[
            { label: c.is_active ? "Switch off" : "Switch on", onSelect: onToggle },
            { label: "Delete", onSelect: onDelete, danger: true },
          ]}
        />
      </div>
      <div className="px-5 py-3">
        {last ? (
          <p className={`flex items-start gap-1.5 text-sm ${last.ok ? "text-emerald-700" : "text-red-700"}`}>
            <Icon name={last.ok ? "check" : "info"} className="mt-0.5 h-4 w-4" />
            <span className="min-w-0">
              {last.message}
              <span className="ml-1 text-xs text-slate-400">· {formatDate(last.at, true)}</span>
            </span>
          </p>
        ) : (
          <p className="text-sm text-slate-500">Not tested yet.</p>
        )}
        {test && test !== "running" && test.ok && test.preview.length > 0 && <TestPreview test={test} />}
      </div>
      <div className="mt-auto flex items-center gap-2 border-t border-slate-100 px-5 py-3">
        <Button variant="secondary" onClick={onTest} disabled={test === "running"}>
          {test === "running" ? "Testing..." : "Test"}
        </Button>
        <Button variant="ghost" onClick={onEdit}>
          Edit
        </Button>
        <span className="ml-auto text-xs text-slate-400">{AUTH[c.auth_type]}</span>
      </div>
    </article>
  );
}

function TestPreview({ test }: { test: ConnectionTest }) {
  const columns = test.columns.slice(0, 6);
  return (
    <div className="mt-3 overflow-x-auto rounded-lg ring-1 ring-slate-200">
      <table className="w-full text-left text-xs">
        <thead className="bg-slate-50 text-slate-500">
          <tr>
            {columns.map((col) => (
              <th key={col} className="whitespace-nowrap px-2.5 py-1.5 font-medium">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {test.preview.map((row, i) => (
            <tr key={i} className="border-t border-slate-100">
              {columns.map((col) => (
                <td key={col} className="whitespace-nowrap px-2.5 py-1.5 text-slate-700">
                  {row[col] || "-"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {test.columns.length > columns.length && <p className="bg-slate-50 px-2.5 py-1 text-[11px] text-slate-500">+ {test.columns.length - columns.length} more fields</p>}
    </div>
  );
}

function toBody(c: Connection) {
  return {
    name: c.name,
    kind: c.kind,
    url: c.url,
    is_active: c.is_active,
    auth_type: c.auth_type,
    api_key_header: c.api_key_header,
    username: c.username,
    headers: c.headers,
    records_path: c.records_path,
    query: c.query,
    campaign_ids: c.campaign_ids,
  };
}

const randomSecret = () => Array.from(crypto.getRandomValues(new Uint8Array(24)), (b) => b.toString(16).padStart(2, "0")).join("");

function ConnectionForm({ connection, ex, onCancel, onSaved }: { connection: Connection | null; ex: DeptExample; onCancel: () => void; onSaved: (c: Connection, isNew: boolean) => void }) {
  const { me } = useAuth();
  const [department, setDepartment] = useState("");
  const [form, setForm] = useState({
    kind: (connection?.kind ?? "fetch_contacts") as ConnectionKind,
    name: connection?.name ?? "",
    url: connection?.url ?? "",
    auth_type: (connection?.auth_type ?? "bearer") as ConnectionAuth,
    api_key_header: connection?.api_key_header ?? "X-API-Key",
    username: connection?.username ?? "",
    secret: "",
    clearSecret: false,
    signing_secret: "",
    records_path: connection?.records_path ?? "",
    query: lines(connection?.query ?? {}, "="),
    headers: lines(connection?.headers ?? {}, ": "),
    campaign_ids: connection?.campaign_ids ?? [],
  });
  const campaigns = useApi<Page<Campaign>>(form.kind === "send_results" ? "/campaigns?page_size=200" : null);
  const sample = useApi<Record<string, unknown>>(form.kind === "send_results" ? "/integrations/sample-result" : null);
  const { busy, error, run } = useAction();
  const set = (change: Partial<typeof form>) => setForm({ ...form, ...change });
  const fetchKind = form.kind === "fetch_contacts";
  const deptId = connection?.department_id ?? (me?.role === "admin" ? department : me?.department_id);
  const deptCampaigns = (campaigns.data?.items ?? []).filter((c) => !deptId || c.department_id === deptId);

  const nameExamples = fetchKind ? [`${ex.system.split(" (")[0]} - ${ex.who} to call`, `${ex.scriptName} list`] : [`${ex.system.split(" (")[0]} - call results`, `${ex.scriptName} answers`];

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const body = {
      name: form.name,
      kind: form.kind,
      url: form.url.trim(),
      is_active: connection?.is_active ?? true,
      auth_type: form.auth_type,
      api_key_header: form.api_key_header || "X-API-Key",
      username: form.username || null,
      // Empty keeps the stored secret when editing; "Remove" clears it.
      secret: form.clearSecret ? "" : form.secret || (connection ? null : ""),
      signing_secret: form.signing_secret || (connection ? null : ""),
      headers: parseLines(form.headers, ":"),
      records_path: form.records_path.trim(),
      query: parseLines(form.query, "="),
      campaign_ids: form.campaign_ids,
      ...(connection ? {} : me?.role === "admin" && department ? { department_id: department } : {}),
    };
    run(async () => {
      const saved = connection ? await api.put<Connection>(`/integrations/${connection.id}`, body) : await api.post<Connection>("/integrations", body);
      onSaved(saved, !connection);
    });
  };

  const needsSecret = form.auth_type !== "none";

  return (
    <Drawer
      title={connection ? `Edit ${connection.name}` : "Connect an app"}
      subtitle="Four short steps. Your IT team or the app's admin can give you the address and the key."
      onClose={onCancel}
      onSubmit={submit}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "Saving..." : connection ? "Save changes" : "Save and test"}
          </Button>
        </>
      }
    >
      <ErrorBox error={error} />

      <Step plain n={1} title="What should it do?" done>
        <ChoiceCards<ConnectionKind>
          columns={1}
          value={form.kind}
          disabled={!!connection}
          onChange={(kind) => set({ kind })}
          options={[
            { value: "fetch_contacts", label: "Bring people in", description: `Fetch the ${ex.who} to call from your app, instead of uploading Excel.`, icon: "download" },
            { value: "send_results", label: "Send results out", description: `After each call, send the answers to your app, e.g. to update your ${ex.system}.`, icon: "upload" },
          ]}
        />
      </Step>

      <Step plain n={2} title="Where is it?" help="A name for your team, and the web address (API) of your app." done={!!form.name.trim() && /^https?:\/\/.+/.test(form.url.trim())}>
        <div className="grid gap-4">
          {!connection && <DepartmentPicker value={department} onChange={setDepartment} />}
          <Field label="Name">
            <Input value={form.name} onChange={(e) => set({ name: e.target.value })} placeholder={`e.g. ${nameExamples[0]}`} required />
          </Field>
          <div className="-mt-2 flex flex-wrap gap-1.5 text-xs">
            {nameExamples.map((n) => (
              <button key={n} type="button" onClick={() => set({ name: n })} className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700 hover:bg-slate-200">
                {n}
              </button>
            ))}
          </div>
          <Field label="Address" hint={fetchKind ? "We read this address (GET). It should answer with JSON." : "We send each result to this address (POST, JSON)."}>
            <Input type="url" className="font-mono" value={form.url} onChange={(e) => set({ url: e.target.value })} placeholder={fetchKind ? ex.fetchUrl : ex.resultsUrl} required />
          </Field>
        </div>
      </Step>

      <Step plain n={3} title="How does it sign in?" help="Ask the app's admin which one it uses. Keys are stored encrypted and never shown again." done={!needsSecret || !!form.secret || (!!connection?.has_secret && !form.clearSecret)}>
        <div className="grid gap-4">
          <ChoiceCards<ConnectionAuth>
            value={form.auth_type}
            onChange={(auth_type) => set({ auth_type })}
            options={(Object.keys(AUTH) as ConnectionAuth[]).map((a) => ({ value: a, label: AUTH[a] }))}
          />
          {form.auth_type === "api_key" && (
            <Field label="Header name" hint="e.g. X-API-Key or apikey">
              <Input className="font-mono" value={form.api_key_header} onChange={(e) => set({ api_key_header: e.target.value })} />
            </Field>
          )}
          {form.auth_type === "basic" && (
            <Field label="User name">
              <Input value={form.username} onChange={(e) => set({ username: e.target.value })} autoComplete="off" />
            </Field>
          )}
          {needsSecret && (
            <Field
              label={form.auth_type === "basic" ? "Password" : form.auth_type === "api_key" ? "API key" : "Token"}
              hint={connection?.has_secret && !form.clearSecret ? "A key is saved. Leave empty to keep it." : undefined}
            >
              <Input type="password" autoComplete="new-password" value={form.secret} onChange={(e) => set({ secret: e.target.value, clearSecret: false })} placeholder={connection?.has_secret ? "••••••••" : ""} />
            </Field>
          )}
          {connection?.has_secret && needsSecret && !form.clearSecret && (
            <button type="button" className="-mt-2 self-start text-xs text-slate-500 underline hover:text-slate-800" onClick={() => set({ clearSecret: true, secret: "" })}>
              Remove the saved key
            </button>
          )}
        </div>
      </Step>

      <Step plain last n={4} title={fetchKind ? "Where is the list?" : "Which calls?"} done>
        {fetchKind ? (
          <div className="grid gap-4">
            <Field label="Where the list is in the reply" hint="Leave empty if the reply is the list itself, or has it under data, items, results or records.">
              <Input className="font-mono" value={form.records_path} onChange={(e) => set({ records_path: e.target.value })} placeholder={`e.g. ${ex.fetchPath}`} />
            </Field>
            <pre className="overflow-x-auto rounded-lg bg-slate-900 px-4 py-3 text-xs leading-relaxed text-slate-200">
              {`// For a reply like this, write: ${ex.fetchPath}
${exampleReply(ex)}`}
            </pre>
            <p className="text-sm text-slate-600">
              Nested fields become columns like <span className="font-mono text-xs">customer.name</span>; you will match them to name and phone in the next screen, just like Excel columns.
            </p>
            <Field label="Filters added to the address (optional)" hint="One per line, e.g. month=2026-11">
              <TextArea rows={2} className="font-mono text-xs" value={form.query} onChange={(e) => set({ query: e.target.value })} />
            </Field>
          </div>
        ) : (
          <div className="grid gap-4">
            <Field label="Send results of" hint="Leave all unticked to send every campaign's calls.">
              <div className="max-h-48 space-y-1.5 overflow-y-auto rounded-lg p-3 ring-1 ring-slate-200">
                {deptCampaigns.length === 0 && <p className="text-sm text-slate-500">All campaigns (none created yet).</p>}
                {deptCampaigns.map((c) => (
                  <label key={c.id} className="flex items-center gap-2 text-sm">
                    <input
                      type="checkbox"
                      checked={form.campaign_ids.includes(c.id)}
                      onChange={(e) => set({ campaign_ids: e.target.checked ? [...form.campaign_ids, c.id] : form.campaign_ids.filter((id) => id !== c.id) })}
                    />
                    {c.name}
                  </label>
                ))}
              </div>
            </Field>
            <Field
              label="Signing secret (recommended)"
              hint={
                connection?.has_signing_secret
                  ? "A secret is saved. Leave empty to keep it."
                  : "Your app can use it to check that results really come from Bull AI Calling (header X-BullCall-Signature)."
              }
            >
              <div className="flex gap-2">
                <Input className="font-mono" value={form.signing_secret} onChange={(e) => set({ signing_secret: e.target.value })} autoComplete="off" />
                <Button variant="secondary" onClick={() => set({ signing_secret: randomSecret() })}>
                  Generate
                </Button>
              </div>
            </Field>
            {form.signing_secret && <Notice tone="blue">Copy this secret to your app now. It is not shown again after saving.</Notice>}
            <details className="rounded-lg bg-slate-50 px-4 py-3 text-sm ring-1 ring-slate-200">
              <summary className="cursor-pointer font-medium text-slate-700">What your app receives after each call</summary>
              <pre className="mt-2 max-h-72 overflow-auto rounded bg-slate-900 px-3 py-2 text-xs text-slate-200">{sample.data ? JSON.stringify(sample.data, null, 2) : "Loading..."}</pre>
              <p className="mt-2 text-xs text-slate-500">Phone numbers are always masked. Fields from your upload (like a customer ID) come back under contact.fields and items.</p>
            </details>
          </div>
        )}
        <details className="mt-4 text-sm">
          <summary className="cursor-pointer text-slate-500">Advanced: extra headers</summary>
          <Field label="Extra headers" hint="One per line, e.g. X-Tenant: bullmachines" className="mt-2">
            <TextArea rows={2} className="font-mono text-xs" value={form.headers} onChange={(e) => set({ headers: e.target.value })} />
          </Field>
        </details>
      </Step>
    </Drawer>
  );
}

function exampleReply(ex: DeptExample): string {
  const [first, second] = ex.fetchPath.split(".");
  const person = ex.people[0];
  const record = `{ "name": "${person[0]}", "mobile": "${person[1]}", "company": "${person[2]}", "${ex.fields[0].label.toLowerCase().replace(/\s+/g, "_")}": "${ex.fields[0].values[0]}" }`;
  return second ? `{ "${first}": { "${second}": [\n    ${record},\n    ...\n] } }` : `{ "${first}": [\n    ${record},\n    ...\n] }`;
}
