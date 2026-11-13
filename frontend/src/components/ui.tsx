import {
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type FormEvent,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";

import { ApiError } from "../lib/api";

// ---- Icons (inline, stroke-based, 20x20 viewbox) ----

const ICONS = {
  check: "M4.5 10.5l3.5 3.5 7.5-8",
  plus: "M10 4v12M4 10h12",
  x: "M5 5l10 10M15 5L5 15",
  search: "M9 15a6 6 0 100-12 6 6 0 000 12zM17 17l-3.6-3.6",
  more: "M4 10h.01M10 10h.01M16 10h.01",
  chevronDown: "M5 8l5 5 5-5",
  chevronRight: "M8 5l5 5-5 5",
  user: "M10 10a3.5 3.5 0 100-7 3.5 3.5 0 000 7zM3.5 17a6.5 6.5 0 0113 0",
  users: "M7.5 9a3 3 0 100-6 3 3 0 000 6zM2 16.5a5.5 5.5 0 0111 0M13 3.3a3 3 0 010 5.4M15.5 16.5a5.5 5.5 0 00-2.2-4.4",
  shield: "M10 2.5l6 2.5v4.5c0 4-2.6 6.8-6 8-3.4-1.2-6-4-6-8V5l6-2.5z",
  key: "M12.5 7.5a3 3 0 11-6 0 3 3 0 016 0zM9.5 10.5L4 16v1.5h2.5V16H8v-1.5h1.5l1.4-1.4",
  building: "M4 17V4.5L10 3v14M10 7l6 1.5V17M2.5 17h15M6.5 7h1M6.5 10h1M6.5 13h1M12.5 10.5h1M12.5 13.5h1",
  megaphone: "M3 8v4h3l6 4V4L6 8H3zM15 7.5a3.5 3.5 0 010 5",
  phone: "M5 3h3l1.5 4-2 1.2a9 9 0 004.3 4.3l1.2-2 4 1.5v3a1.5 1.5 0 01-1.5 1.5A13.5 13.5 0 013.5 4.5 1.5 1.5 0 015 3z",
  contacts: "M4 3h11a1 1 0 011 1v12a1 1 0 01-1 1H4zM7.5 3v14M11.5 9.5a2 2 0 100-4 2 2 0 000 4zM9 13a2.5 2.5 0 015 0",
  upload: "M10 13V3.5M6 7l4-4 4 4M3.5 13v2.5A1.5 1.5 0 005 17h10a1.5 1.5 0 001.5-1.5V13",
  plug: "M7 3v4M13 3v4M5 7h10v3a5 5 0 01-10 0V7zM10 15v2.5",
  download: "M10 3.5V13M6 9l4 4 4-4M3.5 13v2.5A1.5 1.5 0 005 17h10a1.5 1.5 0 001.5-1.5V13",
  script: "M6 3h6l4 4v10H6zM12 3v4h4M8.5 10.5h5M8.5 13.5h5",
  ban: "M10 17a7 7 0 100-14 7 7 0 000 14zM5 5l10 10",
  log: "M5 3.5h10v13H5zM8 7h4M8 10h4M8 13h2.5",
  logout: "M8 17H4.5A1.5 1.5 0 013 15.5v-11A1.5 1.5 0 014.5 3H8M13 14l4-4-4-4M17 10H8",
  lock: "M5.5 9h9v8h-9zM7.5 9V6.5a2.5 2.5 0 015 0V9",
  copy: "M7 7h9v9H7zM4 13V4h9",
  info: "M10 17a7 7 0 100-14 7 7 0 000 14zM10 9.5V14M10 6.5h.01",
} as const;

export type IconName = keyof typeof ICONS;

export function Icon({ name, className = "h-4 w-4" }: { name: IconName; className?: string }) {
  return (
    <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" className={`shrink-0 ${className}`}>
      <path d={ICONS[name]} />
    </svg>
  );
}

// ---- Buttons and form controls ----

type Variant = "primary" | "secondary" | "danger" | "ghost";

const variants: Record<Variant, string> = {
  primary: "bg-slate-900 text-white shadow-sm hover:bg-slate-800 disabled:bg-slate-300 disabled:shadow-none",
  secondary: "bg-white text-slate-800 shadow-sm ring-1 ring-inset ring-slate-300 hover:bg-slate-50 disabled:text-slate-400",
  danger: "bg-red-600 text-white shadow-sm hover:bg-red-700 disabled:bg-red-300",
  ghost: "text-slate-600 hover:bg-slate-100 hover:text-slate-900 disabled:text-slate-300 disabled:hover:bg-transparent",
};

export function Button({ variant = "primary", className = "", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-500 disabled:cursor-not-allowed ${variants[variant]} ${className}`}
      {...props}
    />
  );
}

const field =
  "w-full rounded-lg border-0 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm ring-1 ring-inset ring-slate-300 transition placeholder:text-slate-400 focus:ring-2 focus:ring-inset focus:ring-brand-500 focus:outline-none disabled:bg-slate-50 disabled:text-slate-500 disabled:ring-slate-200";

export function Input(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`${field} ${props.className ?? ""}`} />;
}

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={`${field} pr-8 ${props.className ?? ""}`} />;
}

export function TextArea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea rows={3} {...props} className={`${field} leading-relaxed ${props.className ?? ""}`} />;
}

export function Field({ label, hint, children, className = "" }: { label: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <label className={`block ${className}`}>
      <span className="mb-1.5 block text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1.5 block text-xs leading-relaxed text-slate-500">{hint}</span>}
    </label>
  );
}

/** A group of selectable cards; a friendlier radio group for a few important choices. */
export function ChoiceCards<T extends string>({
  value,
  onChange,
  options,
  disabled,
  columns = 2,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string; description?: string; icon?: IconName }[];
  disabled?: boolean;
  columns?: 1 | 2;
}) {
  return (
    <div role="radiogroup" className={`grid gap-3 ${columns === 2 ? "sm:grid-cols-2" : ""}`}>
      {options.map((o) => {
        const selected = o.value === value;
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            onClick={() => onChange(o.value)}
            className={`flex items-start gap-3 rounded-xl p-3.5 text-left ring-1 transition disabled:cursor-not-allowed disabled:opacity-60 ${
              selected ? "bg-brand-50 ring-2 ring-brand-500" : "bg-white ring-slate-200 hover:ring-slate-300"
            }`}
          >
            {o.icon && (
              <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${selected ? "bg-brand-500 text-white" : "bg-slate-100 text-slate-600"}`}>
                <Icon name={o.icon} />
              </span>
            )}
            <span className="min-w-0 flex-1">
              <span className="block text-sm font-semibold text-slate-900">{o.label}</span>
              {o.description && <span className="mt-0.5 block text-xs leading-relaxed text-slate-500">{o.description}</span>}
            </span>
            <span className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full ring-1 ${selected ? "bg-brand-500 ring-brand-500" : "ring-slate-300"}`}>
              {selected && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/** A compact one-of-many switch, e.g. for list filters. */
export function Segmented<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: { value: T; label: string }[] }) {
  return (
    <div className="inline-flex rounded-lg bg-slate-100 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={`whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium transition ${o.value === value ? "bg-white text-slate-900 shadow-sm" : "text-slate-500 hover:text-slate-800"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

// ---- Surfaces ----

export function Card({
  title,
  subtitle,
  actions,
  children,
  className = "",
  flush = false,
}: {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** No padding around the body, e.g. for an edge-to-edge table. */
  flush?: boolean;
}) {
  return (
    <section className={`min-w-0 rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
          <div className="min-w-0">
            <h2 className="text-[15px] font-semibold text-slate-900">{title}</h2>
            {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
          </div>
          <div className="flex flex-wrap gap-2">{actions}</div>
        </header>
      )}
      <div className={flush ? "" : "p-5"}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-sm text-slate-500">{subtitle}</p>}
      </div>
      <div className="flex flex-wrap items-center gap-2">{actions}</div>
    </div>
  );
}

// ---- Step-by-step setup on a single scrolling page ----

/** One numbered step of a setup page. `plain` drops the card, for use inside a drawer. */
export function Step({
  n,
  title,
  help,
  actions,
  done,
  plain = false,
  last = false,
  children,
}: {
  n: number;
  title: string;
  help?: ReactNode;
  actions?: ReactNode;
  done?: boolean;
  plain?: boolean;
  last?: boolean;
  children: ReactNode;
}) {
  const badge = (
    <span
      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold transition ${
        done ? "bg-emerald-500 text-white" : "bg-slate-900 text-white"
      }`}
    >
      {done ? <Icon name="check" className="h-3.5 w-3.5" /> : n}
    </span>
  );
  const heading = (
    <div className="min-w-0 flex-1">
      <h2 className="text-[15px] font-semibold leading-7 text-slate-900">{title}</h2>
      {help && <p className="mt-0.5 text-sm leading-relaxed text-slate-500">{help}</p>}
    </div>
  );

  if (plain) {
    return (
      <section id={`step-${n}`} className="relative flex gap-4">
        <div className="flex flex-col items-center">
          {badge}
          {!last && <span className="mt-2 w-px flex-1 bg-slate-200" />}
        </div>
        <div className={`min-w-0 flex-1 ${last ? "" : "pb-8"}`}>
          <div className="mb-4 flex flex-wrap items-start gap-3">
            {heading}
            {actions}
          </div>
          {children}
        </div>
      </section>
    );
  }

  return (
    <section id={`step-${n}`} className="min-w-0 scroll-mt-6 rounded-xl border border-slate-200 bg-white shadow-sm">
      <header className="flex flex-wrap items-start gap-3 border-b border-slate-100 px-5 py-4">
        {badge}
        {heading}
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </header>
      <div className="px-5 py-5">{children}</div>
    </section>
  );
}

export type OutlineStep = { n: number; title: string; done?: boolean; optional?: boolean };

/** Sticky outline of a setup page's steps: shows progress, highlights the step in view, and jumps on click. */
export function StepOutline({ steps, title = "Setup" }: { steps: OutlineStep[]; title?: string }) {
  const [active, setActive] = useState(steps[0]?.n);
  const key = steps.map((s) => s.n).join(",");

  useEffect(() => {
    const ns = key.split(",").map(Number);
    const onScroll = () => {
      let current = ns[0];
      for (const n of ns) {
        const el = document.getElementById(`step-${n}`);
        if (el && el.getBoundingClientRect().top <= 160) current = n;
      }
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) current = ns[ns.length - 1];
      setActive(current);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, [key]);

  const required = steps.filter((s) => !s.optional);
  const complete = required.filter((s) => s.done).length;

  return (
    <nav aria-label="Steps" className="sticky top-6">
      <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">{title}</p>
      <div className="mt-2 flex items-center gap-2">
        <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-200">
          <div className="h-full rounded-full bg-emerald-500 transition-all" style={{ width: `${required.length ? (complete / required.length) * 100 : 0}%` }} />
        </div>
        <span className="text-xs tabular-nums text-slate-500">
          {complete}/{required.length}
        </span>
      </div>
      <ol className="mt-4 space-y-0.5">
        {steps.map((s) => {
          const isActive = s.n === active;
          return (
            <li key={s.n}>
              <a
                href={`#step-${s.n}`}
                onClick={(e) => {
                  e.preventDefault();
                  document.getElementById(`step-${s.n}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
                }}
                className={`flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-sm transition ${isActive ? "bg-white font-medium text-slate-900 shadow-sm ring-1 ring-slate-200" : "text-slate-600 hover:text-slate-900"}`}
              >
                <span
                  className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
                    s.done ? "bg-emerald-500 text-white" : isActive ? "bg-slate-900 text-white" : "bg-slate-200 text-slate-600"
                  }`}
                >
                  {s.done ? <Icon name="check" className="h-3 w-3" /> : s.n}
                </span>
                <span className="min-w-0 flex-1 truncate">{s.title}</span>
                {s.optional && <span className="text-[10px] uppercase tracking-wide text-slate-400">opt</span>}
              </a>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

// ---- Guidance for first-time users ----

function remembered(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function remember(key: string, on: boolean) {
  try {
    if (on) window.localStorage.setItem(key, "1");
    else window.localStorage.removeItem(key);
  } catch {
    // Storage blocked: the guide simply shows again next time.
  }
}

export type GuideStep = { title: string; text: ReactNode; icon?: IconName };

/** A friendly "how this works" strip of numbered steps. It can be hidden; a small link brings it back. */
export function Guide({ id, title, steps, forceOpen = false }: { id: string; title: string; steps: GuideStep[]; forceOpen?: boolean }) {
  const key = `bullcall.guide.${id}.hidden`;
  const [hidden, setHidden] = useState(() => remembered(key));
  const toggle = (h: boolean) => {
    remember(key, h);
    setHidden(h);
  };
  if (hidden && !forceOpen) {
    return (
      <button type="button" onClick={() => toggle(false)} className="mb-4 inline-flex items-center gap-1.5 text-sm font-medium text-slate-500 hover:text-slate-900">
        <Icon name="info" />
        {title}
      </button>
    );
  }
  return (
    <section className="mb-6 overflow-hidden rounded-xl border border-brand-100 bg-gradient-to-br from-brand-50 to-white">
      <header className="flex items-center justify-between gap-3 px-5 pt-4">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold text-slate-900">
          <Icon name="info" className="h-4 w-4 text-brand-600" />
          {title}
        </h2>
        {!forceOpen && (
          <button type="button" onClick={() => toggle(true)} className="text-xs font-medium text-slate-500 hover:text-slate-900">
            Hide
          </button>
        )}
      </header>
      <ol className={`grid gap-4 px-5 pb-5 pt-4 sm:grid-cols-2 ${steps.length >= 4 ? "lg:grid-cols-4" : "lg:grid-cols-3"}`}>
        {steps.map((s, i) => (
          <li key={s.title} className="flex gap-3">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white text-xs font-semibold text-slate-900 shadow-sm ring-1 ring-brand-100">{i + 1}</span>
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-900">{s.title}</p>
              <div className="mt-0.5 text-sm leading-relaxed text-slate-600">{s.text}</div>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** A small picture of a spreadsheet, to show what a good file looks like. */
export function ExampleSheet({ headers, rows, highlight = [], caption }: { headers: string[]; rows: string[][]; highlight?: string[]; caption?: ReactNode }) {
  return (
    <figure className="min-w-0">
      <div className="overflow-x-auto rounded-lg ring-1 ring-slate-200">
        <table className="w-full border-collapse text-left font-mono text-xs">
          <thead>
            <tr className="bg-emerald-50">
              <th className="w-8 border-b border-r border-slate-200 bg-slate-100 px-2 py-1.5 text-center font-normal text-slate-400">1</th>
              {headers.map((h) => (
                <th key={h} className={`whitespace-nowrap border-b border-r border-slate-200 px-2.5 py-1.5 font-semibold last:border-r-0 ${highlight.includes(h) ? "text-emerald-800" : "text-slate-700"}`}>
                  {h}
                  {highlight.includes(h) && <span className="ml-1 text-red-500">*</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={i} className="bg-white">
                <td className="border-r border-t border-slate-200 bg-slate-100 px-2 py-1.5 text-center text-slate-400">{i + 2}</td>
                {row.map((cell, j) => (
                  <td key={j} className="whitespace-nowrap border-r border-t border-slate-200 px-2.5 py-1.5 text-slate-700 last:border-r-0">
                    {cell}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {caption && <figcaption className="mt-2 text-xs leading-relaxed text-slate-500">{caption}</figcaption>}
    </figure>
  );
}

export type Milestone = { title: string; done: boolean; text: ReactNode; action?: ReactNode };

/** A row of milestones; the first unfinished one is expanded with what to do next. */
export function NextSteps({ title, steps }: { title: string; steps: Milestone[] }) {
  const current = steps.findIndex((s) => !s.done);
  const now = current >= 0 ? steps[current] : null;
  return (
    <section className="mb-6 rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 border-b border-slate-100 px-5 py-4">
        <h2 className="mr-auto text-[15px] font-semibold text-slate-900">{title}</h2>
        <ol className="flex flex-wrap items-center gap-x-2 gap-y-2">
          {steps.map((s, i) => (
            <li key={s.title} className="flex items-center gap-2">
              <span
                className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-semibold ${
                  s.done ? "bg-emerald-500 text-white" : i === current ? "bg-slate-900 text-white" : "bg-slate-200 text-slate-500"
                }`}
              >
                {s.done ? <Icon name="check" className="h-3 w-3" /> : i + 1}
              </span>
              <span className={`text-sm ${i === current ? "font-semibold text-slate-900" : s.done ? "text-slate-600" : "text-slate-400"}`}>{s.title}</span>
              {i < steps.length - 1 && <Icon name="chevronRight" className="h-4 w-4 text-slate-300" />}
            </li>
          ))}
        </ol>
      </div>
      {now && (
        <div className="flex flex-wrap items-center gap-4 px-5 py-4">
          <p className="min-w-0 flex-1 text-sm leading-relaxed text-slate-600">
            <span className="font-semibold text-slate-900">Next: {now.title}. </span>
            {now.text}
          </p>
          {now.action}
        </div>
      )}
    </section>
  );
}

// ---- Overlays ----

function useEscape(onClose: () => void) {
  const ref = useRef(onClose);
  ref.current = onClose;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && ref.current();
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, []);
}

/** A panel that slides in from the right, with a scrolling body and a fixed footer. */
export function Drawer({
  title,
  subtitle,
  onClose,
  onSubmit,
  footer,
  children,
}: {
  title: string;
  subtitle?: ReactNode;
  onClose: () => void;
  onSubmit?: (e: FormEvent) => void;
  footer?: ReactNode;
  children: ReactNode;
}) {
  useEscape(onClose);
  const inner = (
    <>
      <header className="flex items-start gap-3 border-b border-slate-200 px-6 py-5">
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-semibold tracking-tight text-slate-900">{title}</h2>
          {subtitle && <p className="mt-0.5 text-sm text-slate-500">{subtitle}</p>}
        </div>
        <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
          <Icon name="x" className="h-5 w-5" />
        </button>
      </header>
      <div className="flex-1 overflow-y-auto px-6 py-6">{children}</div>
      {footer && <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-200 bg-slate-50 px-6 py-4">{footer}</footer>}
    </>
  );
  const panel = "flex h-full w-full max-w-xl flex-col bg-white shadow-2xl animate-[slide-in_.2s_ease-out]";
  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px] animate-[fade-in_.2s_ease-out]" onClick={onClose} />
      {onSubmit ? (
        <form onSubmit={onSubmit} className={`relative ${panel}`}>
          {inner}
        </form>
      ) : (
        <div className={`relative ${panel}`}>{inner}</div>
      )}
    </div>
  );
}

/** A small centred dialog. */
export function Modal({ title, onClose, footer, children, icon }: { title: string; onClose: () => void; footer?: ReactNode; children: ReactNode; icon?: ReactNode }) {
  useEscape(onClose);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-[2px] animate-[fade-in_.2s_ease-out]" onClick={onClose} />
      <div className="relative w-full max-w-md rounded-2xl bg-white shadow-2xl animate-[pop-in_.18s_ease-out]">
        <div className="px-6 pb-2 pt-6">
          {icon}
          <h2 className="text-lg font-semibold tracking-tight text-slate-900">{title}</h2>
          <div className="mt-3">{children}</div>
        </div>
        {footer && <div className="flex flex-wrap justify-end gap-2 px-6 pb-6 pt-4">{footer}</div>}
      </div>
    </div>
  );
}

/** A "more actions" button with a small dropdown. Items close the menu when chosen. */
export function Menu({ items, label = "More actions" }: { items: ({ label: string; onSelect: () => void; danger?: boolean } | false | null | undefined)[]; label?: string }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  const visible = items.filter((i): i is { label: string; onSelect: () => void; danger?: boolean } => !!i);
  if (!visible.length) return null;
  return (
    <div ref={ref} className="relative inline-block text-left">
      <button
        type="button"
        aria-label={label}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        className="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
      >
        <Icon name="more" className="h-5 w-5" />
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-48 overflow-hidden rounded-xl bg-white py-1 shadow-lg ring-1 ring-slate-200 animate-[pop-in_.12s_ease-out]">
          {visible.map((item) => (
            <button
              key={item.label}
              type="button"
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className={`block w-full px-3.5 py-2 text-left text-sm ${item.danger ? "text-red-600 hover:bg-red-50" : "text-slate-700 hover:bg-slate-50"}`}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- Status and feedback ----

const tones = {
  slate: "bg-slate-100 text-slate-700 ring-slate-500/10",
  amber: "bg-amber-50 text-amber-800 ring-amber-600/20",
  green: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  red: "bg-red-50 text-red-700 ring-red-600/20",
  blue: "bg-sky-50 text-sky-700 ring-sky-600/20",
};

export function Badge({ tone = "slate", children }: { tone?: keyof typeof tones; children: ReactNode }) {
  return <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${tones[tone]}`}>{children}</span>;
}

const statusTones: Record<string, keyof typeof tones> = {
  draft: "slate",
  pending_approval: "amber",
  published: "green",
  approved: "green",
  completed: "green",
  running: "blue",
  paused: "amber",
  retired: "slate",
  cancelled: "red",
  failed: "red",
  rejected: "red",
  uploaded: "slate",
  queued: "slate",
  dialing: "blue",
  ringing: "blue",
  in_progress: "blue",
  no_answer: "amber",
  busy: "amber",
  retry_scheduled: "amber",
  skipped: "slate",
  validated: "green",
  verified: "green",
  needs_review: "amber",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={statusTones[status] ?? "slate"}>{status.replace(/_/g, " ")}</Badge>;
}

export function ErrorBox({ error }: { error: Error | null | undefined }) {
  if (!error) return null;
  const lines = error instanceof ApiError ? error.detailLines() : [];
  return (
    <div role="alert" className="mb-4 flex gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
      <Icon name="info" className="mt-0.5 h-4 w-4 text-red-500" />
      <div className="min-w-0">
        <p className="font-medium">{error.message}</p>
        {lines.length > 0 && (
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {lines.slice(0, 30).map((line, i) => (
              <li key={i}>{line}</li>
            ))}
            {lines.length > 30 && <li>... and {lines.length - 30} more</li>}
          </ul>
        )}
      </div>
    </div>
  );
}

export function Notice({ children, tone = "amber" }: { children: ReactNode; tone?: "amber" | "green" | "blue" }) {
  const styles = {
    amber: "border-amber-200 bg-amber-50 text-amber-900 [&>svg]:text-amber-500",
    green: "border-emerald-200 bg-emerald-50 text-emerald-900 [&>svg]:text-emerald-500",
    blue: "border-sky-200 bg-sky-50 text-sky-900 [&>svg]:text-sky-500",
  };
  return (
    <div className={`mb-4 flex gap-3 rounded-xl border px-4 py-3 text-sm ${styles[tone]}`}>
      <Icon name={tone === "green" ? "check" : "info"} className="mt-0.5 h-4 w-4" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}

// ---- Tables and lists ----

export function Table({ headers, children, empty }: { headers: ReactNode[]; children: ReactNode; empty?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-200 bg-slate-50/70 text-xs text-slate-500">
            {headers.map((h, i) => (
              <th key={i} className="whitespace-nowrap px-4 py-2.5 font-medium first:rounded-tl-lg last:rounded-tr-lg">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 [&>tr]:transition-colors [&>tr:hover]:bg-slate-50/70">{children}</tbody>
      </table>
      {empty && <EmptyState title="Nothing here yet" />}
    </div>
  );
}

export function Td({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <td className={`px-4 py-3 align-middle ${className}`}>{children}</td>;
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-4 py-12 text-center">
      <span className="flex h-11 w-11 items-center justify-center rounded-full bg-slate-100 text-slate-400">
        <Icon name="search" className="h-5 w-5" />
      </span>
      <p className="mt-3 text-sm font-medium text-slate-700">{title}</p>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  return (
    <div className="mt-4 flex items-center justify-end gap-3 text-sm text-slate-600">
      <span className="tabular-nums">
        Page {page} of {pages}
      </span>
      <Button variant="secondary" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </Button>
      <Button variant="secondary" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </Button>
    </div>
  );
}

export function Loading() {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-700" />
      Loading...
    </div>
  );
}

/** Initials in a coloured circle, picked from the name so it stays the same. */
export function Avatar({ name, size = "md" }: { name: string; size?: "sm" | "md" }) {
  const initials =
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((p) => p[0]?.toUpperCase())
      .join("") || "?";
  const palette = ["bg-amber-100 text-amber-800", "bg-sky-100 text-sky-800", "bg-emerald-100 text-emerald-800", "bg-violet-100 text-violet-800", "bg-rose-100 text-rose-800", "bg-teal-100 text-teal-800"];
  const hash = [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 0);
  const dims = size === "sm" ? "h-7 w-7 text-[11px]" : "h-9 w-9 text-xs";
  return <span className={`flex shrink-0 items-center justify-center rounded-full font-semibold ${dims} ${palette[hash % palette.length]}`}>{initials}</span>;
}

export function formatDate(value: string | null | undefined, withTime = false): string {
  if (!value) return "-";
  const date = new Date(value);
  return withTime
    ? date.toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })
    : date.toLocaleDateString("en-IN", { dateStyle: "medium" });
}

export const LANGUAGE_NAMES: Record<string, string> = {
  "ta-IN": "Tamil",
  "en-IN": "English",
  "hi-IN": "Hindi",
  "te-IN": "Telugu",
  "kn-IN": "Kannada",
  "ml-IN": "Malayalam",
  "mr-IN": "Marathi",
  "bn-IN": "Bengali",
};

export const ROLE_NAMES: Record<string, string> = {
  admin: "Admin",
  user: "User",
};
