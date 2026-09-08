/** Shareable signup link for inviting members into an organisation (org_id as invite code). */
export function buildMemberInviteLink(orgId: string, orgName?: string): string {
  const params = new URLSearchParams({ org: orgId });
  if (orgName) params.set("org_name", orgName);
  const qs = params.toString();
  if (typeof window === "undefined") return `/signup?${qs}`;
  return `${window.location.origin}/signup?${qs}`;
}
