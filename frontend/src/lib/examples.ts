// Examples from Bull Machines' own work, so every department sees something it recognises.
// The department is matched by its code or name; anything unknown gets a mix.

import { useAuth } from "./auth";
import { useApi } from "./hooks";
import type { Department } from "./types";

export interface DeptExample {
  /** Who is being called, plural: "suppliers", "customers"... */
  who: string;
  /** The department's own system, for the connected-apps wording. */
  system: string;
  purpose: string;
  scriptName: string;
  campaignNames: string[];
  /** Name, phone, company for three example rows. */
  people: [string, string, string][];
  /** Extra columns the department would typically have, with three example values each. */
  fields: { label: string; values: [string, string, string] }[];
  fetchUrl: string;
  fetchPath: string;
  resultsUrl: string;
}

const SCM: DeptExample = {
  who: "suppliers",
  system: "ERP (e.g. SAP)",
  purpose: "Check that open purchase orders will be dispatched on time, and get the new date when they are late.",
  scriptName: "Supplier dispatch confirmation",
  campaignNames: ["Pending PO dispatch check - Nov week 2", "Hydraulic parts suppliers - follow-up", "Castings vendors - delivery dates"],
  people: [
    ["Ravi Kumar", "9876543210", "Sri Balaji Steels"],
    ["Ravi Kumar", "9876543210", "Sri Balaji Steels"],
    ["Lakshmi N", "9123456780", "KMR Castings"],
  ],
  fields: [
    { label: "PO Number", values: ["PO-45001", "PO-45034", "PO-45040"] },
    { label: "Material", values: ["Hydraulic cylinder", "Boom pin 60mm", "Axle housing"] },
    { label: "Due Date", values: ["2026-11-20", "2026-11-25", "2026-11-22"] },
  ],
  fetchUrl: "https://erp.example.com/api/purchase-orders?status=open",
  fetchPath: "data.orders",
  resultsUrl: "https://erp.example.com/api/po-followups",
};

const SALES: DeptExample = {
  who: "customers",
  system: "CRM",
  purpose: "Follow up on machine enquiries: is the customer still interested, which model, and when to arrange a demo.",
  scriptName: "Backhoe loader enquiry follow-up",
  campaignNames: ["Expo enquiries - follow-up", "Backhoe loader leads - Tamil Nadu", "Skid steer enquiries - November"],
  people: [
    ["Senthil Murugan", "9876543210", "Sri Murugan Earthmovers"],
    ["Priya Raman", "9123456780", "PR Constructions"],
    ["Arun Prakash", "+91 98400 12345", "Vel Infra Projects"],
  ],
  fields: [
    { label: "Enquiry ID", values: ["ENQ-2311", "ENQ-2318", "ENQ-2325"] },
    { label: "Machine", values: ["Backhoe loader", "Skid steer loader", "Backhoe loader"] },
    { label: "Dealer", values: ["Coimbatore", "Madurai", "Salem"] },
  ],
  fetchUrl: "https://crm.example.com/api/leads?stage=new",
  fetchPath: "data.leads",
  resultsUrl: "https://crm.example.com/api/lead-activities",
};

const SERVICE: DeptExample = {
  who: "machine owners",
  system: "service / CRM system",
  purpose: "Remind owners that their machine's service is due, book a visit, and ask how the last service went.",
  scriptName: "Service due reminder",
  campaignNames: ["Service due reminder - November", "500-hour service - backhoe loaders", "After-service feedback - October"],
  people: [
    ["Ravi Kumar", "9876543210", "Sri Murugan Earthmovers"],
    ["Ravi Kumar", "9876543210", "Sri Murugan Earthmovers"],
    ["Lakshmi N", "9123456780", "KMR Infra"],
  ],
  fields: [
    { label: "Machine Serial", values: ["BL-2024-0871", "BL-2024-0902", "SSL-2023-0112"] },
    { label: "Hour Meter", values: ["492", "1488", "990"] },
    { label: "Service Due", values: ["2026-11-20", "2026-11-22", "2026-11-25"] },
  ],
  fetchUrl: "https://service.example.com/api/machines/service-due",
  fetchPath: "data.machines",
  resultsUrl: "https://service.example.com/api/service-bookings",
};

const SPARES: DeptExample = {
  who: "dealers",
  system: "parts ordering system",
  purpose: "Confirm spare-part orders with dealers: received, complete, or anything missing.",
  scriptName: "Spare parts delivery confirmation",
  campaignNames: ["Parts orders - delivery confirmation", "Filter kits - dealer follow-up", "Pending back-orders - November"],
  people: [
    ["Karthik S", "9876543210", "Bull dealer - Madurai"],
    ["Meena Iyer", "9123456780", "Bull dealer - Trichy"],
    ["Rahul Sharma", "+91 98400 12345", "Bull dealer - Bengaluru"],
  ],
  fields: [
    { label: "Order No", values: ["SP-7781", "SP-7790", "SP-7802"] },
    { label: "Part", values: ["Hydraulic filter kit", "Bucket tooth set", "Fuel filter"] },
    { label: "Dispatched On", values: ["2026-11-08", "2026-11-09", "2026-11-10"] },
  ],
  fetchUrl: "https://parts.example.com/api/orders?status=dispatched",
  fetchPath: "orders",
  resultsUrl: "https://parts.example.com/api/order-confirmations",
};

const FINANCE: DeptExample = {
  who: "dealers",
  system: "accounting system (e.g. Tally)",
  purpose: "Remind dealers about invoices that are due and note when they will pay.",
  scriptName: "Payment due reminder",
  campaignNames: ["Invoices due this week", "Overdue 30+ days - reminder", "Dealer payments - November"],
  people: [
    ["Karthik S", "9876543210", "Bull dealer - Madurai"],
    ["Karthik S", "9876543210", "Bull dealer - Madurai"],
    ["Meena Iyer", "9123456780", "Bull dealer - Trichy"],
  ],
  fields: [
    { label: "Invoice No", values: ["INV-10231", "INV-10255", "INV-10260"] },
    { label: "Amount", values: ["245000", "86000", "132500"] },
    { label: "Due Date", values: ["2026-11-15", "2026-11-18", "2026-11-20"] },
  ],
  fetchUrl: "https://accounts.example.com/api/invoices?status=due",
  fetchPath: "data.invoices",
  resultsUrl: "https://accounts.example.com/api/collection-notes",
};

const HR: DeptExample = {
  who: "employees",
  system: "HR / attendance system",
  purpose: "Call employees who are absent without notice: ask the reason and when they will be back.",
  scriptName: "Absence check",
  campaignNames: ["Absent today - assembly line", "Unplanned leave - follow-up", "New joiners - first week check-in"],
  people: [
    ["Suresh K", "9876543210", "Assembly - Line 2"],
    ["Divya R", "9123456780", "Paint shop"],
    ["Manoj P", "+91 98400 12345", "Machining"],
  ],
  fields: [
    { label: "Employee ID", values: ["E-1042", "E-1188", "E-1203"] },
    { label: "Shift", values: ["General", "First", "Second"] },
    { label: "Absent From", values: ["2026-11-12", "2026-11-11", "2026-11-12"] },
  ],
  fetchUrl: "https://hr.example.com/api/attendance/absent-today",
  fetchPath: "employees",
  resultsUrl: "https://hr.example.com/api/absence-reasons",
};

const MIXED: DeptExample = {
  ...SERVICE,
  who: "people",
  system: "CRM, ERP or HR system",
  campaignNames: ["Service due reminder - November", "Pending PO dispatch check - Nov week 2", "Expo enquiries - follow-up"],
};

const MATCHERS: [RegExp, DeptExample][] = [
  [/scm|supply|purchas|procure|vendor|stores/i, SCM],
  [/spare|parts/i, SPARES],
  [/serv|after.?sales|customer.?care|support/i, SERVICE],
  [/sale|market|crm|lead/i, SALES],
  [/fin|account|collect|credit/i, FINANCE],
  [/^hr$|human|people|admin.?hr|attendance/i, HR],
];

export function examplesFor(department: Pick<Department, "code" | "name"> | null | undefined): DeptExample {
  if (!department) return MIXED;
  const text = `${department.code} ${department.name}`;
  return MATCHERS.find(([pattern]) => pattern.test(department.code) || pattern.test(text))?.[1] ?? MIXED;
}

/** Examples for a department (by id), or for the signed-in user's own department. */
export function useExamples(departmentId?: string | null): DeptExample {
  const { me } = useAuth();
  const departments = useApi<Department[]>("/departments");
  const id = departmentId ?? me?.department_id;
  return examplesFor(departments.data?.find((d) => d.id === id));
}
