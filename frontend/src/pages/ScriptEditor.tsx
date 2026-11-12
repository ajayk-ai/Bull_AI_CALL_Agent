import { useEffect, useState, type ReactNode } from "react";
import { useNavigate, useParams } from "react-router";

import { DepartmentPicker, departmentPayload } from "../components/DepartmentPicker";
import { Button, Card, ErrorBox, Field, Input, LANGUAGE_NAMES, Loading, Notice, PageHeader, Select, StatusBadge, TextArea } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction, useApi } from "../lib/hooks";
import type { ContextField, Question, QuestionType, Script, ScriptConfig, ScriptVersion } from "../lib/types";

const LANGUAGES = ["ta-IN", "en-IN", "hi-IN"];

// Gemini Live voices and how they sound (from Google's voice list).
const VOICES: [string, string][] = [
  ["Sulafat", "Warm"],
  ["Achird", "Friendly"],
  ["Vindemiatrix", "Gentle"],
  ["Achernar", "Soft"],
  ["Aoede", "Breezy"],
  ["Callirrhoe", "Easy-going"],
  ["Umbriel", "Easy-going"],
  ["Zubenelgenubi", "Casual"],
  ["Despina", "Smooth"],
  ["Algieba", "Smooth"],
  ["Iapetus", "Clear"],
  ["Erinome", "Clear"],
  ["Schedar", "Even"],
  ["Charon", "Informative"],
  ["Rasalgethi", "Informative"],
  ["Sadaltager", "Knowledgeable"],
  ["Kore", "Firm"],
  ["Orus", "Firm"],
  ["Alnilam", "Firm"],
  ["Gacrux", "Mature"],
  ["Pulcherrima", "Forward"],
  ["Zephyr", "Bright"],
  ["Autonoe", "Bright"],
  ["Puck", "Upbeat"],
  ["Laomedeia", "Upbeat"],
  ["Sadachbia", "Lively"],
  ["Leda", "Youthful"],
  ["Fenrir", "Excitable"],
  ["Enceladus", "Breathy"],
  ["Algenib", "Gravelly"],
];

const CALL_MINUTES = [1, 2, 3, 4, 5, 7, 10, 15, 20, 30];

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

// ---- Results (extraction schema) built automatically from the questions ----

const AUTO_MARK = "Built automatically from the script's questions";
const ITEMS = "items[].";

/** A key the backend accepts: lowercase letters, digits and underscores, starting with a letter. */
const slug = (text: string) => {
  const s = text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 60);
  return s ? (/^[a-z]/.test(s) ? s : `f_${s}`) : "";
};

const isPerItem = (q: Question) => (q.maps_to ?? "").startsWith(ITEMS);
const resultName = (q: Question) => slug((q.maps_to ?? "").replace(ITEMS, "")) || q.id;

function answerSchema(q: Question): Record<string, unknown> {
  const description = q.prompt.slice(0, 300);
  switch (q.type) {
    case "yes_no":
      return { type: ["boolean", "null"], description };
    case "number":
      return { type: ["number", "null"], description };
    case "date":
      return { type: ["string", "null"], format: "date", description };
    case "choice":
      return { enum: [...(q.choices ?? []), null], description };
    default:
      return { type: ["string", "null"], description };
  }
}

function buildSchema(config: ScriptConfig): Record<string, unknown> {
  const call: Record<string, unknown> = {};
  const item: Record<string, unknown> = {};
  for (const f of config.context_fields) item[f.key] = { type: ["string", "number", "null"], description: f.label };
  for (const q of config.questions) (isPerItem(q) ? item : call)[resultName(q)] = answerSchema(q);
  return {
    $comment: AUTO_MARK,
    type: "object",
    properties: {
      ...call,
      ...(Object.keys(item).length > 0 && config.questions.some(isPerItem)
        ? { items: { type: "array", description: "One entry per line in the upload", items: { type: "object", properties: item } } }
        : {}),
      needs_followup: { type: "boolean", description: "Someone from the team should follow up" },
      followup_reason: { type: ["string", "null"] },
      confidence: { type: "number", minimum: 0, maximum: 1, description: "How sure you are about this record, 0 to 1" },
    },
    required: ["confidence"],
  };
}

// ---- Placeholders ----

const BUILTIN_PLACEHOLDERS: [string, string][] = [
  ["Person's name", "{contact.name}"],
  ["Company", "{contact.company}"],
  ["Assistant's name", "{agent.name}"],
  ["Our company", "{agent.organisation}"],
];

function InsertChips({ fields, onInsert }: { fields: ContextField[]; onInsert: (text: string) => void }) {
  const chips: [string, string][] = [...BUILTIN_PLACEHOLDERS, ...fields.filter((f) => f.key && f.label).map((f): [string, string] => [f.label, `{context.${f.key}}`])];
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1 text-xs text-slate-500">
      <span>Insert:</span>
      {chips.map(([label, token]) => (
        <button key={token} type="button" onClick={() => onInsert(token)} className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-700 hover:bg-slate-200 disabled:opacity-50" title={token}>
          + {label}
        </button>
      ))}
    </div>
  );
}

const append = (text: string, token: string) => (text && !text.endsWith(" ") ? `${text} ${token}` : `${text}${token}`);

// Common ways people write placeholders by hand, mapped to the ones the server knows.
const ALIASES: Record<string, string> = {
  "assistant.name": "agent.name",
  "bot.name": "agent.name",
  "ai.name": "agent.name",
  "agent.organization": "agent.organisation",
  "agent.company": "agent.organisation",
  "company.name": "agent.organisation",
  "organisation.name": "agent.organisation",
  "organization.name": "agent.organisation",
  "customer.name": "contact.name",
  "person.name": "contact.name",
  "supplier.name": "contact.name",
  "user.name": "contact.name",
  "contact.full_name": "contact.name",
  "customer.company": "contact.company",
  "supplier.company": "contact.company",
  "contact.organisation": "contact.company",
  "contact.organization": "contact.company",
};

const PLACEHOLDER = /\{\s*([A-Za-z_]+)\.([A-Za-z0-9_]+)\s*\}/g;

/** The texts that may contain placeholders, with where they are on the page. */
const placeholderTexts = (c: ScriptConfig): [string, string][] => [
  ["the opening line (step 2)", c.agent.introduction],
  ["how the assistant should behave (step 2)", c.system_instructions],
  ...c.questions.map((q, i): [string, string] => [`question ${i + 1} (step 5)`, q.prompt]),
  ["the closing line (step 6)", c.closing.statement],
  ["the hand-over message (step 7)", c.escalation.message ?? ""],
];

function fixPlaceholders(c: ScriptConfig): ScriptConfig {
  const fix = (t: string) =>
    t.replace(PLACEHOLDER, (_whole: string, scope: string, name: string) => {
      const key = `${scope.toLowerCase()}.${name.toLowerCase()}`;
      return `{${ALIASES[key] ?? key}}`;
    });
  return {
    ...c,
    agent: { ...c.agent, introduction: fix(c.agent.introduction) },
    system_instructions: fix(c.system_instructions),
    closing: { ...c.closing, statement: fix(c.closing.statement) },
    escalation: { ...c.escalation, message: c.escalation.message && fix(c.escalation.message) },
    questions: c.questions.map((q) => ({ ...q, prompt: fix(q.prompt) })),
  };
}

function unknownPlaceholders(c: ScriptConfig): string[] {
  const known = new Set(["contact.name", "contact.company", "agent.name", "agent.organisation", ...c.context_fields.map((f) => `context.${f.key}`)]);
  const out: string[] = [];
  for (const [where, text] of placeholderTexts(c)) {
    for (const [, scope, name] of text.matchAll(PLACEHOLDER)) {
      const key = `${scope}.${name}`;
      if (!known.has(key)) {
        out.push(
          scope === "context"
            ? `In ${where}, {${key}} is not one of your upload fields. Add it in step 4, or use the "Insert" buttons.`
            : `In ${where}, {${key}} is not recognised. Use the "Insert" buttons under the box instead of typing it.`,
        );
      }
    }
  }
  return out;
}

/** When a campaign field's key changes, keep every {context.key} reference pointing at it. */
function renameContextKey(config: ScriptConfig, from: string, to: string): ScriptConfig {
  const fix = (t: string) => t.split(`{context.${from}}`).join(`{context.${to}}`);
  return {
    ...config,
    agent: { ...config.agent, introduction: fix(config.agent.introduction) },
    system_instructions: fix(config.system_instructions),
    closing: { ...config.closing, statement: fix(config.closing.statement) },
    escalation: { ...config.escalation, message: config.escalation.message && fix(config.escalation.message) },
    questions: config.questions.map((q) => ({
      ...q,
      prompt: fix(q.prompt),
      validation: q.validation?.not_before_context_field === from ? { ...q.validation, not_before_context_field: to } : q.validation,
    })),
  };
}

// ---- Friendly checks before saving ----

function problems(config: ScriptConfig, name: string | null): string[] {
  const out: string[] = [];
  if (name !== null && !name.trim()) out.push("Give the script a name (step 1).");
  if (!config.objective.trim()) out.push("Describe the purpose of the call (step 2).");
  if (!config.agent.name.trim()) out.push("Give the assistant a name (step 2).");
  if (!config.agent.introduction.trim()) out.push("Write the opening line (step 2).");
  if (!config.system_instructions.trim()) out.push("Say how the assistant should behave (step 2).");
  if (config.languages.allowed.length === 0) out.push("Choose at least one language (step 3).");
  config.context_fields.forEach((f, i) => {
    if (!f.label.trim()) out.push(`Upload field ${i + 1} needs a name (step 4).`);
  });
  const keys = config.context_fields.map((f) => f.key);
  if (new Set(keys).size !== keys.length) out.push("Two upload fields have the same name (step 4).");
  config.questions.forEach((q, i) => {
    if (!q.prompt.trim()) out.push(`Question ${i + 1} is empty (step 5).`);
    if (q.type === "choice" && !(q.choices ?? []).length) out.push(`Question ${i + 1} needs the possible answers (step 5).`);
  });
  if (!config.closing.statement.trim()) out.push("Write the closing line (step 6).");
  out.push(...unknownPlaceholders(config));
  return out;
}

// ---- Page ----

export function ScriptEditorPage() {
  const { scriptId, versionId } = useParams();
  const navigate = useNavigate();
  const { me, can } = useAuth();
  const script = useApi<Script>(scriptId ? `/scripts/${scriptId}` : null);
  const version = useApi<ScriptVersion>(versionId ? `/script-versions/${versionId}` : null);
  const [config, setConfig] = useState<ScriptConfig | null>(versionId ? null : BLANK);
  const [autoResults, setAutoResults] = useState(true);
  const [schemaText, setSchemaText] = useState("");
  const [meta, setMeta] = useState({ name: "", description: "" });
  const [department, setDepartment] = useState("");
  const [comments, setComments] = useState("");
  const [saved, setSaved] = useState(false);
  const [issues, setIssues] = useState<string[]>([]);
  const action = useAction();

  useEffect(() => {
    if (version.data) {
      setConfig(version.data.config);
      const schema = version.data.extraction_schema;
      setAutoResults(schema?.$comment === AUTO_MARK);
      setSchemaText(JSON.stringify(schema, null, 2));
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

  const setContextFields = (fields: ContextField[]) => {
    let next = config;
    fields.forEach((f, i) => {
      const old = config.context_fields[i];
      if (old && old.key && f.key && old.key !== f.key && fields.length === config.context_fields.length) next = renameContextKey(next, old.key, f.key);
    });
    setSaved(false);
    setConfig({ ...next, context_fields: fields });
  };

  const check = () => {
    const fixed = fixPlaceholders(config);
    if (JSON.stringify(fixed) !== JSON.stringify(config)) setConfig(fixed);
    const found = problems(fixed, versionId ? null : meta.name);
    setIssues(found);
    if (found.length) window.scrollTo({ top: 0, behavior: "smooth" });
    return found.length === 0;
  };

  const body = () => {
    const clean = (list: string[]) => list.map((l) => l.trim()).filter(Boolean);
    const fixed = fixPlaceholders(config);
    const cfg: ScriptConfig = {
      ...fixed,
      business_rules: clean(config.business_rules),
      escalation: { ...fixed.escalation, triggers: clean(fixed.escalation.triggers), message: fixed.escalation.message?.trim() || null },
    };
    if (autoResults) return { config: cfg, extraction_schema: buildSchema(cfg) };
    try {
      return { config: cfg, extraction_schema: JSON.parse(schemaText) };
    } catch {
      throw new Error("The custom results format (step 8) is not valid JSON.");
    }
  };

  const save = () => {
    if (!check()) return;
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
  };

  const selfApprove = me?.second_approver_required === false && can("scripts:approve");

  const publish = () => {
    if (!check()) return;
    action.run(async () => {
      await api.put(`/script-versions/${versionId}`, body());
      await api.post(`/script-versions/${versionId}/submit`, {});
      await api.post(`/script-versions/${versionId}/approve`, { comments: null });
      version.reload();
      script.reload();
    });
  };

  const transition = (step: "submit" | "approve" | "reject") => {
    if (step === "submit" && !check()) return;
    action.run(async () => {
      if (step === "submit" && editable) await api.put(`/script-versions/${versionId}`, body());
      await api.post(`/script-versions/${versionId}/${step}`, step === "submit" ? {} : { comments: comments || null });
      setComments("");
      version.reload();
      script.reload();
    });
  };

  const newVersion = () =>
    action.run(async () => {
      const created = await api.post<ScriptVersion>(`/scripts/${scriptId}/versions`, body());
      navigate(`/scripts/${scriptId}/versions/${created.id}`);
    });

  const setLanguage = (code: string, on: boolean) => {
    const allowed = on ? LANGUAGES.filter((c) => c === code || config.languages.allowed.includes(c)) : config.languages.allowed.filter((c) => c !== code);
    if (allowed.length === 0) return;
    update({ languages: { ...config.languages, allowed, default: allowed.includes(config.languages.default) ? config.languages.default : allowed[0] } });
  };

  const otherVersions = script.data?.versions.filter((v) => v.id !== versionId) ?? [];
  const voiceKnown = VOICES.some(([v]) => v === config.voice.voice_name);
  const minutes = Math.round(config.limits.max_call_seconds / 60);
  const limit = (key: keyof ScriptConfig["limits"], value: number) => update({ limits: { ...config.limits, [key]: value } });

  return (
    <>
      <PageHeader
        title={script.data ? `${script.data.name} · v${version.data?.version_no}` : "New script"}
        subtitle={script.data?.description ?? "A script tells the AI assistant what to say on the call, what to ask and what to write down."}
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
      {issues.length > 0 && (
        <Notice>
          <p className="font-medium">Please fix these before saving:</p>
          <ul className="mt-1 list-disc pl-5">
            {issues.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </Notice>
      )}
      {saved && <Notice tone="green">Draft saved.</Notice>}
      {status === "published" && <Notice tone="green">Published. It cannot be changed; campaigns keep this exact version. To change it, create a new version.</Notice>}
      {status === "retired" && <Notice>Retired: a newer version has been published. Campaigns already using this version keep it.</Notice>}
      {status === "pending_approval" &&
        (selfApprove ? (
          <Notice tone="blue">Not published yet. Press "Publish" at the bottom to make it available to campaigns.</Notice>
        ) : (
          <Notice tone="blue">Waiting for approval by someone other than the author (a colleague in the department, or an admin).</Notice>
        ))}

      <fieldset disabled={!editable} className="space-y-4">
        {!versionId && (
          <Step n={1} title="Basics" help="How this script appears in the list. The person on the call never sees this.">
            <div className="grid gap-3 md:grid-cols-2">
              <DepartmentPicker value={department} onChange={setDepartment} />
              <Field label="Script name">
                <Input value={meta.name} onChange={(e) => setMeta({ ...meta, name: e.target.value })} placeholder="e.g. Supplier delivery check" required />
              </Field>
              <Field label="Short description (optional)" className="md:col-span-2">
                <Input value={meta.description} onChange={(e) => setMeta({ ...meta, description: e.target.value })} placeholder="e.g. Confirms delivery dates for open purchase orders" />
              </Field>
            </div>
          </Step>
        )}

        <Step n={2} title="Who is calling and why">
          <div className="grid gap-3">
            <Field label="Purpose of the call" hint="One or two sentences. The assistant uses this to stay on track.">
              <TextArea
                value={config.objective}
                onChange={(e) => update({ objective: e.target.value })}
                placeholder="e.g. Check whether each open purchase order will be delivered on time. If it is late, find out why and the new date."
              />
            </Field>
            <div className="grid gap-3 md:grid-cols-2">
              <Field label="Assistant's name" hint="How the assistant introduces itself.">
                <Input value={config.agent.name} onChange={(e) => update({ agent: { ...config.agent, name: e.target.value } })} />
              </Field>
              <Field label="Calling on behalf of">
                <Input value={config.agent.organisation} onChange={(e) => update({ agent: { ...config.agent, organisation: e.target.value } })} />
              </Field>
            </div>
            <div>
              <Field label="Opening line" hint="The first thing the assistant says. Words in { } are filled in for each person, e.g. {contact.name} becomes their name.">
                <TextArea
                  value={config.agent.introduction}
                  onChange={(e) => update({ agent: { ...config.agent, introduction: e.target.value } })}
                  placeholder="e.g. Hello, this is the Bull Machines calling assistant. Am I speaking with {contact.name} from {contact.company}?"
                />
              </Field>
              {editable && <InsertChips fields={config.context_fields} onInsert={(t) => update({ agent: { ...config.agent, introduction: append(config.agent.introduction, t) } })} />}
            </div>
            <Field label="How the assistant should behave" hint="Tone and manners. The default works for most calls.">
              <TextArea rows={4} value={config.system_instructions} onChange={(e) => update({ system_instructions: e.target.value })} />
            </Field>
          </div>
        </Step>

        <Step n={3} title="Language and voice">
          <div className="grid gap-4 md:grid-cols-3">
            <Field label="Languages it can speak">
              <div className="flex flex-wrap gap-3 py-1.5">
                {LANGUAGES.map((code) => (
                  <label key={code} className="flex items-center gap-1 text-sm">
                    <input type="checkbox" checked={config.languages.allowed.includes(code)} onChange={(e) => setLanguage(code, e.target.checked)} />
                    {LANGUAGE_NAMES[code]}
                  </label>
                ))}
              </div>
            </Field>
            <Field label="First language of the call">
              <Select value={config.languages.default} onChange={(e) => update({ languages: { ...config.languages, default: e.target.value } })}>
                {config.languages.allowed.map((code) => (
                  <option key={code} value={code}>
                    {LANGUAGE_NAMES[code] ?? code}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Voice">
              <Select value={config.voice.voice_name} onChange={(e) => update({ voice: { ...config.voice, voice_name: e.target.value } })}>
                {!voiceKnown && <option value={config.voice.voice_name}>{config.voice.voice_name}</option>}
                {VOICES.map(([name, style]) => (
                  <option key={name} value={name}>
                    {name} ({style})
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          {config.languages.allowed.length > 1 && (
            <label className="mt-3 flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={config.languages.auto_detect && config.languages.allow_switching}
                onChange={(e) => update({ languages: { ...config.languages, auto_detect: e.target.checked, allow_switching: e.target.checked } })}
              />
              Switch to the person's language if they speak a different one
            </label>
          )}
        </Step>

        <ContextFieldsEditor fields={config.context_fields} onChange={setContextFields} />
        <QuestionsEditor questions={config.questions} contextFields={config.context_fields} editable={editable} onChange={(questions) => update({ questions })} />

        <Step n={6} title="Rules and ending the call">
          <div className="grid gap-3">
            <Field label="Rules the assistant must follow (optional)" hint="One rule per line.">
              <TextArea
                rows={4}
                value={config.business_rules.join("\n")}
                onChange={(e) => update({ business_rules: e.target.value.split("\n") })}
                onBlur={(e) => update({ business_rules: e.target.value.split("\n").map((l) => l.trim()).filter(Boolean) })}
                placeholder={"e.g. Do not discuss prices or payments.\nIf the person is busy, ask for a better time to call and end politely."}
              />
            </Field>
            <Field label="Closing line" hint="The last thing the assistant says.">
              <TextArea rows={2} value={config.closing.statement} onChange={(e) => update({ closing: { ...config.closing, statement: e.target.value } })} />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={config.closing.confirm_before_close} onChange={(e) => update({ closing: { ...config.closing, confirm_before_close: e.target.checked } })} />
              Repeat the answers back to the person before ending, so they can correct mistakes
            </label>
          </div>
        </Step>

        <Step n={7} title="Handing over to a person (optional)" help="Situations where the assistant should stop and promise that someone from the team will call back.">
          <div className="grid gap-3 md:grid-cols-2">
            <Field label="When" hint="One situation per line.">
              <TextArea
                rows={4}
                value={config.escalation.triggers.join("\n")}
                onChange={(e) => update({ escalation: { ...config.escalation, triggers: e.target.value.split("\n") } })}
                onBlur={(e) => update({ escalation: { ...config.escalation, triggers: e.target.value.split("\n").map((l) => l.trim()).filter(Boolean) } })}
                placeholder={"e.g. The person asks to speak to someone\nThe person is upset or complaining"}
              />
            </Field>
            <Field label="What the assistant says then">
              <TextArea
                rows={4}
                value={config.escalation.message ?? ""}
                onChange={(e) => update({ escalation: { ...config.escalation, message: e.target.value || null } })}
                placeholder="e.g. I will ask a member of our team to call you back."
              />
            </Field>
          </div>
        </Step>

        <Step n={8} title="What gets saved after each call">
          {autoResults ? (
            <>
              <p className="text-sm text-slate-600">After each call, the answers to your questions are written down automatically, together with a short summary and whether the team needs to follow up. Nothing to set up here.</p>
              <ul className="mt-2 list-disc pl-5 text-sm text-slate-600">
                {config.questions.map((q, i) => (
                  <li key={i}>
                    Answer to question {i + 1}
                    {q.prompt ? `: "${q.prompt.length > 70 ? q.prompt.slice(0, 70) + "..." : q.prompt}"` : ""}
                    {isPerItem(q) && " (for each item)"}
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <Notice tone="blue">This script uses a custom results format, set up by a specialist. You can leave it as it is.</Notice>
          )}
          <details className="mt-3 text-sm">
            <summary className="cursor-pointer text-slate-500">Advanced: custom results format (for technical staff)</summary>
            <div className="mt-2 space-y-2">
              {autoResults ? (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setSchemaText(JSON.stringify(buildSchema(config), null, 2));
                    setAutoResults(false);
                    setSaved(false);
                  }}
                >
                  Switch to a custom format
                </Button>
              ) : (
                <>
                  <TextArea
                    rows={14}
                    className="font-mono text-xs"
                    value={schemaText}
                    onChange={(e) => {
                      setSaved(false);
                      setSchemaText(e.target.value);
                    }}
                  />
                  <p className="text-xs text-slate-500">A JSON Schema describing an object.</p>
                  <Button
                    variant="secondary"
                    onClick={() => {
                      if (window.confirm("Replace the custom format with one built automatically from the questions?")) {
                        setAutoResults(true);
                        setSaved(false);
                      }
                    }}
                  >
                    Use the automatic format instead
                  </Button>
                </>
              )}
            </div>
          </details>
        </Step>

        <details className="rounded-lg border border-slate-200 bg-white px-4 py-3 shadow-sm">
          <summary className="cursor-pointer text-sm font-semibold text-slate-800">Call limits (optional, the defaults are fine for most calls)</summary>
          <div className="mt-3 grid gap-3 md:grid-cols-4">
            <Field label="Longest call" hint="The call ends after this.">
              <Select value={minutes} onChange={(e) => limit("max_call_seconds", Number(e.target.value) * 60)}>
                {[...new Set([...CALL_MINUTES, minutes])]
                  .sort((a, b) => a - b)
                  .map((m) => (
                    <option key={m} value={m}>
                      {m} minute{m === 1 ? "" : "s"}
                    </option>
                  ))}
              </Select>
            </Field>
            <Field label="Wait for a reply (seconds)" hint="Before the assistant speaks again.">
              <Input type="number" min={2} max={60} value={config.limits.silence_timeout_seconds} onChange={(e) => limit("silence_timeout_seconds", Number(e.target.value))} />
            </Field>
            <Field label="Reminders if silent" hint="Then the assistant hangs up.">
              <Input type="number" min={0} max={5} value={config.limits.max_silence_prompts} onChange={(e) => limit("max_silence_prompts", Number(e.target.value))} />
            </Field>
            <Field label="Most replies per call" hint="Stops calls that go round in circles.">
              <Input type="number" min={4} max={200} value={config.limits.max_turns} onChange={(e) => limit("max_turns", Number(e.target.value))} />
            </Field>
          </div>
        </details>
      </fieldset>

      <div className="sticky bottom-0 z-10 mt-4 rounded-lg border border-slate-200 bg-white/95 px-4 py-3 shadow-md backdrop-blur">
        <div className="flex flex-wrap items-end gap-2">
          {editable && (
            <>
              <Button onClick={save} disabled={action.busy}>
                {versionId ? "Save draft" : "Create script"}
              </Button>
              {versionId &&
                (selfApprove ? (
                  <Button variant="secondary" onClick={publish} disabled={action.busy}>
                    Save and publish
                  </Button>
                ) : (
                  <Button variant="secondary" onClick={() => transition("submit")} disabled={action.busy}>
                    Save and send for approval
                  </Button>
                ))}
              <span className="text-xs text-slate-500">
                {!versionId
                  ? "Saved as a draft first. You can change it before publishing."
                  : selfApprove
                    ? "Publishing makes the script available to campaigns. After that it cannot be changed, only copied to a new version."
                    : "A colleague must approve the script before a campaign can use it."}
              </span>
            </>
          )}
          {status === "pending_approval" && can("scripts:approve") && (
            <>
              {!selfApprove && (
                <Field label="Comments" className="min-w-64 flex-1">
                  <Input value={comments} onChange={(e) => setComments(e.target.value)} />
                </Field>
              )}
              <Button onClick={() => transition("approve")} disabled={action.busy}>
                {selfApprove ? "Publish" : "Approve and publish"}
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
      </div>
    </>
  );
}

function Step({ n, title, help, actions, children }: { n: number; title: string; help?: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-slate-900 text-xs text-white">{n}</span>
          {title}
        </span>
      }
      actions={actions}
    >
      {help && <p className="mb-3 text-sm text-slate-500">{help}</p>}
      {children}
    </Card>
  );
}

function ContextFieldsEditor({ fields, onChange }: { fields: ContextField[]; onChange: (f: ContextField[]) => void }) {
  const set = (i: number, change: Partial<ContextField>) => onChange(fields.map((f, j) => (i === j ? { ...f, ...change } : f)));
  const rename = (i: number, label: string) => {
    const base = slug(label);
    let key = base;
    for (let n = 2; key && fields.some((f, j) => j !== i && f.key === key); n++) key = `${base}_${n}`;
    set(i, { label, key: key || fields[i].key });
  };
  return (
    <Step
      n={4}
      title="Information from your upload (optional)"
      help="Details that are different for each person and come from the Excel/CSV file you upload for a campaign, e.g. PO number or due date. The assistant can then mention them on the call."
      actions={
        <Button variant="secondary" onClick={() => onChange([...fields, { key: "", label: "", type: "string", required: true }])}>
          + Add field
        </Button>
      }
    >
      {fields.length === 0 && <p className="text-sm text-slate-500">None. Add a field only if the call needs details from the upload.</p>}
      <div className="space-y-2">
        {fields.map((f, i) => (
          <div key={i} className="grid items-end gap-2 md:grid-cols-[2fr_10rem_auto_auto]">
            <Field label="Field name">
              <Input value={f.label} onChange={(e) => rename(i, e.target.value)} placeholder="e.g. PO Number" />
            </Field>
            <Field label="Kind">
              <Select value={f.type} onChange={(e) => set(i, { type: e.target.value as ContextField["type"] })}>
                <option value="string">Text</option>
                <option value="number">Number</option>
                <option value="date">Date</option>
              </Select>
            </Field>
            <label className="flex items-center gap-1 pb-2 text-sm">
              <input type="checkbox" checked={f.required} onChange={(e) => set(i, { required: e.target.checked })} /> Must be in the upload
            </label>
            <Button variant="ghost" onClick={() => onChange(fields.filter((_, j) => j !== i))}>
              Remove
            </Button>
          </div>
        ))}
      </div>
    </Step>
  );
}

const QUESTION_TYPES: Record<QuestionType, string> = { yes_no: "Yes or no", text: "In their own words", date: "A date", number: "A number", choice: "One of a few options" };

const nextId = (questions: Question[]) => {
  let n = questions.length + 1;
  while (questions.some((q) => q.id === `q${n}`)) n++;
  return `q${n}`;
};

const short = (text: string) => (text.length > 50 ? `${text.slice(0, 50)}...` : text);

function QuestionsEditor({
  questions,
  contextFields,
  editable,
  onChange,
}: {
  questions: Question[];
  contextFields: ContextField[];
  editable: boolean;
  onChange: (q: Question[]) => void;
}) {
  const set = (i: number, change: Partial<Question>) => onChange(questions.map((q, j) => (i === j ? { ...q, ...change } : q)));
  const move = (i: number, by: number) => {
    const next = [...questions];
    [next[i], next[i + by]] = [next[i + by], next[i]];
    // A question can only depend on an earlier one.
    onChange(next.map((q, j) => (q.condition && !next.slice(0, j).some((p) => p.id === q.condition!.question_id) ? { ...q, condition: null } : q)));
  };
  const remove = (i: number) => {
    const gone = questions[i].id;
    onChange(questions.filter((_, j) => j !== i).map((q) => (q.condition?.question_id === gone ? { ...q, condition: null } : q)));
  };
  const add = () => onChange([...questions, { id: nextId(questions), prompt: "", type: "text", required: true }]);
  const dateFields = contextFields.filter((f) => f.type === "date");

  return (
    <Step
      n={5}
      title="Questions to ask"
      help="The assistant asks these in order and writes down the answers. Write each question the way you would say it."
      actions={
        <Button variant="secondary" onClick={add}>
          + Add question
        </Button>
      }
    >
      <div className="space-y-4">
        {questions.map((q, i) => {
          const earlier = questions.slice(0, i);
          const parent = earlier.find((p) => p.id === q.condition?.question_id);
          return (
            <div key={i} className="rounded-md border border-slate-200 p-3">
              <div className="mb-2 flex items-center gap-2">
                <span className="text-sm font-semibold text-slate-700">Question {i + 1}</span>
                <span className="flex-1" />
                <Button variant="ghost" disabled={i === 0} onClick={() => move(i, -1)} title="Move up">
                  ↑
                </Button>
                <Button variant="ghost" disabled={i === questions.length - 1} onClick={() => move(i, 1)} title="Move down">
                  ↓
                </Button>
                <Button variant="ghost" disabled={questions.length === 1} onClick={() => remove(i)}>
                  Remove
                </Button>
              </div>
              <div className="grid gap-2 md:grid-cols-[1fr_13rem]">
                <div>
                  <Field label="What to ask">
                    <Input value={q.prompt} onChange={(e) => set(i, { prompt: e.target.value })} placeholder="e.g. Will the material be delivered on time?" />
                  </Field>
                  {editable && <InsertChips fields={contextFields} onInsert={(t) => set(i, { prompt: append(q.prompt, t) })} />}
                </div>
                <Field label="Expected answer">
                  <Select value={q.type} onChange={(e) => set(i, { type: e.target.value as QuestionType, choices: e.target.value === "choice" ? (q.choices ?? []) : null })}>
                    {Object.entries(QUESTION_TYPES).map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              {q.type === "choice" && (
                <Field label="Possible answers" hint="Separate with commas." className="mt-2">
                  <Input value={(q.choices ?? []).join(", ")} onChange={(e) => set(i, { choices: e.target.value.split(",").map((c) => c.trim()).filter(Boolean) })} placeholder="e.g. On time, Delayed, Already delivered" />
                </Field>
              )}
              <div className="mt-2 grid gap-2 md:grid-cols-2">
                <Field label="When to ask">
                  <Select value={q.condition?.question_id ?? ""} onChange={(e) => {
                    const p = earlier.find((x) => x.id === e.target.value);
                    set(i, { condition: p ? { question_id: p.id, equals: p.type === "choice" ? (p.choices?.[0] ?? "") : true } : null });
                  }}>
                    <option value="">Always</option>
                    {earlier.map((p) => (
                      <option key={p.id} value={p.id}>
                        Only after question {questions.indexOf(p) + 1}{p.prompt ? ` (${short(p.prompt)})` : ""}
                      </option>
                    ))}
                  </Select>
                </Field>
                {q.condition && (
                  <Field label={`...if the answer to question ${questions.indexOf(parent!) + 1} was`}>
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
              </div>
              <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
                <label className="flex items-center gap-1">
                  <input type="checkbox" checked={q.required} onChange={(e) => set(i, { required: e.target.checked })} /> Must get an answer
                </label>
                {contextFields.length > 0 && (
                  <label className="flex items-center gap-1" title="Use when one call covers several rows of the upload, e.g. several PO lines for the same supplier.">
                    <input
                      type="checkbox"
                      checked={isPerItem(q)}
                      onChange={(e) => {
                        const name = (q.maps_to ?? "").replace(ITEMS, "") || q.id;
                        set(i, { maps_to: e.target.checked ? `${ITEMS}${name}` : q.maps_to?.startsWith(ITEMS) ? name : q.maps_to });
                      }}
                    />
                    Ask for each item in the upload (e.g. each PO line)
                  </label>
                )}
              </div>
              {q.type === "date" && dateFields.length > 0 && (
                <Field label="The date must not be earlier than" className="mt-2 md:w-1/2">
                  <Select value={q.validation?.not_before_context_field ?? ""} onChange={(e) => set(i, { validation: e.target.value ? { ...q.validation, not_before_context_field: e.target.value } : null })}>
                    <option value="">No check</option>
                    {dateFields.map((f) => (
                      <option key={f.key} value={f.key}>
                        {f.label}
                      </option>
                    ))}
                  </Select>
                </Field>
              )}
            </div>
          );
        })}
      </div>
    </Step>
  );
}
