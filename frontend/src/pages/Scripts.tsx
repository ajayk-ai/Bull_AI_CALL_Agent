import { Link } from "react-router";

import { Button, Card, ErrorBox, Loading, PageHeader, StatusBadge, Table, Td, formatDate } from "../components/ui";
import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import type { Script } from "../lib/types";

export function ScriptsPage() {
  const { can } = useAuth();
  const list = useApi<Script[]>("/scripts");

  return (
    <>
      <PageHeader
        title="Scripts"
        subtitle="What the AI says and asks. Each change is a new version that must be approved before campaigns can use it."
        actions={
          can("scripts:write") && (
            <Link to="/scripts/new">
              <Button>New script</Button>
            </Link>
          )
        }
      />
      <ErrorBox error={list.error} />
      <Card>
        {list.loading && !list.data ? (
          <Loading />
        ) : (
          <Table headers={["Script", "Versions", "Current published", ""]} empty={list.data?.length === 0}>
            {list.data?.map((s) => {
              const published = s.versions.find((v) => v.status === "published");
              return (
                <tr key={s.id}>
                  <Td>
                    <p className="font-medium">{s.name}</p>
                    {s.description && <p className="text-xs text-slate-500">{s.description}</p>}
                  </Td>
                  <Td>
                    <div className="flex flex-wrap gap-1">
                      {s.versions.map((v) => (
                        <Link key={v.id} to={`/scripts/${s.id}/versions/${v.id}`} className="hover:opacity-75">
                          <span className="mr-1 text-xs text-slate-600">v{v.version_no}</span>
                          <StatusBadge status={v.status} />
                        </Link>
                      ))}
                    </div>
                  </Td>
                  <Td>{published ? `v${published.version_no} · ${formatDate(published.published_at)}` : "-"}</Td>
                  <Td className="text-right">
                    <Link to={`/scripts/${s.id}/versions/${s.versions[0].id}`}>
                      <Button variant="ghost">Open</Button>
                    </Link>
                  </Td>
                </tr>
              );
            })}
          </Table>
        )}
      </Card>
    </>
  );
}
