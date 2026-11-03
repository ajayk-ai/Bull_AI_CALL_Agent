import { useState } from "react";

import { Button, Card, ErrorBox, Input, Loading, PageHeader, Pager, Table, Td, formatDate } from "../components/ui";
import { query } from "../lib/api";
import { useApi } from "../lib/hooks";
import type { AuditEntry, Page } from "../lib/types";

const PAGE_SIZE = 50;

export function AuditPage() {
  const [action, setAction] = useState("");
  const [applied, setApplied] = useState("");
  const [page, setPage] = useState(1);
  const list = useApi<Page<AuditEntry>>(`/audit-logs${query({ action: applied, page, page_size: PAGE_SIZE })}`);

  return (
    <>
      <PageHeader title="Audit log" subtitle="Every change and sign-in. Phone numbers are never shown here." />
      <ErrorBox error={list.error} />
      <Card>
        <form
          className="mb-3 flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setPage(1);
            setApplied(action.trim());
          }}
        >
          <Input placeholder="Filter by action, e.g. contact.create or auth.login_failed" value={action} onChange={(e) => setAction(e.target.value)} />
          <Button type="submit" variant="secondary">
            Filter
          </Button>
        </form>
        {list.loading && !list.data ? (
          <Loading />
        ) : (
          <>
            <Table headers={["When", "Who", "Action", "Record", "Details"]} empty={list.data?.items.length === 0}>
              {list.data?.items.map((e) => (
                <tr key={e.id}>
                  <Td className="whitespace-nowrap">{formatDate(e.occurred_at, true)}</Td>
                  <Td>{e.actor_email ?? "-"}</Td>
                  <Td className="font-mono text-xs">{e.action}</Td>
                  <Td className="text-xs">{e.entity_type ?? "-"}</Td>
                  <Td className="max-w-md break-words font-mono text-xs text-slate-600">
                    {Object.keys(e.changes).length ? JSON.stringify(e.changes) : "-"}
                  </Td>
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
