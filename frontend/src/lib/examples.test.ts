import { describe, expect, it } from "vitest";

import { examplesFor } from "./examples";

describe("examplesFor", () => {
  it("matches departments by code or name", () => {
    expect(examplesFor({ code: "SCM", name: "Supply Chain Management" }).who).toBe("suppliers");
    expect(examplesFor({ code: "SVC", name: "Service" }).who).toBe("machine owners");
    expect(examplesFor({ code: "HR", name: "Human Resources" }).who).toBe("employees");
    expect(examplesFor({ code: "SALES", name: "Sales and Marketing" }).who).toBe("customers");
    expect(examplesFor({ code: "SPARES", name: "Spare Parts" }).who).toBe("dealers");
  });

  it("falls back to a mix", () => {
    expect(examplesFor(null).who).toBe("people");
    expect(examplesFor({ code: "QA", name: "Quality" }).who).toBe("people");
  });
});
