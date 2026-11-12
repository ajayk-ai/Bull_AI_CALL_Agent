import { useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { DepartmentPicker } from "../components/DepartmentPicker";
import { Badge, Button, ErrorBox, ExampleSheet, Field, Icon, Input, Loading, Notice, PageHeader, Select, Step, Table, Td } from "../components/ui";
import { api, download } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction, useApi } from "../lib/hooks";
import { initialChoices, toMapping, type ColumnChoice, type ColumnRole } from "../lib/mapping";
import type { Campaign, ContextField, ImportReport, ImportUpload, ScriptVersion } from "../lib/types";

const ROLE_LABELS: Record<ColumnRole, string> = {
  ignore: "Don't use",
  name: "Person's name",
  phone: "Phone number",
  company: "Company",
  language: "Language",
  contact_field: "Keep on the contact",
  campaign_field: "Use in this campaign's calls",
};

const ROLE_HELP: [string, string][] = [
  ["Person's name / Phone number", "Required. Who to call and how to greet them."],
  ["Company / Language", "Optional. Language can be e.g. Tamil, English or Hindi; otherwise the script's language is used."],
  ["Use in this campaign's calls", "Details the AI talks about, e.g. PO number or due date. One per row."],
  ["Keep on the contact", "Extra details saved with the person for later, e.g. city or GST number."],
  ["Don't use", "The column is skipped."],
];

// ---- Example file, built from the script's upload fields ----

const SAMPLE_PEOPLE = [
  ["Ravi Kumar", "9876543210", "Sri Balaji Steels"],
  ["Ravi Kumar", "9876543210", "Sri Balaji Steels"],
  ["Lakshmi N", "9123456780", "KMR Castings"],
];
const SAMPLE_SOLO = [
  ["Ravi Kumar", "9876543210", "Sri Balaji Steels"],
  ["Lakshmi N", "9123456780", "KMR Castings"],
  ["Arun Prakash", "+91 98400 12345", "Vel Engineering"],
];

function sampleValue(f: ContextField, i: number): string {
  const text = `${f.key} ${f.label}`.toLowerCase();
  if (f.type === "date") return ["2026-11-20", "2026-11-25", "2026-11-22"][i];
  if (f.type === "number") return ["120", "45", "300"][i];
  if (/\bpo\b|purchase/.test(text)) return ["PO-1021", "PO-1034", "PO-1040"][i];
  if (/item|material|part|product/.test(text)) return ["MS Plate 10mm", "Bearing 6205", "Gear housing"][i];
  if (/qty|quantity/.test(text)) return ["120", "45", "300"][i];
  return [`Example ${i + 1}`, `Example ${i + 2}`, `Example ${i + 3}`][i];
}

function sampleSheet(fields: ContextField[]) {
  const people = fields.length ? SAMPLE_PEOPLE : SAMPLE_SOLO;
  return {
    headers: ["Contact Name", "Mobile", "Company", ...fields.map((f) => f.label)],
    rows: people.map((p, i) => [...p, ...fields.map((f) => sampleValue(f, i))]),
  };
}

function downloadCsv(name: string, headers: string[], rows: string[][]) {
  const cell = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  const text = [headers, ...rows].map((r) => r.map(cell).join(",")).join("\r\n");
  // The byte-order mark makes Excel open the file as UTF-8.
  const url = URL.createObjectURL(new Blob(["\ufeff" + text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

const fileSize = (bytes: number) => (bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`);

export function ImportWizardPage() {
  const [params] = useSearchParams();
  const campaignId = params.get("campaign");
  const campaign = useApi<Campaign>(campaignId ? `/campaigns/${campaignId}` : null);
  const version = useApi<ScriptVersion>(campaign.data?.script_version_id ? `/script-versions/${campaign.data.script_version_id}` : null);
  const [upload, setUpload] = useState<ImportUpload | null>(null);
  // The column suggestions use the script's fields, so wait for them before starting.
  const ready = !campaignId || (campaign.data !== null && (!campaign.data.script_version_id || version.data !== null));

  return (
    <>
      <PageHeader
        title={campaign.data ? `Upload contacts to "${campaign.data.name}"` : "Upload contacts"}
        subtitle="Add the people to call from an Excel or CSV file. Four steps: prepare, choose, match, import."
      />
      <ErrorBox error={campaign.error || version.error} />
      {!ready ? (
        <Loading />
      ) : !upload ? (
        <UploadStep campaign={campaign.data} contextFields={version.data?.config.context_fields ?? []} onUploaded={setUpload} />
      ) : (
        <div className="space-y-5">
          <Step n={1} done title="Prepare your file">
            <p className="text-sm text-slate-600">Done.</p>
          </Step>
          <Step
            n={2}
            done
            title="Choose the file"
            actions={
              <Button variant="ghost" onClick={() => setUpload(null)}>
                Choose another file
              </Button>
            }
          >
            <p className="flex items-center gap-2 text-sm text-slate-700">
              <Icon name="upload" className="h-4 w-4 text-slate-400" />
              <span className="font-medium">{upload.file_name}</span>
              <span className="text-slate-500">· {upload.total_rows} rows</span>
            </p>
          </Step>
          <MappingStep upload={upload} campaign={campaign.data} contextFields={version.data?.config.context_fields ?? null} />
        </div>
      )}
    </>
  );
}

function UploadStep({ campaign, contextFields, onUploaded }: { campaign: Campaign | null; contextFields: ContextField[]; onUploaded: (u: ImportUpload) => void }) {
  const { me } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [department, setDepartment] = useState("");
  const { busy, error, run } = useAction();
  const input = useRef<HTMLInputElement>(null);
  const sample = sampleSheet(contextFields);
  const okType = (f: File) => /\.(csv|xlsx|xlsm)$/i.test(f.name);
  const wrongType = file && !okType(file);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!file || wrongType) return;
    const form = new FormData();
    form.append("file", file);
    const dept = campaign?.department_id ?? (me?.role === "admin" ? department : "");
    if (dept) form.append("department_id", dept);
    run(async () => onUploaded(await api.post<ImportUpload>("/imports", form)));
  };

  return (
    <div className="space-y-5">
      <Step n={1} title="Prepare your file" help="Any Excel or CSV works. Column names and order are up to you; you will match them in step 3.">
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_17rem]">
          <div className="min-w-0">
            <p className="mb-2 text-sm font-medium text-slate-700">A file that works looks like this:</p>
            <ExampleSheet
              headers={sample.headers}
              rows={sample.rows}
              highlight={["Contact Name", "Mobile", ...contextFields.filter((f) => f.required).map((f) => f.label)]}
              caption={
                contextFields.length > 0 ? (
                  <>
                    Columns marked * are needed. Ravi has two rows with the same number, so he gets <b>one call</b> that covers both rows.
                  </>
                ) : (
                  <>Columns marked * are needed. Each row is one person to call.</>
                )
              }
            />
            <Button variant="secondary" className="mt-3" onClick={() => downloadCsv(campaign ? `${campaign.name} - sample.csv` : "contacts - sample.csv", sample.headers, sample.rows)}>
              <Icon name="download" />
              Download this sample
            </Button>
          </div>
          <ul className="space-y-2.5 text-sm text-slate-600">
            {[
              <>
                <b className="text-slate-800">First row = column names</b>, like "Name" and "Mobile".
              </>,
              <>
                <b className="text-slate-800">A name and a phone number</b> on every row.
              </>,
              <>
                Phone numbers like <span className="font-mono text-xs">9876543210</span> or <span className="font-mono text-xs">+91 98765 43210</span>.
              </>,
              <>
                Save as <b className="text-slate-800">.xlsx</b> or <b className="text-slate-800">.csv</b> (not the old .xls).
              </>,
              <>Up to 10,000 rows and 10 MB.</>,
            ].map((item, i) => (
              <li key={i} className="flex gap-2">
                <Icon name="check" className="mt-0.5 h-4 w-4 text-emerald-500" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>
      </Step>

      <Step n={2} title="Choose the file" help="Nothing is saved yet. You will see the columns and check the rows first.">
        <ErrorBox error={error} />
        <form onSubmit={submit} className="space-y-4">
          {!campaign && <DepartmentPicker value={department} onChange={setDepartment} />}
          <div
            role="button"
            tabIndex={0}
            onClick={() => input.current?.click()}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && input.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              const dropped = e.dataTransfer.files?.[0];
              if (dropped) setFile(dropped);
            }}
            className={`flex cursor-pointer flex-col items-center rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${
              dragging ? "border-brand-500 bg-brand-50" : file ? "border-emerald-300 bg-emerald-50/50" : "border-slate-300 hover:border-slate-400 hover:bg-slate-50"
            }`}
          >
            <span className={`flex h-11 w-11 items-center justify-center rounded-full ${file ? "bg-emerald-100 text-emerald-600" : "bg-slate-100 text-slate-500"}`}>
              <Icon name={file ? "check" : "upload"} className="h-5 w-5" />
            </span>
            {file ? (
              <>
                <p className="mt-3 text-sm font-semibold text-slate-900">{file.name}</p>
                <p className="mt-0.5 text-xs text-slate-500">{fileSize(file.size)} · click to choose a different file</p>
              </>
            ) : (
              <>
                <p className="mt-3 text-sm font-semibold text-slate-900">Drop your Excel or CSV file here</p>
                <p className="mt-0.5 text-xs text-slate-500">or click to browse · .xlsx or .csv, up to 10 MB</p>
              </>
            )}
            <input ref={input} type="file" accept=".csv,.xlsx,.xlsm" className="hidden" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
          {wrongType && <Notice>This file type can't be read. Open it in Excel and use "Save as" → Excel Workbook (.xlsx) or CSV.</Notice>}
          <div className="flex justify-end">
            <Button type="submit" disabled={!file || !!wrongType || busy}>
              {busy ? "Reading the file..." : "Upload and continue"}
            </Button>
          </div>
        </form>
      </Step>
    </div>
  );
}

function MappingStep({ upload, campaign, contextFields }: { upload: ImportUpload; campaign: Campaign | null; contextFields: ScriptVersion["config"]["context_fields"] | null }) {
  const navigate = useNavigate();
  const [choices, setChoices] = useState<Record<string, ColumnChoice>>(() => initialChoices(upload.headers, upload.suggested_mapping, contextFields));
  const [duplicatePolicy, setDuplicatePolicy] = useState<"skip" | "update">("skip");
  const [skipInvalid, setSkipInvalid] = useState(false);
  const [report, setReport] = useState<ImportReport | null>(null);
  const { busy, error, run } = useAction();
  const { mapping, problems } = useMemo(() => toMapping(choices), [choices]);

  const roles: ColumnRole[] = campaign
    ? ["ignore", "name", "phone", "company", "language", "contact_field", "campaign_field"]
    : ["ignore", "name", "phone", "company", "language", "contact_field"];

  const missingContext = (contextFields ?? []).filter((f) => f.required && !Object.keys(mapping.campaign_fields ?? {}).includes(f.key));

  const setChoice = (header: string, change: Partial<ColumnChoice>) => {
    setReport(null);
    setChoices({ ...choices, [header]: { ...choices[header], ...change } });
  };

  const process = (dryRun: boolean) =>
    run(async () => {
      const result = await api.post<ImportReport>(`/imports/${upload.id}/process`, {
        mapping,
        campaign_id: campaign?.id ?? null,
        duplicate_policy: duplicatePolicy,
        skip_invalid_rows: skipInvalid,
        dry_run: dryRun,
      });
      setReport(result);
    });

  const finished = report && !report.dry_run;

  return (
    <>
      <ErrorBox error={error} />
      <Step
        n={3}
        done={problems.length === 0 && missingContext.length === 0}
        title="Match your columns"
        help="We guessed what each column is. Check the 'Use as' column and fix anything that looks wrong."
      >
        <details className="mb-4 rounded-lg bg-slate-50 px-4 py-3 text-sm ring-1 ring-slate-200">
          <summary className="cursor-pointer font-medium text-slate-700">What do the options mean?</summary>
          <dl className="mt-2 grid gap-x-4 gap-y-1.5 sm:grid-cols-[14rem_1fr]">
            {ROLE_HELP.map(([term, text]) => (
              <div key={term} className="contents">
                <dt className="font-medium text-slate-800">{term}</dt>
                <dd className="text-slate-600">{text}</dd>
              </div>
            ))}
          </dl>
        </details>
        {campaign && (
          <Notice tone="blue">
            Rows with the same phone number become one contact in the campaign, with one item per row (for example, one per PO).
            {contextFields && contextFields.length > 0 && (
              <> The script needs these campaign fields: {contextFields.map((f) => `${f.label} (${f.key})`).join(", ")}.</>
            )}
          </Notice>
        )}
        <Table headers={["Column in your file", "Use as", "Saved as", "First values in your file"]}>
          {upload.headers.map((header) => (
            <tr key={header}>
              <Td className="font-medium">{header}</Td>
              <Td>
                <Select value={choices[header].role} onChange={(e) => setChoice(header, { role: e.target.value as ColumnRole })} disabled={!!finished}>
                  {roles.map((r) => (
                    <option key={r} value={r}>
                      {ROLE_LABELS[r]}
                    </option>
                  ))}
                </Select>
              </Td>
              <Td>
                {(choices[header].role === "contact_field" || choices[header].role === "campaign_field") && (
                  <Input value={choices[header].key} onChange={(e) => setChoice(header, { key: e.target.value })} disabled={!!finished} />
                )}
              </Td>
              <Td className="text-xs text-slate-600">
                {upload.preview
                  .map((row) => row[header])
                  .filter(Boolean)
                  .slice(0, 3)
                  .join(" · ") || "-"}
              </Td>
            </tr>
          ))}
        </Table>
        {(problems.length > 0 || missingContext.length > 0) && (
          <ul className="mt-3 list-disc pl-5 text-sm text-amber-800">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
            {missingContext.map((f) => (
              <li key={f.key}>
                No column is mapped to the required campaign field {f.label} ({f.key})
              </li>
            ))}
          </ul>
        )}
      </Step>

      <Step n={4} done={!!finished} title="Check and import" help="First press 'Check file': it finds problems without saving anything. Then press 'Import'.">
        <div className="mb-4 grid gap-3 md:grid-cols-2">
          <Field label="If a number already exists in the department">
            <Select value={duplicatePolicy} onChange={(e) => setDuplicatePolicy(e.target.value as "skip" | "update")} disabled={!!finished}>
              <option value="skip">Keep the existing contact unchanged</option>
              <option value="update">Update name, company, language and fields</option>
            </Select>
          </Field>
          <Field label="If some rows have errors">
            <Select value={skipInvalid ? "skip" : "stop"} onChange={(e) => setSkipInvalid(e.target.value === "skip")} disabled={!!finished}>
              <option value="stop">Import nothing until the file is fixed</option>
              <option value="skip">Import the valid rows, list the others</option>
            </Select>
          </Field>
        </div>
        {!finished && (
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => process(true)} disabled={busy || problems.length > 0}>
              Check file
            </Button>
            <Button onClick={() => process(false)} disabled={busy || problems.length > 0 || !report || report.status !== "uploaded"}>
              Import
            </Button>
            <span className="self-center text-xs text-slate-500">{report?.dry_run ? "Looks right? Press Import." : "Nothing is saved by a check."}</span>
          </div>
        )}
        {report && <ReportView report={report} />}
        {finished && (
          <div className="mt-4 flex gap-2">
            {report.errors.length + report.warnings.length > 0 && (
              <Button variant="secondary" onClick={() => download(`/imports/${report.id}/errors.csv`, "errors.csv")}>
                Download problem list
              </Button>
            )}
            <Button onClick={() => navigate(campaign ? `/campaigns/${campaign.id}` : "/contacts")}>{campaign ? "Back to campaign" : "Go to contacts"}</Button>
            <Link to="/imports">
              <Button variant="ghost">Upload history</Button>
            </Link>
          </div>
        )}
      </Step>
    </>
  );
}

function ReportView({ report }: { report: ImportReport }) {
  const blocked = report.error_rows > 0 && report.status !== "completed";
  return (
    <div className="mt-4">
      {report.dry_run ? (
        <Notice tone={report.error_rows ? "amber" : "green"}>
          Check complete: {report.valid_rows} of {report.total_rows} rows are valid
          {report.error_rows > 0 && `, ${report.error_rows} have errors`}
          {report.duplicate_rows > 0 && `, ${report.duplicate_rows} match existing contacts`}. Nothing has been saved yet.
        </Notice>
      ) : blocked ? (
        <Notice>Import stopped: {report.error_rows} rows have errors and nothing was saved. Fix the file and upload it again.</Notice>
      ) : (
        <Notice tone="green">
          Imported: {report.new_contacts} new contacts, {report.updated_contacts} updated
          {report.campaign_contacts > 0 && `, ${report.campaign_contacts} added to the campaign`}
          {report.error_rows > 0 && `; ${report.error_rows} rows skipped`}.
        </Notice>
      )}
      {(report.errors.length > 0 || report.warnings.length > 0) && (
        <Table headers={["Row", "", "Column", "Problem"]}>
          {[...report.errors, ...report.warnings]
            .sort((a, b) => a.row - b.row)
            .slice(0, 200)
            .map((issue, i) => (
              <tr key={i}>
                <Td>{issue.row}</Td>
                <Td>{issue.level === "error" ? <Badge tone="red">error</Badge> : <Badge tone="amber">warning</Badge>}</Td>
                <Td>{issue.field ?? "-"}</Td>
                <Td>{issue.message}</Td>
              </tr>
            ))}
        </Table>
      )}
    </div>
  );
}
