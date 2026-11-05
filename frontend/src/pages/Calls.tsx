import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";

import { DepartmentPicker, departmentPayload } from "../components/DepartmentPicker";
import { Badge, Button, Card, ErrorBox, Field, Input, LANGUAGE_NAMES, Loading, Notice, PageHeader, Pager, Select, StatusBadge, Table, Td, formatDate } from "../components/ui";
import { api, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction, useApi } from "../lib/hooks";
import type { Call, Contact, Page, ScriptVersion } from "../lib/types";
import { usePublishedVersions } from "./Campaigns";

const PAGE_SIZE = 25;

export function ModeNotice({ mode }: { mode: string | undefined }) {
  if (mode === "live") return null;
  if (mode === "mock")
    return (
      <Notice tone="blue">
        Simulation mode: calls are not placed on the phone network. Every call here is marked <b>simulated</b> and is never
        counted as a real result.
      </Notice>
    );
  if (mode === "disabled") return <Notice>Calling is switched off on this server (TELEPHONY_MODE=disabled).</Notice>;
  return null;
}

export function CallsPage() {
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const [creating, setCreating] = useState(false);
  const mode = useApi<{ mode: string }>("/calls/mode");
  const list = useApi<Page<Call>>(`/calls${query({ page, page_size: PAGE_SIZE })}`);

  return (
    <>
      <PageHeader
        title="Calls"
        subtitle="Individual calls placed from here, and (from Phase 4) campaign calls."
        actions={can("calls:place") && mode.data?.mode !== "disabled" && <Button onClick={() => setCreating(true)}>New call</Button>}
      />
      <ModeNotice mode={mode.data?.mode} />
      {creating && <NewCall onCancel={() => setCreating(false)} />}
      <ErrorBox error={list.error} />
      <Card>
        {list.loading && !list.data ? (
          <Loading />
        ) : (
          <>
            <Table headers={["When", "Who", "Phone", "Status", "Outcome", "Length"]} empty={list.data?.items.length === 0}>
              {list.data?.items.map((c) => (
                <tr key={c.id}>
                  <Td className="whitespace-nowrap">
                    <Link to={`/calls/${c.id}`} className="text-sky-800 hover:underline">
                      {formatDate(c.created_at, true)}
                    </Link>
                  </Td>
                  <Td>
                    {c.contact_name ?? "-"} {c.is_simulated && <Badge tone="blue">simulated</Badge>}
                  </Td>
                  <Td className="font-mono text-xs">{c.phone_masked}</Td>
                  <Td>
                    <StatusBadge status={c.status} />
                  </Td>
                  <Td>{c.outcome?.replace(/_/g, " ") ?? "-"}</Td>
                  <Td>{c.duration_seconds != null ? `${c.duration_seconds}s` : "-"}</Td>
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

function NewCall({ onCancel }: { onCancel: () => void }) {
  const { me } = useAuth();
  const navigate = useNavigate();
  const versions = usePublishedVersions();
  const [target, setTarget] = useState<"contact" | "number">("contact");
  const [search, setSearch] = useState("");
  const [contact, setContact] = useState<Contact | null>(null);
  const [manual, setManual] = useState({ phone: "", name: "", company: "" });
  const [department, setDepartment] = useState("");
  const [versionId, setVersionId] = useState("");
  const [language, setLanguage] = useState("");
  const [items, setItems] = useState<Record<string, string>[]>([{}]);
  const found = useApi<Page<Contact>>(target === "contact" && search.trim().length >= 2 ? `/contacts${query({ search: search.trim(), page_size: 8 })}` : null);
  const version = useApi<ScriptVersion>(versionId ? `/script-versions/${versionId}` : null);
  const { busy, error, run } = useAction();

  const fields = version.data?.config.context_fields ?? [];
  const deptId = target === "contact" ? contact?.department_id : me?.role === "admin" ? department : me?.department_id;
  const options = versions.options.filter((v) => !deptId || v.departmentId === deptId);

  const setItem = (i: number, key: string, value: string) => setItems(items.map((item, j) => (i === j ? { ...item, [key]: value } : item)));

  const submit = (event: FormEvent) => {
    event.preventDefault();
    run(async () => {
      const cleaned = items.map((item) => Object.fromEntries(Object.entries(item).filter(([, v]) => v.trim() !== ""))).filter((item) => Object.keys(item).length);
      const call = await api.post<Call>("/calls", {
        ...(target === "contact"
          ? { contact_id: contact?.id }
          : { phone: manual.phone, name: manual.name || null, company: manual.company || null, ...departmentPayload(me?.role, department) }),
        script_version_id: versionId,
        language: language || null,
        context: fields.length ? { items: cleaned } : {},
      });
      navigate(`/calls/${call.id}`);
    });
  };

  return (
    <Card title="New call" className="mb-4">
      <ErrorBox error={error} />
      <form onSubmit={submit} className="space-y-4">
        <div className="flex gap-4 text-sm">
          <label className="flex items-center gap-1">
            <input type="radio" checked={target === "contact"} onChange={() => setTarget("contact")} /> A contact
          </label>
          <label className="flex items-center gap-1">
            <input type="radio" checked={target === "number"} onChange={() => setTarget("number")} /> A number
          </label>
        </div>

        {target === "contact" ? (
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Find contact" hint="Name, company or full phone number">
              <Input value={search} onChange={(e) => {
                  setContact(null);
                  setSearch(e.target.value);
                }} />
            </Field>
            <div className="text-sm">
              {contact ? (
                <p className="pt-6">
                  <b>{contact.name}</b> {contact.company && `· ${contact.company}`} · <span className="font-mono">{contact.phone_masked}</span>{" "}
                  {contact.do_not_call && <Badge tone="red">Do not call</Badge>}
                </p>
              ) : (
                <ul className="divide-y divide-slate-100 pt-5">
                  {found.data?.items.map((c) => (
                    <li key={c.id}>
                      <button type="button" className="w-full py-1 text-left hover:bg-slate-50" onClick={() => {
                          setContact(c);
                          setLanguage(c.language ?? "");
                        }}>
                        {c.name} <span className="text-slate-500">{c.company}</span> <span className="font-mono text-xs">{c.phone_masked}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        ) : (
          <div className="grid gap-3 md:grid-cols-4">
            <DepartmentPicker value={department} onChange={setDepartment} />
            <Field label="Phone">
              <Input value={manual.phone} onChange={(e) => setManual({ ...manual, phone: e.target.value })} required />
            </Field>
            <Field label="Name">
              <Input value={manual.name} onChange={(e) => setManual({ ...manual, name: e.target.value })} />
            </Field>
            <Field label="Company">
              <Input value={manual.company} onChange={(e) => setManual({ ...manual, company: e.target.value })} />
            </Field>
          </div>
        )}

        <div className="grid gap-3 md:grid-cols-2">
          <Field label="Script" hint={options.length === 0 ? "No approved script for this department yet." : undefined}>
            <Select value={versionId} onChange={(e) => setVersionId(e.target.value)} required>
              <option value="">Choose...</option>
              {options.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Language">
            <Select value={language} onChange={(e) => setLanguage(e.target.value)}>
              <option value="">Script default</option>
              {(version.data?.config.languages.allowed ?? []).map((code) => (
                <option key={code} value={code}>
                  {LANGUAGE_NAMES[code] ?? code}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        {fields.length > 0 && (
          <div>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-slate-600">Call data (one row per line, e.g. per PO)</p>
            <div className="space-y-2">
              {items.map((item, i) => (
                <div key={i} className="grid items-end gap-2" style={{ gridTemplateColumns: `repeat(${fields.length}, minmax(0, 1fr)) auto` }}>
                  {fields.map((f) => (
                    <Field key={f.key} label={`${f.label}${f.required ? "" : " (optional)"}`}>
                      <Input type={f.type === "date" ? "date" : "text"} value={item[f.key] ?? ""} onChange={(e) => setItem(i, f.key, e.target.value)} />
                    </Field>
                  ))}
                  <Button variant="ghost" disabled={items.length === 1} onClick={() => setItems(items.filter((_, j) => j !== i))}>
                    Remove
                  </Button>
                </div>
              ))}
            </div>
            <Button variant="secondary" className="mt-2" onClick={() => setItems([...items, {}])}>
              Add line
            </Button>
          </div>
        )}

        <div className="flex gap-2">
          <Button type="submit" disabled={busy || !versionId || (target === "contact" && !contact)}>
            {busy ? "Placing call..." : "Call now"}
          </Button>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </form>
    </Card>
  );
}
