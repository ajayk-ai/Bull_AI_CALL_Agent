import { useAuth } from "../lib/auth";
import { useApi } from "../lib/hooks";
import type { Department } from "../lib/types";
import { Field, Select } from "./ui";

/** Admins choose a department; everyone else always works in their own, so nothing is shown. */
export function DepartmentPicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const { me } = useAuth();
  const { data } = useApi<Department[]>(me?.role === "admin" ? "/departments" : null);
  if (me?.role !== "admin") return null;
  return (
    <Field label="Department">
      <Select value={value} onChange={(e) => onChange(e.target.value)} required>
        <option value="">Choose...</option>
        {(data ?? [])
          .filter((d) => d.is_active)
          .map((d) => (
            <option key={d.id} value={d.id}>
              {d.code} · {d.name}
            </option>
          ))}
      </Select>
    </Field>
  );
}

/** department_id to send: the chosen one for admins, omitted for others. */
export function departmentPayload(role: string | undefined, chosen: string) {
  return role === "admin" && chosen ? { department_id: chosen } : {};
}
