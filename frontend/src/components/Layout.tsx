import { Link, NavLink, Outlet } from "react-router";

import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import type { Department } from "../lib/types";
import { ROLE_NAMES } from "./ui";

type NavItem = { to: string; label: string; permission?: string };

const WORK: NavItem[] = [
  { to: "/campaigns", label: "Campaigns", permission: "campaigns:read" },
  { to: "/calls", label: "Calls", permission: "calls:read" },
  { to: "/contacts", label: "Contacts", permission: "contacts:read" },
  { to: "/imports", label: "Uploads", permission: "contacts:read" },
  { to: "/scripts", label: "Scripts", permission: "scripts:read" },
  { to: "/dnc", label: "Do not call", permission: "dnc:read" },
];

const ADMIN: NavItem[] = [
  { to: "/users", label: "Users and access", permission: "users:read" },
  { to: "/departments", label: "Departments", permission: "departments:manage" },
  { to: "/audit", label: "Audit log", permission: "audit:read" },
];

function NavGroup({ items, title }: { items: NavItem[]; title?: string }) {
  const { can } = useAuth();
  const visible = items.filter((item) => !item.permission || can(item.permission));
  if (!visible.length) return null;
  return (
    <>
      {title && <p className="hidden px-3 pb-1 pt-4 text-xs font-medium uppercase tracking-wide text-slate-500 md:block">{title}</p>}
      {visible.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) => `whitespace-nowrap rounded-md px-3 py-2 text-sm ${isActive ? "bg-slate-700 text-white" : "hover:bg-slate-800"}`}
        >
          {item.label}
        </NavLink>
      ))}
    </>
  );
}

export function Layout() {
  const { me, signOut } = useAuth();
  const departments = useApi<Department[]>("/departments");
  const department = me?.department_id ? departments.data?.find((d) => d.id === me.department_id) : null;

  return (
    <div className="min-h-screen md:flex">
      <aside className="border-b border-slate-800 bg-slate-900 text-slate-200 md:min-h-screen md:w-56 md:shrink-0 md:border-b-0">
        <div className="px-4 py-4">
          <p className="text-base font-semibold text-white">
            <span className="text-brand-500">Bull</span> AI Calling
          </p>
          <p className="text-xs text-slate-400">Bull Machines · all departments</p>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-4">
          <NavGroup items={WORK} />
          <NavGroup items={ADMIN} title="Admin" />
        </nav>
      </aside>
      <div className="min-w-0 flex-1">
        <header className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1 border-b border-slate-200 bg-white px-4 py-2 text-sm">
          <span className="text-slate-700">
            {me?.full_name}{" "}
            <span className="text-slate-400">
              · {me?.username} · {me ? ROLE_NAMES[me.role] : ""}
              {department ? ` · ${department.code}` : me?.role === "admin" ? " · all departments" : ""}
            </span>
          </span>
          <Link to="/account/password" className="text-slate-500 hover:text-slate-900">
            Change password
          </Link>
          <button className="text-slate-500 hover:text-slate-900" onClick={signOut}>
            Sign out
          </button>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
