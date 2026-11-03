import { describe, expect, it } from "vitest";

import { fieldKey, initialChoices, toMapping } from "./mapping";

describe("fieldKey", () => {
  it("matches the backend rule", () => {
    expect(fieldKey("PO Number")).toBe("po_number");
    expect(fieldKey("1st Contact #")).toBe("field_1st_contact");
    expect(fieldKey("***")).toBe("field");
  });
});

describe("initialChoices", () => {
  const headers = ["Supplier Name", "Phone Number", "PO Number", "Material", "Vendor Code"];
  const suggested = {
    name: "Supplier Name",
    phone: "Phone Number",
    contact_fields: { po_number: "PO Number", material: "Material", vendor_code: "Vendor Code" },
    campaign_fields: {},
  };

  it("uses script context fields as campaign fields", () => {
    const choices = initialChoices(headers, suggested, [
      { key: "po_number", label: "PO Number", type: "string", required: true },
      { key: "material_description", label: "Material", type: "string", required: true },
    ]);
    expect(choices["Supplier Name"].role).toBe("name");
    expect(choices["PO Number"]).toEqual({ role: "campaign_field", key: "po_number" });
    expect(choices["Material"]).toEqual({ role: "campaign_field", key: "material_description" });
    expect(choices["Vendor Code"]).toEqual({ role: "contact_field", key: "vendor_code" });
  });

  it("falls back to ignore without a suggestion", () => {
    expect(initialChoices(["A"], null, null)).toEqual({ A: { role: "ignore", key: "a" } });
  });
});

describe("toMapping", () => {
  it("builds the backend mapping", () => {
    const { mapping, problems } = toMapping({
      Name: { role: "name", key: "name" },
      Mobile: { role: "phone", key: "mobile" },
      PO: { role: "campaign_field", key: "po_number" },
      Code: { role: "contact_field", key: "code" },
      Junk: { role: "ignore", key: "junk" },
    });
    expect(problems).toEqual([]);
    expect(mapping).toEqual({ name: "Name", phone: "Mobile", campaign_fields: { po_number: "PO" }, contact_fields: { code: "Code" } });
  });

  it("reports missing and conflicting choices", () => {
    const { problems } = toMapping({
      A: { role: "name", key: "a" },
      B: { role: "name", key: "b" },
      C: { role: "contact_field", key: "x" },
      D: { role: "campaign_field", key: "x" },
      E: { role: "contact_field", key: "Bad Key" },
    });
    expect(problems).toContain("Only one column can be name");
    expect(problems).toContain('Field key "x" is used twice');
    expect(problems).toContain('"Bad Key" is not a valid field key (lowercase letters, digits, _)');
    expect(problems).toContain("Choose the column with the phone number");
  });
});
