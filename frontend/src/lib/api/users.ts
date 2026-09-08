import { apiFetch } from "@/lib/api/http";
import type {
  CheckEmailResult,
  LoginResponse,
  OrganisationSummary,
  UserOrganisationsResponse,
  UserProfile,
} from "@/lib/api-types";

export async function login(email: string, password: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>(
    "/users/login",
    { method: "POST", body: JSON.stringify({ email, password }) },
    false,
  );
}

export async function signup(
  email: string,
  password: string,
  organisationName: string,
): Promise<LoginResponse> {
  return apiFetch<LoginResponse>(
    "/users/signup",
    {
      method: "POST",
      body: JSON.stringify({
        email,
        password,
        organisation_name: organisationName,
      }),
    },
    false,
  );
}

export async function getMe(): Promise<UserProfile> {
  return apiFetch<UserProfile>("/users/me");
}

/** Every organisation the current user belongs to (for the account page's org switcher). */
export async function getUserOrganisations(): Promise<OrganisationSummary[]> {
  const res = await apiFetch<UserOrganisationsResponse>("/users/organisations");
  return res.organisations;
}

export async function switchOrganisation(orgId: string): Promise<LoginResponse> {
  return apiFetch<LoginResponse>("/users/switch-organisation", {
    method: "POST",
    body: JSON.stringify({ org_id: orgId }),
  });
}

/** Invite-flow helper: does this email already exist, and is it already in this org? */
export async function checkEmail(email: string, orgId?: string): Promise<CheckEmailResult> {
  const query = orgId ? `?org_id=${encodeURIComponent(orgId)}` : "";
  return apiFetch<CheckEmailResult>(`/users/check/${encodeURIComponent(email)}${query}`, {}, false);
}

export async function getUserByEmail(email: string): Promise<UserProfile> {
  return apiFetch<UserProfile>(`/users/${encodeURIComponent(email)}`);
}

export async function forgotPassword(email: string): Promise<{ status: string; message: string }> {
  return apiFetch(
    "/users/forgot-password",
    { method: "POST", body: JSON.stringify({ email }) },
    false,
  );
}

export async function resetPassword(
  token: string,
  newPassword: string,
): Promise<{ status: string; message: string }> {
  return apiFetch(
    "/users/reset-password",
    { method: "POST", body: JSON.stringify({ token, new_password: newPassword }) },
    false,
  );
}
