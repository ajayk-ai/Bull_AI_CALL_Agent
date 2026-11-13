import { Link, NavLink, Outlet } from "react-router";

import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import type { Department } from "../lib/types";
import { Avatar, Icon, ROLE_NAMES, type IconName } from "./ui";

type NavItem = { to: string; label: string; icon: IconName; permission?: string };

const WORK: NavItem[] = [
  { to: "/campaigns", label: "Campaigns", icon: "megaphone", permission: "campaigns:read" },
  { to: "/calls", label: "Calls", icon: "phone", permission: "calls:read" },
  { to: "/contacts", label: "Contacts", icon: "contacts", permission: "contacts:read" },
  { to: "/imports", label: "Uploads", icon: "upload", permission: "contacts:read" },
  { to: "/scripts", label: "Scripts", icon: "script", permission: "scripts:read" },
  { to: "/dnc", label: "Do not call", icon: "ban", permission: "dnc:read" },
  { to: "/integrations", label: "Connected apps", icon: "plug", permission: "integrations:manage" },
];

const ADMIN: NavItem[] = [
  { to: "/users", label: "Users and access", icon: "users", permission: "users:read" },
  { to: "/departments", label: "Departments", icon: "building", permission: "departments:manage" },
  { to: "/audit", label: "Audit log", icon: "log", permission: "audit:read" },
];

function NavGroup({ items, title }: { items: NavItem[]; title?: string }) {
  const { can } = useAuth();
  const visible = items.filter((item) => !item.permission || can(item.permission));
  if (!visible.length) return null;
  return (
    <>
      {title && <p className="hidden px-3 pb-1.5 pt-5 text-[11px] font-semibold uppercase tracking-wider text-slate-500 md:block">{title}</p>}
      {visible.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          className={({ isActive }) =>
            `group flex items-center gap-2.5 whitespace-nowrap rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              isActive ? "bg-white/10 text-white" : "text-slate-400 hover:bg-white/5 hover:text-slate-100"
            }`
          }
        >
          {({ isActive }) => (
            <>
              <Icon name={item.icon} className={`h-[18px] w-[18px] ${isActive ? "text-brand-500" : "text-slate-500 group-hover:text-slate-300"}`} />
              {item.label}
            </>
          )}
        </NavLink>
      ))}
    </>
  );
}

export function Layout() {
  const { me, signOut } = useAuth();
  const departments = useApi<Department[]>("/departments");
  const department = me?.department_id ? departments.data?.find((d) => d.id === me.department_id) : null;
  const scope = department ? department.code : me?.role === "admin" ? "All departments" : "";

  return (
    <div className="min-h-screen md:flex">
      <aside className="bg-slate-950 text-slate-200 md:sticky md:top-0 md:flex md:h-screen md:w-60 md:shrink-0 md:flex-col">
        <div className="flex items-center gap-2.5 px-4 py-4 md:px-5 md:py-5">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-500 text-sm font-bold text-slate-950">B</span>
          <div className="leading-tight">
            <p className="text-sm font-semibold text-white">Bull AI Calling</p>
            <p className="text-[11px] text-slate-500">Bull Machines</p>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-1 md:flex-col md:overflow-y-auto md:px-3 md:pb-4">
          <NavGroup items={WORK} />
          <NavGroup items={ADMIN} title="Admin" />
        </nav>
        {me && (
          <div className="hidden border-t border-white/10 p-3 md:block">
            <div className="flex items-center gap-2.5 rounded-lg px-2 py-2">
              <Avatar name={me.full_name} size="sm" />
              <div className="min-w-0 flex-1 leading-tight">
                <p className="truncate text-sm font-medium text-white">{me.full_name}</p>
                <p className="truncate text-[11px] text-slate-500">
                  {ROLE_NAMES[me.role]}
                  {scope && ` · ${scope}`}
                </p>
              </div>
            </div>
            <div className="mt-1 grid grid-cols-2 gap-1">
              <Link to="/account/password" className="flex items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-slate-400 hover:bg-white/5 hover:text-white">
                <Icon name="key" className="h-3.5 w-3.5" />
                Password
              </Link>
              <button onClick={signOut} className="flex items-center justify-center gap-1.5 rounded-lg px-2 py-1.5 text-xs text-slate-400 hover:bg-white/5 hover:text-white">
                <Icon name="logout" className="h-3.5 w-3.5" />
                Sign out
              </button>
            </div>
          </div>
        )}
      </aside>
      <div className="min-w-0 flex-1">
        {/* On phones the sidebar footer is hidden, so the account links live here. */}
        <header className="flex flex-wrap items-center justify-end gap-x-4 gap-y-1 border-b border-slate-200 bg-white px-4 py-2 text-sm md:hidden">
          <span className="text-slate-700">
            {me?.full_name} <span className="text-slate-400">· {me ? ROLE_NAMES[me.role] : ""}</span>
          </span>
          <Link to="/account/password" className="text-slate-500 hover:text-slate-900">
            Password
          </Link>
          <button className="text-slate-500 hover:text-slate-900" onClick={signOut}>
            Sign out
          </button>
        </header>
        <main className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
