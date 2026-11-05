import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { DepartmentPicker, departmentPayload } from "../components/DepartmentPicker";
import { Button, Card, ErrorBox, Field, Input, LANGUAGE_NAMES, Loading, Notice, PageHeader, Select, StatusBadge, TextArea } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction, useApi } from "../lib/hooks";
import type { ContextField, Question, QuestionType, Script, ScriptConfig, ScriptVersion } from "../lib/types";

const LANGUAGES = ["ta-IN", "en-IN", "hi-IN"];

const BLANK: ScriptConfig = {
  objective: "",
  agent: { name: "Bull Machines calling assistant", organisation: "Bull Machines", introduction: "" },
  system_instructions:
    "You are an automated calling assistant for Bull Machines Pvt Ltd. Say clearly that you are an automated assistant. Be polite, brief and professional. Speak in the person's language and switch if they switch. Only record what the person actually says.",
  languages: { default: "ta-IN", allowed: ["ta-IN", "en-IN", "hi-IN"], auto_detect: true, allow_switching: true },
  voice: { provider: "gemini", voice_name: "Sulafat" },
  context_fields: [],
  questions: [{ id: "q1", prompt: "", type: "yes_no", required: true }],
  business_rules: [],
  limits: { max_call_seconds: 300, silence_timeout_seconds: 8, max_silence_prompts: 2, max_turns: 40 },
  closing: { confirm_before_close: true, statement: "Thank you for your time. Have a good day." },
  escalation: { human_transfer_enabled: false, triggers: [], message: null },
};

const BLANK_SCHEMA = { type: "object", properties: { summary: { type: "string" }, confidence: { type: "number", minimum: 0, maximum: 1 } } };

const lines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);

export function ScriptEditorPage() {
  const { scriptId, versionId } = useParams();
  const navigate = useNavigate();
  const { me, can } = useAuth();
  const script = useApi<Script>(scriptId ? `/scripts/${scriptId}` : null);
  const version = useApi<ScriptVersion>(versionId ? `/script-versions/${versionId}` : null);
  const [config, setConfig] = useState<ScriptConfig | null>(versionId ? null : BLANK);
  const [schemaText, setSchemaText] = useState(JSON.stringify(BLANK_SCHEMA, null, 2));
  const [meta, setMeta] = useState({ name: "", description: "" });
  const [department, setDepartment] = useState("");
  const [comments, setComments] = useState("");
  const [saved, setSaved] = useState(false);
  const action = useAction();

  useEffect(() => {
    if (version.data) {
      setConfig(version.data.config);
      setSchemaText(JSON.stringify(version.data.extraction_schema, null, 2));
    }
  }, [version.data]);

  if (versionId && (!config || !version.data || !script.data)) {
    return version.error || script.error ? <ErrorBox error={version.error || script.error} /> : <Loading />;
  }
  if (!config) return <Loading />;

  const status = version.data?.status ?? "draft";
  const editable = status === "draft" && can("scripts:write");
  const update = (change: Partial<ScriptConfig>) => {
    setSaved(false);
    setConfig({ ...config, ...change });
  };

  const body = () => {
    let schema: unknown;
    try {
      schema = JSON.parse(schemaText);
    } catch {
      throw new Error("The extraction schema is not valid JSON");
    }
    return { config, extraction_schema: schema };
  };

  const save = () =>
    action.run(async () => {
      if (!versionId) {
        const created = await api.post<Script>("/scripts", { ...body(), name: meta.name, description: meta.description || null, ...departmentPayload(me?.role, department) });
        navigate(`/scripts/${created.id}/versions/${created.versions[0].id}`, { replace: true });
      } else {
        await api.put(`/script-versions/${versionId}`, body());
        setSaved(true);
        version.reload();
      }
    });

  const transition = (step: "submit" | "approve" | "reject") =>
    action.run(async () => {
      if (step === "submit" && editable) await api.put(`/script-versions/${versionId}`, body());
      await api.post(`/script-versions/${versionId}/${step}`, step === "submit" ? {} : { comments: comments || null });
      setComments("");
      version.reload();
      script.reload();
    });

  const newVersion = () =>
    action.run(async () => {
      const created = await api.post<ScriptVersion>(`/scripts/${scriptId}/versions`, body());
      navigate(`/scripts/${scriptId}/versions/${created.id}`);
    });

  const otherVersions = script.data?.versions.filter((v) => v.id !== versionId) ?? [];

  return (
    <>
      <PageHeader
        title={script.data ? `${script.data.name} · v${version.data?.version_no}` : "New script"}
        subtitle={script.data?.description ?? undefined}
        actions={
          <>
            {version.data && <StatusBadge status={status} />}
            {otherVersions.length > 0 && (
              <Select className="w-auto" value="" onChange={(e) => e.target.value && navigate(`/scripts/${scriptId}/versions/${e.target.value}`)}>
                <option value="">Other versions...</option>
                {otherVersions.map((v) => (
                  <option key={v.id} value={v.id}>
                    v{v.version_no} ({v.status.replace("_", " ")})
                  </option>
                ))}
              </Select>
            )}
          </>
        }
      />
      <ErrorBox error={action.error} />
      {saved && <Notice tone="green">Draft saved.</Notice>}
      {status === "published" && <Notice tone="green">Published. It cannot be changed; campaigns keep this exact version. To change it, create a new version.</Notice>}
      {status === "retired" && <Notice>Retired: a newer version has been published. Campaigns already using this version keep it.</Notice>}
      {status === "pending_approval" && <Notice tone="blue">Waiting for approval by someone other than the author (a colleague in the department, or an admin).</Notice>}

      <fieldset disabled={!editable} className="space-y-4">
        {!versionId && (
          <Card title="Script">
            <div className="grid gap-3 md:grid-cols-2">
              <DepartmentPicker value={department} onChange={setDepartment} />
              <Field label="Name">
                <Input value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} required />
              </Field>
              <Field label="Description" className="md:col-span-2">
                <Input value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })} />
              </Field>
            </div>
          </Card>
        )}

        <Card title="Purpose and identity">
          <div className="grid gap-3">
            <Field label="Objective">
              <TextArea value={config.objective} onChange={(e) => update({ objective: e.target.value })} />
            </Field>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Agent name">
                <Input value={config.agent.name} onChange={(e) => update({ agent: { ...config.agent, name: e.target.value } })} />
              </Field>
              <Field label="Organisation">
                <Input value={config.agent.organisation} onChange={(e) => update({ agent: { ...config.agent, organisation: e.target.value } })} />
              </Field>
            </div>
            <Field label="Introduction" hint="Placeholders: {contact.name}, {contact.company}, {agent.name}, {context.<field key>}">
              <TextArea value={config.agent.introduction} onChange={(e) => update({ agent: { ...config.agent, introduction: e.target.value } })} />
            </Field>
            <Field label="Instructions to the AI">
              <TextArea rows={6} value={config.system_instructions} onChange={(e) => update({ system_instructions: e.target.value })} />
            </Field>
          </div>
        </Card>

        <Card title="Language and voice">
          <div className="grid gap-3 md:grid-cols-4">
            <Field label="Allowed languages" className="md:col-span-2">
              <div className="flex flex-wrap gap-3 py-1.5">
                {LANGUAGES.map((code) => (
                  <label key={code} className="flex items-center gap-1 text-sm">
                    <input
                      type="checkbox"
                      checked={config.languages.allowed.includes(code)}
                      onChange={(e) =>
                        update({
                          languages: {
                            ...config.languages,
                            allowed: e.target.checked ? [...config.languages.allowed, code] : config.languages.allowed.filter((c) => c !== code),
                          },
                        })
                      }
                    />
                    {LANGUAGE_NAMES[code]}
                  </label>
                ))}
              </div>
            </Field>
            <Field label="Start in">
              <Select value={config.languages.default} onChange={(e) => update({ languages: { ...config.languages, default: e.target.value } })}>
                {config.languages.allowed.map((code) => (
                  <option key={code} value={code}>
                    {LANGUAGE_NAMES[code] ?? code}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Voice name" hint="Gemini voice">
              <Input value={config.voice.voice_name} onChange={(e) => update({ voice: { ...config.voice, voice_name: e.target.value } })} />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={config.languages.auto_detect} onChange={(e) => update({ languages: { ...config.languages, auto_detect: e.target.checked } })} />
              Detect the caller's language
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={config.languages.allow_switching} onChange={(e) => update({ languages: { ...config.languages, allow_switching: e.target.checked } })} />
              Switch language during the call
            </label>
          </div>
        </Card>

        <ContextFieldsEditor fields={config.context_fields} onChange={(context_fields) => update({ context_fields })} />
        <QuestionsEditor questions={config.questions} contextFields={config.context_fields} onChange={(questions) => update({ questions })} />

        <Card title="Rules, limits and closing">
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="Business rules" hint="One per line" className="md:col-span-2">
              <TextArea rows={5} value={config.business_rules.join("\n")} onChange={(e) => update({ business_rules: lines(e.target.value) })} />
            </Field>
            <div className="grid grid-cols-2 gap-3 md:col-span-2 md:grid-cols-4">
              {(
                [
                  ["max_call_seconds", "Max call length (s)"],
                  ["silence_timeout_seconds", "Silence timeout (s)"],
                  ["max_silence_prompts", "Silence prompts"],
                  ["max_turns", "Max turns"],
                ] as const
              ).map(([key, label]) => (
                <Field key={key} label={label}>
                  <Input type="number" value={config.limits[key]} onChange={(e) => update({ limits: { ...config.limits, [key]: Number(e.target.value) } })} />
                </Field>
              ))}
            </div>
            <Field label="Closing statement" className="md:col-span-2">
              <TextArea value={config.closing.statement} onChange={(e) => update({ closing: { ...config.closing, statement: e.target.value } })} />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={config.closing.confirm_before_close} onChange={(e) => update({ closing: { ...config.closing, confirm_before_close: e.target.checked } })} />
              Read back the collected answers before closing
            </label>
          </div>
        </Card>

        <Card title="Escalation">
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="When to offer a human callback" hint="One per line">
              <TextArea value={config.escalation.triggers.join("\n")} onChange={(e) => update({ escalation: { ...config.escalation, triggers: lines(e.target.value) } })} />
            </Field>
            <Field label="What the AI says">
              <TextArea value={config.escalation.message ?? ""} onChange={(e) => update({ escalation: { ...config.escalation, message: e.target.value || null } })} />
            </Field>
          </div>
        </Card>

        <Card title="Result fields (extraction schema)">
          <Field label="JSON Schema" hint="The structured result produced after each call. Must describe an object.">
            <TextArea rows={14} className="font-mono text-xs" value={schemaText} onChange={(e) => {
                setSaved(false);
                setSchemaText(e.target.value);
              }} />
          </Field>
        </Card>
      </fieldset>

      <Card className="mt-4">
        <div className="flex flex-wrap items-end gap-2">
          {editable && (
            <>
              <Button onClick={save} disabled={action.busy}>
                {versionId ? "Save draft" : "Create script"}
              </Button>
              {versionId && (
                <Button variant="secondary" onClick={() => transition("submit")} disabled={action.busy}>
                  Save and submit for approval
                </Button>
              )}
            </>
          )}
          {status === "pending_approval" && can("scripts:approve") && (
            <>
              <Field label="Comments" className="min-w-64 flex-1">
                <Input value={comments} onChange={(e) => setComments(e.target.value)} />
              </Field>
              <Button onClick={() => transition("approve")} disabled={action.busy}>
                Approve and publish
              </Button>
              <Button variant="danger" onClick={() => transition("reject")} disabled={action.busy}>
                Send back
              </Button>
            </>
          )}
          {(status === "published" || status === "retired") && can("scripts:write") && (
            <Button variant="secondary" onClick={newVersion} disabled={action.busy}>
              Create new version from this
            </Button>
          )}
        </div>
      </Card>
    </>
  );
}

function ContextFieldsEditor({ fields, onChange }: { fields: ContextField[]; onChange: (f: ContextField[]) => void }) {
  const set = (i: number, change: Partial<ContextField>) => onChange(fields.map((f, j) => (i === j ? { ...f, ...change } : f)));
  return (
    <Card title="Campaign data per call" actions={<Button variant="secondary" onClick={() => onChange([...fields, { key: "", label: "", type: "string", required: true }])}>Add field</Button>}>
      <p className="mb-3 text-sm text-slate-500">Data each call needs from the campaign upload, e.g. PO number. Use in prompts as {"{context.key}"}.</p>
      {fields.length === 0 && <p className="text-sm text-slate-500">None.</p>}
      <div className="space-y-2">
        {fields.map((f, i) => (
          <div key={i} className="grid items-end gap-2 md:grid-cols-[1fr_1fr_8rem_6rem_auto]">
            <Field label="Key">
              <Input value={f.key} onChange={(e) => set(i, { key: e.target.value })} placeholder="po_number" />
            </Field>
            <Field label="Label">
              <Input value={f.label} onChange={(e) => set(i, { label: e.target.value })} placeholder="PO Number" />
            </Field>
            <Field label="Type">
              <Select value={f.type} onChange={(e) => set(i, { type: e.target.value as ContextField["type"] })}>
                <option value="string">Text</option>
                <option value="number">Number</option>
                <option value="date">Date</option>
              </Select>
            </Field>
            <label className="flex items-center gap-1 pb-2 text-sm">
              <input type="checkbox" checked={f.required} onChange={(e) => set(i, { required: e.target.checked })} /> Required
            </label>
            <Button variant="ghost" onClick={() => onChange(fields.filter((_, j) => j !== i))}>
              Remove
            </Button>
          </div>
        ))}
      </div>
    </Card>
  );
}

const QUESTION_TYPES: Record<QuestionType, string> = { yes_no: "Yes / No", text: "Free text", date: "Date", number: "Number", choice: "Choice" };

function QuestionsEditor({ questions, contextFields, onChange }: { questions: Question[]; contextFields: ContextField[]; onChange: (q: Question[]) => void }) {
  const set = (i: number, change: Partial<Question>) => onChange(questions.map((q, j) => (i === j ? { ...q, ...change } : q)));
  const move = (i: number, by: number) => {
    const next = [...questions];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    onChange(next);
  };
  const add = () => onChange([...questions, { id: `q${questions.length + 1}`, prompt: "", type: "text", required: true }]);

  return (
    <Card title="Questions" actions={<Button variant="secondary" onClick={add}>Add question</Button>}>
      <p className="mb-3 text-sm text-slate-500">Asked in this order. A question with a condition is asked only when an earlier answer matches.</p>
      <div className="space-y-4">
        {questions.map((q, i) => {
          const earlier = questions.slice(0, i);
          const parent = earlier.find((p) => p.id === q.condition?.question_id);
          return (
            <div key={i} className="rounded-md border border-slate-200 p-3">
              <div className="grid gap-2 md:grid-cols-[8rem_1fr_9rem]">
                <Field label="ID">
                  <Input value={q.id} onChange={(e) => set(i, { id: e.target.value })} />
                </Field>
                <Field label="What to ask">
                  <Input value={q.prompt} onChange={(e) => set(i, { prompt: e.target.value })} />
                </Field>
                <Field label="Answer type">
                  <Select value={q.type} onChange={(e) => set(i, { type: e.target.value as QuestionType, choices: e.target.value === "choice" ? (q.choices ?? []) : null })}>
                    {Object.entries(QUESTION_TYPES).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              <div className="mt-2 grid gap-2 md:grid-cols-4">
                {q.type === "choice" && (
                  <Field label="Choices" hint="Comma-separated">
                    <Input value={(q.choices ?? []).join(", ")} onChange={(e) => set(i, { choices: e.target.value.split(",").map((c) => c.trim()).filter(Boolean) })} />
                  </Field>
                )}
                <Field label="Ask only if">
                  <Select
                    value={q.condition?.question_id ?? ""}
                    onChange={(e) => set(i, { condition: e.target.value ? { question_id: e.target.value, equals: true } : null })}
                  >
                    <option value="">Always</option>
                    {earlier.map((p) => (
                      <option key={p.id} value={p.id}>
                        answer to {p.id}
                      </option>
                    ))}
                  </Select>
                </Field>
                {q.condition && (
                  <Field label="Equals">
                    {parent?.type === "yes_no" ? (
                      <Select value={String(q.condition.equals)} onChange={(e) => set(i, { condition: { ...q.condition!, equals: e.target.value === "true" } })}>
                        <option value="true">Yes</option>
                        <option value="false">No</option>
                      </Select>
                    ) : parent?.type === "choice" ? (
                      <Select value={String(q.condition.equals)} onChange={(e) => set(i, { condition: { ...q.condition!, equals: e.target.value } })}>
                        {(parent.choices ?? []).map((c) => (
                          <option key={c}>{c}</option>
                        ))}
                      </Select>
                    ) : (
                      <Input value={String(q.condition.equals)} onChange={(e) => set(i, { condition: { ...q.condition!, equals: e.target.value } })} />
                    )}
                  </Field>
                )}
                {q.type === "date" && contextFields.some((f) => f.type === "date") && (
                  <Field label="Not before">
                    <Select
                      value={q.validation?.not_before_context_field ?? ""}
                      onChange={(e) => set(i, { validation: e.target.value ? { ...q.validation, not_before_context_field: e.target.value } : null })}
                    >
                      <option value="">No check</option>
                      {contextFields
                        .filter((f) => f.type === "date")
                        .map((f) => (
                          <option key={f.key} value={f.key}>
                            {f.label}
                          </option>
                        ))}
                    </Select>
                  </Field>
                )}
                <Field label="Result field" hint="e.g. items[].delay_reason">
                  <Input value={q.maps_to ?? ""} onChange={(e) => set(i, { maps_to: e.target.value || null })} />
                </Field>
              </div>
              <div className="mt-2 flex items-center gap-3 text-sm">
                <label className="flex items-center gap-1">
                  <input type="checkbox" checked={q.required} onChange={(e) => set(i, { required: e.target.checked })} /> Required
                </label>
                <span className="flex-1" />
                <Button variant="ghost" disabled={i === 0} onClick={() => move(i, -1)}>
                  Up
                </Button>
                <Button variant="ghost" disabled={i === questions.length - 1} onClick={() => move(i, 1)}>
                  Down
                </Button>
                <Button variant="ghost" disabled={questions.length === 1} onClick={() => onChange(questions.filter((_, j) => j !== i))}>
                  Remove
                </Button>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
