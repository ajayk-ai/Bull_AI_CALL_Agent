import { useEffect, type ReactNode } from "react";
import { useParams } from "react-router";

import { Badge, Button, Card, ErrorBox, Loading, PageHeader, StatusBadge, formatDate } from "../components/ui";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction, useApi } from "../lib/hooks";
import type { CallDetail, CallStatus } from "../lib/types";

const ACTIVE: CallStatus[] = ["queued", "dialing", "ringing", "in_progress"];
const POLL_MS = 2000;

const END_REASONS: Record<string, string> = {
  agent_end_call: "The assistant closed the call",
  caller_hangup: "The person hung up",
  silence: "No response from the person",
  time_limit: "Time limit reached",
  turn_limit: "Conversation limit reached",
  hard_time_limit: "Maximum call length reached",
  no_answer: "Not answered",
  busy: "Line busy",
  hung_up_by_user: "Hung up from the app",
  provider_error: "The phone provider could not place the call",
  no_final_status: "No final status from the phone provider",
  error: "Technical error",
  engine_closed: "The voice engine closed the session",
};

export function CallDetailPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const call = useApi<CallDetail>(`/calls/${id}`);
  const action = useAction();
  const active = call.data ? ACTIVE.includes(call.data.status) : false;

  // While the call is live, refresh the transcript and status.
  const { reload } = call;
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(reload, POLL_MS);
    return () => window.clearInterval(timer);
  }, [active, reload]);

  if (!call.data) return call.error ? <ErrorBox error={call.error} /> : <Loading />;
  const c = call.data;
  const m = c.metrics;
  const avgReply = m.reply_ms?.length ? Math.round(m.reply_ms.reduce((a, b) => a + b, 0) / m.reply_ms.length) : null;

  const hangUp = () =>
    action.run(async () => {
      await api.post(`/calls/${c.id}/hang-up`);
      call.reload();
    });

  return (
    <>
      <PageHeader
        title={c.contact_name ?? c.phone_masked}
        subtitle={`${c.phone_masked} · ${formatDate(c.created_at, true)}`}
        actions={
          <>
            {c.is_simulated && <Badge tone="blue">simulated</Badge>}
            <StatusBadge status={c.status} />
            {active && can("calls:place") && (
              <Button variant="danger" onClick={hangUp} disabled={action.busy}>
                Hang up
              </Button>
            )}
          </>
        }
      />
      <ErrorBox error={action.error} />
      {c.error && <ErrorBox error={new Error(c.error)} />}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card title={active ? "Transcript (live)" : "Transcript"} className="lg:col-span-2">
          {c.transcript.length === 0 ? (
            <p className="text-sm text-slate-500">{active ? "The transcript appears when the call ends." : "No conversation was recorded."}</p>
          ) : (
            <ol className="space-y-2">
              {c.transcript.map((t) => (
                <li key={t.turn_id} className={`flex ${t.speaker === "agent" ? "justify-start" : "justify-end"}`}>
                  <div className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${t.speaker === "agent" ? "bg-slate-100" : "bg-amber-50 ring-1 ring-amber-200"}`}>
                    <p className="mb-0.5 text-xs text-slate-500">
                      {t.speaker === "agent" ? "Assistant" : "Person"} · {(t.at_ms / 1000).toFixed(1)}s{t.interrupted && " · interrupted"}
                    </p>
                    <p className="whitespace-pre-wrap">{t.text}</p>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Card>

        <div className="space-y-4">
          <Card title="Result">
            <dl className="space-y-2 text-sm">
              <Row label="Outcome">{c.outcome?.replace(/_/g, " ") ?? "-"}</Row>
              {c.outcome_note && <Row label="Note">{c.outcome_note}</Row>}
              <Row label="How it ended">{c.end_reason ? (END_REASONS[c.end_reason] ?? c.end_reason) : "-"}</Row>
              <Row label="Length">{c.duration_seconds != null ? `${c.duration_seconds} s` : "-"}</Row>
              <Row label="Answered">{formatDate(c.answered_at, true)}</Row>
            </dl>
          </Card>
          <Card title="Conversation quality">
            <dl className="space-y-2 text-sm">
              <Row label="Turns">{m.turns ?? "-"}</Row>
              <Row label="Average reply time">{avgReply != null ? `${avgReply} ms` : "-"}</Row>
              <Row label="First audio">{m.first_audio_ms != null ? `${m.first_audio_ms} ms` : "-"}</Row>
              <Row label="Interruptions">{m.interruptions ?? "-"}</Row>
              <Row label="Silence prompts">{m.silence_prompts ?? "-"}</Row>
            </dl>
          </Card>
          <Card title="Set-up">
            <dl className="space-y-2 text-sm">
              <Row label="Language">{c.ai_config.language ?? "-"}</Row>
              <Row label="Voice">{`${c.ai_config.model ?? c.ai_config.engine ?? "-"} · ${c.ai_config.voice ?? "-"}`}</Row>
              <Row label="Phone line">{c.provider}</Row>
              {(c.context.items ?? []).length > 0 && (
                <Row label="Call data">
                  {(c.context.items ?? []).map((item, i) => (
                    <p key={i} className="text-xs">
                      {Object.values(item).join(" · ")}
                    </p>
                  ))}
                </Row>
              )}
            </dl>
          </Card>
          <Card title={`Provider events (${c.events.length})`}>
            <ul className="space-y-1 text-xs">
              {c.events.map((e, i) => (
                <li key={i} className="flex justify-between gap-2">
                  <span className="font-mono">{e.event_type}</span>
                  <span className="text-slate-500">{formatDate(e.received_at, true)}</span>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  );
}
