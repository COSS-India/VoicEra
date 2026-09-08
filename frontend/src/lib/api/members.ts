import { apiFetch } from "@/lib/api/http";
import type { LoginResponse, MemberListResponse } from "@/lib/api-types";

/** Creates the account directly in the caller's active org — there is no separate
 * accept-invite step; the admin/super_admin sets the new member's password here. */
export async function inviteMember(email: string, password: string): Promise<{ status: string }> {
  return apiFetch("/members/invite", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

/** Public self-serve join via invite link (org_id as invite code). Returns a JWT. */
export async function joinOrganisation(
  email: string,
  password: string,
  orgId: string,
): Promise<LoginResponse> {
  return apiFetch<LoginResponse>(
    "/members/join",
    {
      method: "POST",
      body: JSON.stringify({ email, password, org_id: orgId }),
    },
    false,
  );
}

export async function listMembers(orgId: string): Promise<MemberListResponse> {
  return apiFetch<MemberListResponse>(`/members/${encodeURIComponent(orgId)}`);
}

/** Promote a member to admin in the caller's active org (super_admin only). */
export async function assignAdmin(email: string): Promise<{ status: string }> {
  return apiFetch("/members/assign-admin", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

/** Remove a member from the caller's active org (super_admin only). */
export async function removeMember(email: string): Promise<{ status: string }> {
  return apiFetch("/members/remove", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}
