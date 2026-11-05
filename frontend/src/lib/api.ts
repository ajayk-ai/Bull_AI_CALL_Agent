// HTTP client for /api/v1. Tokens live in sessionStorage, so closing the tab signs the user out.

// import.meta.env.BASE_URL is the build's base path, e.g. "/aicall/" (or "/").
const BASE = `${import.meta.env.BASE_URL}api/v1`;
const ACCESS = "bullcall.access";
const REFRESH = "bullcall.refresh";

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: unknown;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.status = status;
    this.code = body.code;
    this.details = body.details;
  }

  /** Human-readable lines for the details the backend attaches (validation errors, readiness problems). */
  detailLines(): string[] {
    const d = this.details as Record<string, unknown> | unknown[] | null | undefined;
    if (Array.isArray(d)) {
      return d.map((e) => {
        const item = e as { loc?: (string | number)[]; msg?: string };
        const where = (item.loc ?? []).filter((p) => p !== "body").join(" > ");
        return where ? `${where}: ${item.msg}` : String(item.msg ?? JSON.stringify(e));
      });
    }
    if (d && typeof d === "object") {
      if (Array.isArray(d.problems)) return d.problems.map(String);
      if (Array.isArray(d.columns)) return [`Columns: ${d.columns.join(", ")}`];
    }
    return [];
  }
}

function storage(): Storage | null {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export const tokens = {
  get access() {
    return storage()?.getItem(ACCESS) ?? null;
  },
  get refresh() {
    return storage()?.getItem(REFRESH) ?? null;
  },
  set(access: string, refresh: string) {
    storage()?.setItem(ACCESS, access);
    storage()?.setItem(REFRESH, refresh);
  },
  clear() {
    storage()?.removeItem(ACCESS);
    storage()?.removeItem(REFRESH);
  },
};

let onSignedOut: () => void = () => {};
export function setSignedOutHandler(handler: () => void) {
  onSignedOut = handler;
}

let refreshing: Promise<boolean> | null = null;

async function refreshTokens(): Promise<boolean> {
  const refresh = tokens.refresh;
  if (!refresh) return false;
  refreshing ??= (async () => {
    try {
      const response = await fetch(`${BASE}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!response.ok) return false;
      const body = await response.json();
      tokens.set(body.access_token, body.refresh_token);
      return true;
    } finally {
      refreshing = null;
    }
  })();
  return refreshing;
}

async function toError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    if (body?.error) return new ApiError(response.status, body.error);
  } catch {
    // not JSON
  }
  return new ApiError(response.status, { code: "http_error", message: `Request failed (${response.status})` });
}

type Body = object | FormData | undefined;

export async function request<T>(method: string, path: string, body?: Body, retry = true): Promise<T> {
  const headers: Record<string, string> = {};
  if (tokens.access) headers.Authorization = `Bearer ${tokens.access}`;
  let payload: BodyInit | undefined;
  if (body instanceof FormData) payload = body;
  else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }

  const response = await fetch(`${BASE}${path}`, { method, headers, body: payload });
  if (response.status === 401 && retry && !path.startsWith("/auth/login")) {
    if (await refreshTokens()) return request<T>(method, path, body, false);
    tokens.clear();
    onSignedOut();
  }
  if (!response.ok) throw await toError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: Body) => request<T>("POST", path, body ?? {}),
  put: <T>(path: string, body: Body) => request<T>("PUT", path, body),
  patch: <T>(path: string, body: Body) => request<T>("PATCH", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};

/** Downloads a file from an authenticated endpoint. */
export async function download(path: string, fallbackName: string) {
  const response = await fetch(`${BASE}${path}`, {
    headers: tokens.access ? { Authorization: `Bearer ${tokens.access}` } : {},
  });
  if (!response.ok) throw await toError(response);
  const disposition = response.headers.get("content-disposition") ?? "";
  const name = /filename="([^"]+)"/.exec(disposition)?.[1] ?? fallbackName;
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

export function query(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
