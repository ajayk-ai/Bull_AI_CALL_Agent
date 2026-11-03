import { useMemo, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import { DepartmentPicker } from "../components/DepartmentPicker";
import { Badge, Button, Card, ErrorBox, Field, Input, Loading, Notice, PageHeader, Select, Table, Td } from "../components/ui";
import { api, download } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction, useApi } from "../lib/hooks";
import { initialChoices, toMapping, type ColumnChoice, type ColumnRole } from "../lib/mapping";
import type { Campaign, ImportReport, ImportUpload, ScriptVersion } from "../lib/types";

const ROLE_LABELS: Record<ColumnRole, string> = {
  ignore: "Ignore",
  name: "Contact name",
  phone: "Phone number",
  company: "Company",
  language: "Language",
  contact_field: "Contact field",
  campaign_field: "Campaign field (per row)",
};

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
        subtitle="CSV or Excel (.xlsx). The first non-empty row must hold the column headers."
      />
      <ErrorBox error={campaign.error || version.error} />
      {!ready ? (
        <Loading />
      ) : !upload ? (
        <UploadStep campaign={campaign.data} onUploaded={setUpload} />
      ) : (
        <MappingStep upload={upload} campaign={campaign.data} contextFields={version.data?.config.context_fields ?? null} />
      )}
    </>
  );
}

function UploadStep({ campaign, onUploaded }: { campaign: Campaign | null; onUploaded: (u: ImportUpload) => void }) {
  const { me } = useAuth();
  const [file, setFile] = useState<File | null>(null);
  const [department, setDepartment] = useState("");
  const { busy, error, run } = useAction();

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    const dept = campaign?.department_id ?? (me?.role === "admin" ? department : "");
    if (dept) form.append("department_id", dept);
    run(async () => onUploaded(await api.post<ImportUpload>("/imports", form)));
  };

  return (
    <Card title="1. Choose file">
      <ErrorBox error={error} />
      <form onSubmit={submit} className="grid items-end gap-3 md:grid-cols-3">
        {!campaign && <DepartmentPicker value={department} onChange={setDepartment} />}
        <Field label="File" hint="Up to 10 MB and 10,000 rows">
          <Input type="file" accept=".csv,.xlsx,.xlsm" onChange={(e) => setFile(e.target.files?.[0] ?? null)} required />
        </Field>
        <Button type="submit" disabled={!file || busy}>
          {busy ? "Reading..." : "Upload"}
        </Button>
      </form>
    </Card>
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
      <Card title={`2. Match columns · ${upload.file_name} · ${upload.total_rows} rows`} className="mb-4">
        {campaign && (
          <Notice tone="blue">
            Rows with the same phone number become one contact in the campaign, with one item per row (for example, one per PO).
            {contextFields && contextFields.length > 0 && (
              <> The script needs these campaign fields: {contextFields.map((f) => `${f.label} (${f.key})`).join(", ")}.</>
            )}
          </Notice>
        )}
        <Table headers={["Column in file", "Use as", "Field key", "Example values"]}>
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
      </Card>

      <Card title="3. Check and import">
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
            <span className="self-center text-xs text-slate-500">Check the file first; nothing is saved by a check.</span>
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
      </Card>
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
