// Shapes returned by the backend (see /api/v1/docs).

export type Role = "admin" | "user";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Me {
  id: string;
  username: string;
  email: string | null;
  full_name: string;
  role: Role;
  department_id: string | null;
  must_change_password: boolean;
  permissions: string[];
}

export interface Department {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
}

export interface User {
  id: string;
  username: string;
  email: string | null;
  full_name: string;
  role: Role;
  department_id: string | null;
  is_active: boolean;
  must_change_password: boolean;
  locked: boolean;
  last_login_at: string | null;
  created_at: string;
}

export interface UserCredentials {
  user: User;
  temporary_password: string;
}

export interface Contact {
  id: string;
  department_id: string;
  name: string;
  company: string | null;
  phone_masked: string;
  language: string | null;
  custom_fields: Record<string, string | number | boolean | null>;
  do_not_call: boolean;
  created_at: string;
}

export interface DncEntry {
  id: string;
  phone_masked: string;
  department_id: string | null;
  reason: string;
  source: string;
  expires_at: string | null;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  occurred_at: string;
  actor_email: string | null;
  action: string;
  entity_type: string | null;
  entity_id: string | null;
  changes: Record<string, unknown>;
}

export type VersionStatus = "draft" | "pending_approval" | "published" | "retired";

export interface ScriptVersionSummary {
  id: string;
  version_no: number;
  status: VersionStatus;
  published_at: string | null;
  created_at: string;
}

export interface Script {
  id: string;
  department_id: string;
  name: string;
  description: string | null;
  is_archived: boolean;
  versions: ScriptVersionSummary[];
}

export interface ContextField {
  key: string;
  label: string;
  type: "string" | "number" | "date";
  required: boolean;
}

export type QuestionType = "yes_no" | "text" | "date" | "number" | "choice";

export interface Question {
  id: string;
  prompt: string;
  type: QuestionType;
  required: boolean;
  choices?: string[] | null;
  condition?: { question_id: string; equals: string | boolean | number } | null;
  validation?: { not_before_context_field?: string | null; min?: number | null; max?: number | null; pattern?: string | null } | null;
  maps_to?: string | null;
}

export interface ScriptConfig {
  objective: string;
  agent: { name: string; organisation: string; introduction: string };
  system_instructions: string;
  languages: { default: string; allowed: string[]; auto_detect: boolean; allow_switching: boolean };
  voice: { provider: string; voice_name: string };
  context_fields: ContextField[];
  questions: Question[];
  business_rules: string[];
  limits: { max_call_seconds: number; silence_timeout_seconds: number; max_silence_prompts: number; max_turns: number };
  closing: { confirm_before_close: boolean; statement: string };
  escalation: { human_transfer_enabled: boolean; triggers: string[]; message: string | null };
}

export interface ScriptVersion {
  id: string;
  script_id: string;
  version_no: number;
  status: VersionStatus;
  config: ScriptConfig;
  extraction_schema: Record<string, unknown>;
  approved_by_id: string | null;
  approved_at: string | null;
  published_at: string | null;
  created_at: string;
}

export type CampaignStatus = "draft" | "pending_approval" | "approved" | "running" | "paused" | "completed" | "cancelled";

export interface CallingWindow {
  timezone: string;
  days: number[];
  start: string;
  end: string;
}

export interface Campaign {
  id: string;
  department_id: string;
  name: string;
  description: string | null;
  owner_id: string;
  script_version_id: string | null;
  status: CampaignStatus;
  language: string | null;
  start_date: string | null;
  end_date: string | null;
  calling_window: CallingWindow;
  max_concurrency: number;
  max_attempts: number;
  retry_interval_minutes: number;
  contact_count: number;
  created_at: string;
}

export interface CampaignContact {
  id: string;
  contact_id: string;
  contact_name: string;
  company: string | null;
  phone_masked: string;
  do_not_call: boolean;
  status: string;
  attempts: number;
  context: { items?: Record<string, string>[] };
}

export interface Approval {
  id: string;
  decision: "pending" | "approved" | "rejected";
  requested_by_id: string;
  decided_by_id: string | null;
  comments: string | null;
  requested_at: string;
  decided_at: string | null;
}

export interface ColumnMapping {
  name: string;
  phone: string;
  company?: string | null;
  language?: string | null;
  contact_fields: Record<string, string>;
  campaign_fields: Record<string, string>;
}

export interface ImportUpload {
  id: string;
  file_name: string;
  headers: string[];
  total_rows: number;
  preview: Record<string, string>[];
  suggested_mapping: ColumnMapping | null;
}

export interface RowIssue {
  row: number;
  field: string | null;
  message: string;
  level: "error" | "warning";
}

export interface ImportReport {
  id: string;
  status: "uploaded" | "validating" | "completed" | "failed";
  dry_run: boolean;
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  duplicate_rows: number;
  new_contacts: number;
  updated_contacts: number;
  campaign_contacts: number;
  errors: RowIssue[];
  warnings: RowIssue[];
}

export interface ImportRecord {
  id: string;
  campaign_id: string | null;
  file_name: string;
  status: ImportReport["status"];
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  new_contacts: number;
  campaign_contacts: number;
  created_at: string;
}

export type CallStatus = "queued" | "dialing" | "ringing" | "in_progress" | "completed" | "no_answer" | "busy" | "failed" | "cancelled";

export interface Call {
  id: string;
  department_id: string;
  campaign_id: string | null;
  contact_id: string | null;
  contact_name: string | null;
  phone_masked: string;
  script_version_id: string;
  provider: string;
  is_simulated: boolean;
  status: CallStatus;
  outcome: string | null;
  outcome_note: string | null;
  end_reason: string | null;
  started_at: string | null;
  answered_at: string | null;
  ended_at: string | null;
  duration_seconds: number | null;
  error: string | null;
  created_at: string;
}

export interface TranscriptTurn {
  turn_id: number;
  speaker: "agent" | "caller";
  text: string;
  at_ms: number;
  interrupted?: boolean;
}

export interface CallDetail extends Call {
  ai_config: Record<string, unknown> & { language?: string; model?: string; voice?: string; telephony?: string };
  context: { items?: Record<string, string>[] };
  metrics: {
    duration_seconds?: number;
    turns?: number;
    interruptions?: number;
    first_audio_ms?: number | null;
    reply_ms?: number[];
    silence_prompts?: number;
  };
  transcript: TranscriptTurn[];
  events: { event_type: string; payload: Record<string, unknown>; received_at: string }[];
  recordings: { id: string; bucket: string; created_at: string }[];
}
