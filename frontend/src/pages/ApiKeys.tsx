import { useState, type FormEvent } from "react";

import { Badge, Button, ChoiceCards, Drawer, EmptyState, ErrorBox, Field, Icon, Input, Loading, Modal, Notice, Segmented, Select, Step, formatDate } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useExamples } from "../lib/examples";
import { useAction, useApi } from "../lib/hooks";
import type { ApiKey, ApiKeyAccess, ApiKeyCreated } from "../lib/types";

const API_BASE = `${window.location.origin}${import.meta.env.BASE_URL}api/v1`;
const MCP_URL = `${API_BASE}/mcp`;

const ACCESS: Record<ApiKeyAccess, { label: string; description: string }> = {
  read: { label: "Read only", description: "See campaigns, scripts, calls and their results. Safe for reports and dashboards." },
  write: {
    label: "Read and run campaigns",
    description: "Also create campaigns, add people and start or pause calling. Approving always stays with a person in the app.",
  },
};

const EXPIRY: [string, string][] = [
  ["30", "30 days"],
  ["90", "90 days (recommended)"],
  ["365", "1 year"],
  ["", "Never"],
];

function keyState(k: ApiKey): { label: string; tone: "green" | "slate" | "red" } {
  if (k.revoked_at) return { label: "revoked", tone: "red" };
  if (k.expires_at && new Date(k.expires_at) <= new Date()) return { label: "expired", tone: "slate" };
  return { label: "active", tone: "green" };
}

export function ApiKeysSection() {
  const { me } = useAuth();
  const list = useApi<ApiKey[]>("/api-keys");
  const [creating, setCreating] = useState(false);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [showOld, setShowOld] = useState(false);
  const action = useAction();
  const keys = list.data ?? [];
  const visible = showOld ? keys : keys.filter((k) => keyState(k).label === "active");

  const revoke = (k: ApiKey) => {
    if (!window.confirm(`Revoke "${k.name}"? Every app using it stops working immediately.`)) return;
    action.run(async () => {
      await api.post(`/api-keys/${k.id}/revoke`);
      list.reload();
    });
  };

  return (
    <section>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <Icon name="key" className="h-4 w-4 text-slate-400" />
        <h2 className="text-[15px] font-semibold text-slate-900">Let apps and AI assistants use Bull AI Calling</h2>
        <span className="text-sm text-slate-500">· API keys for other systems, and MCP for Claude and other assistants</span>
        <span className="flex-1" />
        <Button variant="secondary" onClick={() => setCreating(true)}>
          <Icon name="plus" />
          Create API key
        </Button>
      </div>
      <ErrorBox error={list.error || action.error} />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 rounded-xl border border-slate-200 bg-white shadow-sm">
          {list.loading && !list.data ? (
            <Loading />
          ) : visible.length === 0 ? (
            <EmptyState
              title="No active API keys"
              description="Create a key for each app or assistant, so you can switch one off without affecting the others."
              action={<Button onClick={() => setCreating(true)}>Create API key</Button>}
            />
          ) : (
            <ul className="divide-y divide-slate-100">
              {visible.map((k) => {
                const state = keyState(k);
                return (
                  <li key={k.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3.5">
                    <div className="min-w-0 flex-1">
                      <p className="flex flex-wrap items-center gap-2 font-medium text-slate-900">
                        {k.name}
                        <Badge tone={state.tone}>{state.label}</Badge>
                        <Badge tone={k.access === "write" ? "amber" : "slate"}>{k.access === "write" ? "read and run" : "read only"}</Badge>
                      </p>
                      <p className="mt-0.5 text-xs text-slate-500">
                        <span className="font-mono">{k.prefix}…</span>
                        {me?.role === "admin" && k.user_name && ` · ${k.user_name}`}
                        {` · last used ${k.last_used_at ? formatDate(k.last_used_at, true) : "never"}`}
                        {` · ${k.expires_at ? `expires ${formatDate(k.expires_at)}` : "never expires"}`}
                      </p>
                    </div>
                    {state.label === "active" && (
                      <Button variant="ghost" className="text-red-600 hover:bg-red-50 hover:text-red-700" onClick={() => revoke(k)}>
                        Revoke
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
          {keys.length > visible.length || showOld ? (
            <button type="button" onClick={() => setShowOld(!showOld)} className="w-full border-t border-slate-100 px-5 py-2.5 text-left text-xs text-slate-500 hover:text-slate-800">
              {showOld ? "Hide revoked and expired keys" : `Show ${keys.length - visible.length} revoked or expired`}
            </button>
          ) : null}
        </div>

        <aside className="rounded-xl border border-slate-200 bg-white p-5 text-sm">
          <p className="font-semibold text-slate-900">Addresses</p>
          <p className="mt-3 text-xs font-medium uppercase tracking-wide text-slate-500">MCP server</p>
          <CopyLine text={MCP_URL} />
          <p className="mt-3 text-xs font-medium uppercase tracking-wide text-slate-500">REST API</p>
          <CopyLine text={API_BASE} />
          <a href={`${API_BASE}/docs`} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-slate-600 underline hover:text-slate-900">
            API documentation <Icon name="chevronRight" className="h-3 w-3" />
          </a>
          <p className="mt-4 text-xs leading-relaxed text-slate-500">
            A key acts as the person who created it, in their department only. It can never approve a script or campaign, manage accounts or other keys.
          </p>
        </aside>
      </div>

      {creating && (
        <CreateKey
          onCancel={() => setCreating(false)}
          onCreated={(k) => {
            setCreating(false);
            setCreated(k);
            list.reload();
          }}
        />
      )}
      {created && <KeyCreated apiKey={created} onClose={() => setCreated(null)} />}
    </section>
  );
}

function CopyLine({ text, secret = false }: { text: string; secret?: boolean }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-1 flex items-center gap-1 rounded-lg bg-slate-50 py-1 pl-2.5 pr-1 ring-1 ring-slate-200">
      <code className={`min-w-0 flex-1 truncate text-xs ${secret ? "font-semibold text-slate-900" : "text-slate-700"}`} title={text}>
        {text}
      </code>
      <button
        type="button"
        aria-label="Copy"
        onClick={async () => {
          try {
            await navigator.clipboard.writeText(text);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          } catch {
            setCopied(false);
          }
        }}
        className="rounded-md p-1.5 text-slate-500 hover:bg-white hover:text-slate-900"
      >
        <Icon name={copied ? "check" : "copy"} className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function CreateKey({ onCancel, onCreated }: { onCancel: () => void; onCreated: (k: ApiKeyCreated) => void }) {
  const ex = useExamples();
  const [form, setForm] = useState({ name: "", access: "read" as ApiKeyAccess, expiry: "90" });
  const { busy, error, run } = useAction();
  const examples = [`${ex.system.split(" (")[0]} reports`, "Claude assistant", `${ex.scriptName} automation`];

  const submit = (e: FormEvent) => {
    e.preventDefault();
    run(async () => onCreated(await api.post<ApiKeyCreated>("/api-keys", { name: form.name, access: form.access, expires_in_days: form.expiry ? Number(form.expiry) : null })));
  };

  return (
    <Drawer
      title="Create API key"
      subtitle="One key per app or assistant. You will see the key once, with setup instructions."
      onClose={onCancel}
      onSubmit={submit}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "Creating..." : "Create key"}
          </Button>
        </>
      }
    >
      <ErrorBox error={error} />
      <Step plain n={1} title="Who will use it?" help="A name that says which app or assistant has this key." done={!!form.name.trim()}>
        <Field label="Name">
          <Input autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder={`e.g. ${examples[1]}`} required />
        </Field>
        <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
          {examples.map((n) => (
            <button key={n} type="button" onClick={() => setForm({ ...form, name: n })} className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700 hover:bg-slate-200">
              {n}
            </button>
          ))}
        </div>
      </Step>
      <Step plain n={2} title="What may it do?" help="Give the least it needs. It works only in your department." done>
        <ChoiceCards<ApiKeyAccess>
          columns={1}
          value={form.access}
          onChange={(access) => setForm({ ...form, access })}
          options={(Object.keys(ACCESS) as ApiKeyAccess[]).map((a) => ({ value: a, label: ACCESS[a].label, description: ACCESS[a].description, icon: a === "read" ? "search" : "megaphone" }))}
        />
      </Step>
      <Step plain last n={3} title="How long should it work?" help="You can revoke it at any time." done>
        <Select value={form.expiry} onChange={(e) => setForm({ ...form, expiry: e.target.value })}>
          {EXPIRY.map(([v, l]) => (
            <option key={l} value={v}>
              {l}
            </option>
          ))}
        </Select>
      </Step>
    </Drawer>
  );
}

type Setup = "claude" | "json" | "rest";

function KeyCreated({ apiKey, onClose }: { apiKey: ApiKeyCreated; onClose: () => void }) {
  const [setup, setSetup] = useState<Setup>("claude");
  const snippets: Record<Setup, { title: string; text: string; help: string }> = {
    claude: {
      title: "Claude Code",
      text: `claude mcp add --transport http bull-ai-calling ${MCP_URL} --header "Authorization: Bearer ${apiKey.key}"`,
      help: "Run this once in a terminal. Then ask, for example: \"Which campaigns are running, and what did the last calls say?\"",
    },
    json: {
      title: "Other MCP apps",
      text: JSON.stringify({ mcpServers: { "bull-ai-calling": { type: "http", url: MCP_URL, headers: { Authorization: `Bearer ${apiKey.key}` } } } }, null, 2),
      help: "For assistants that take an MCP server address and headers. Where this goes depends on the app; look for \"MCP servers\" in its settings.",
    },
    rest: {
      title: "REST API",
      text: `curl -H "Authorization: Bearer ${apiKey.key}" ${API_BASE}/campaigns`,
      help: "For your own systems and scripts. Every endpoint is described in the API documentation.",
    },
  };
  const s = snippets[setup];
  return (
    <Modal
      title={`"${apiKey.name}" is ready`}
      onClose={onClose}
      icon={
        <span className="mb-4 flex h-11 w-11 items-center justify-center rounded-full bg-emerald-100 text-emerald-600">
          <Icon name="key" className="h-5 w-5" />
        </span>
      }
      footer={<Button onClick={onClose}>I have saved the key</Button>}
    >
      <Notice>Copy the key now. It is shown only once; if it is lost, revoke it and create a new one.</Notice>
      <CopyLine text={apiKey.key} secret />
      <div className="mt-5">
        <Segmented<Setup>
          value={setup}
          onChange={setSetup}
          options={(Object.keys(snippets) as Setup[]).map((k) => ({ value: k, label: snippets[k].title }))}
        />
        <pre className="mt-3 max-h-48 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-slate-900 px-3 py-2.5 text-[11px] leading-relaxed text-slate-200">{s.text}</pre>
        <div className="mt-2 flex items-start gap-2">
          <p className="flex-1 text-xs leading-relaxed text-slate-500">{s.help}</p>
          <CopyButton text={s.text} />
        </div>
      </div>
    </Modal>
  );
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="secondary"
      className="shrink-0 px-2.5 py-1 text-xs"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
        } catch {
          setCopied(false);
        }
      }}
    >
      <Icon name={copied ? "check" : "copy"} className="h-3.5 w-3.5" />
      {copied ? "Copied" : "Copy"}
    </Button>
  );
}
