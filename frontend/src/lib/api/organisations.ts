import { apiFetch } from "@/lib/api/http";

/** Deletes an organisation (super_admin only, must be the caller's active org). */
export async function deleteOrganisation(orgId: string): Promise<Record<string, unknown>> {
  return apiFetch(`/organisations/${encodeURIComponent(orgId)}`, { method: "DELETE" });
}
