import { NavLink, Outlet } from "react-router";

import { useAuth } from "../lib/auth";
import { ROLE_NAMES } from "./ui";

const NAV: { to: string; label: string; permission?: string }[] = [
  { to: "/campaigns", label: "Campaigns", permission: "campaigns:read" },
  { to: "/contacts", label: "Contacts", permission: "contacts:read" },
  { to: "/imports", label: "Uploads", permission: "contacts:read" },
  { to: "/scripts", label: "Scripts", permission: "scripts:read" },
  { to: "/dnc", label: "Do not call", permission: "dnc:read" },
  { to: "/users", label: "Users", permission: "users:read" },
  { to: "/departments", label: "Departments", permission: "departments:manage" },
  { to: "/audit", label: "Audit log", permission: "audit:read" },
];

export function Layout() {
  const { me, can, signOut } = useAuth();
  return (
    <div className="min-h-screen md:flex">
      <aside className="border-b border-slate-800 bg-slate-900 text-slate-200 md:min-h-screen md:w-56 md:shrink-0 md:border-b-0">
        <div className="flex items-center justify-between px-4 py-4 md:block">
          <div>
            <p className="text-base font-semibold text-white">
              <span className="text-brand-500">Bull</span> AI Calling
            </p>
            <p className="text-xs text-slate-400">Bull Machines</p>
          </div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-4">
          {NAV.filter((item) => !item.permission || can(item.permission)).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `whitespace-nowrap rounded-md px-3 py-2 text-sm ${isActive ? "bg-slate-700 text-white" : "hover:bg-slate-800"}`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="min-w-0 flex-1">
        <header className="flex items-center justify-end gap-3 border-b border-slate-200 bg-white px-4 py-2 text-sm">
          <span className="text-slate-700">
            {me?.full_name} <span className="text-slate-400">· {me ? ROLE_NAMES[me.role] : ""}</span>
          </span>
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
