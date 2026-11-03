// Column roles in the upload wizard, converted to and from the backend's ColumnMapping.

import type { ColumnMapping, ContextField } from "./types";

export type ColumnRole = "ignore" | "name" | "phone" | "company" | "language" | "contact_field" | "campaign_field";

export interface ColumnChoice {
  role: ColumnRole;
  key: string;
}

/** Same rule as the backend: "PO Number" -> "po_number". */
export function fieldKey(header: string): string {
  let key = header
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "");
  if (!key || !/^[a-z]/.test(key)) key = key ? `field_${key}` : "field";
  return key.slice(0, 64);
}

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, "");

/** Initial choices: the backend's suggestion, with script context fields recognised as campaign fields. */
export function initialChoices(
  headers: string[],
  suggested: ColumnMapping | null,
  contextFields: ContextField[] | null,
): Record<string, ColumnChoice> {
  const choices: Record<string, ColumnChoice> = {};
  for (const header of headers) {
    const key = fieldKey(header);
    const context = contextFields?.find((f) => norm(f.key) === norm(header) || norm(f.label) === norm(header));
    let role: ColumnRole = "ignore";
    if (suggested?.name === header) role = "name";
    else if (suggested?.phone === header) role = "phone";
    else if (suggested?.company === header) role = "company";
    else if (suggested?.language === header) role = "language";
    else if (context) role = "campaign_field";
    else if (suggested && Object.values(suggested.contact_fields).includes(header)) role = "contact_field";
    choices[header] = { role, key: context?.key ?? key };
  }
  return choices;
}

export function toMapping(choices: Record<string, ColumnChoice>): { mapping: Partial<ColumnMapping>; problems: string[] } {
  const mapping: Partial<ColumnMapping> & { contact_fields: Record<string, string>; campaign_fields: Record<string, string> } = {
    contact_fields: {},
    campaign_fields: {},
  };
  const problems: string[] = [];
  const keys = new Set<string>();
  for (const [header, choice] of Object.entries(choices)) {
    switch (choice.role) {
      case "ignore":
        break;
      case "name":
      case "phone":
      case "company":
      case "language":
        if (mapping[choice.role]) problems.push(`Only one column can be ${choice.role}`);
        mapping[choice.role] = header;
        break;
      case "contact_field":
      case "campaign_field": {
        if (!/^[a-z][a-z0-9_]{0,63}$/.test(choice.key)) problems.push(`"${choice.key}" is not a valid field key (lowercase letters, digits, _)`);
        if (keys.has(choice.key)) problems.push(`Field key "${choice.key}" is used twice`);
        keys.add(choice.key);
        const target = choice.role === "contact_field" ? mapping.contact_fields : mapping.campaign_fields;
        target[choice.key] = header;
        break;
      }
    }
  }
  if (!mapping.name) problems.push("Choose the column with the contact name");
  if (!mapping.phone) problems.push("Choose the column with the phone number");
  return { mapping, problems };
}
