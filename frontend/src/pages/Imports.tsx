import { useState } from "react";
import { Link } from "react-router";

import { Button, Card, ErrorBox, Loading, PageHeader, Pager, StatusBadge, Table, Td, formatDate } from "../components/ui";
import { download, query } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useAction, useApi } from "../lib/hooks";
import type { ImportRecord, Page } from "../lib/types";

const PAGE_SIZE = 50;

export function ImportsPage() {
  const { can } = useAuth();
  const [page, setPage] = useState(1);
  const list = useApi<Page<ImportRecord>>(`/imports${query({ page, page_size: PAGE_SIZE })}`);
  const action = useAction();

  return (
    <>
      <PageHeader
        title="Uploads"
        subtitle="History of contact files uploaded in your department."
        actions={
          can("imports:write") && (
            <Link to="/imports/new">
              <Button>Upload file</Button>
            </Link>
          )
        }
      />
      <ErrorBox error={list.error || action.error} />
      <Card>
        {list.loading && !list.data ? (
          <Loading />
        ) : (
          <>
            <Table headers={["File", "Uploaded", "Status", "Rows", "Errors", "New contacts", "To campaign", ""]} empty={list.data?.items.length === 0}>
              {list.data?.items.map((r) => (
                <tr key={r.id}>
                  <Td>{r.file_name}</Td>
                  <Td>{formatDate(r.created_at, true)}</Td>
                  <Td>
                    <StatusBadge status={r.status} />
                  </Td>
                  <Td>{r.total_rows}</Td>
                  <Td>{r.error_rows}</Td>
                  <Td>{r.new_contacts}</Td>
                  <Td>{r.campaign_id ? <Link className="text-sky-700 hover:underline" to={`/campaigns/${r.campaign_id}`}>{r.campaign_contacts}</Link> : "-"}</Td>
                  <Td className="text-right">
                    {r.error_rows > 0 && (
                      <Button variant="ghost" onClick={() => action.run(() => download(`/imports/${r.id}/errors.csv`, "errors.csv"))}>
                        Problems
                      </Button>
                    )}
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
