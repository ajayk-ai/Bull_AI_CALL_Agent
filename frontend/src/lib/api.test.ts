import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, query, setSignedOutHandler, tokens } from "./api";

function json(status: number, body: unknown) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("ApiError.detailLines", () => {
  it("formats validation errors and readiness problems", () => {
    const validation = new ApiError(422, {
      code: "validation_failed",
      message: "Request validation failed",
      details: [{ loc: ["body", "config", "questions", 0, "id"], msg: "String should match pattern" }],
    });
    expect(validation.detailLines()).toEqual(["config > questions > 0 > id: String should match pattern"]);
    const readiness = new ApiError(422, { code: "validation_failed", message: "Not ready", details: { problems: ["No contacts"] } });
    expect(readiness.detailLines()).toEqual(["No contacts"]);
  });
});

describe("request", () => {
  beforeEach(() => tokens.set("old-access", "refresh-1"));
  afterEach(() => {
    vi.restoreAllMocks();
    tokens.clear();
  });

  it("refreshes once on 401 and retries with the new token", async () => {
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(401, { error: { code: "unauthorized", message: "Token expired" } }))
      .mockResolvedValueOnce(json(200, { access_token: "new-access", refresh_token: "refresh-2" }))
      .mockResolvedValueOnce(json(200, { ok: true }));

    expect(await api.get("/contacts")).toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    const retried = fetchMock.mock.calls[2][1] as RequestInit;
    expect((retried.headers as Record<string, string>).Authorization).toBe("Bearer new-access");
    expect(tokens.refresh).toBe("refresh-2");
  });

  it("signs out when the refresh fails", async () => {
    const signedOut = vi.fn();
    setSignedOutHandler(signedOut);
    vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json(401, { error: { code: "unauthorized", message: "Token expired" } }))
      .mockResolvedValueOnce(json(401, { error: { code: "unauthorized", message: "Session is no longer valid" } }));

    await expect(api.get("/contacts")).rejects.toBeInstanceOf(ApiError);
    expect(signedOut).toHaveBeenCalledOnce();
    expect(tokens.access).toBeNull();
  });

  it("raises the backend's error message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(json(409, { error: { code: "conflict", message: "Already exists" } }));
    await expect(api.post("/contacts", {})).rejects.toThrow("Already exists");
  });
});

describe("query", () => {
  it("skips empty values", () => {
    expect(query({ a: "x", b: "", c: undefined, d: 0, e: null })).toBe("?a=x&d=0");
    expect(query({})).toBe("");
  });
});
