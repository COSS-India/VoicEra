import { apiFetch } from "@/lib/api/http";
import type {
  PhoneNumberActivityResponse,
  PhoneNumberInventoryResponse,
  PhoneNumberItem,
} from "@/lib/api-types";

/** All phone numbers in the caller's active organisation's inventory. */
export async function listPhoneNumbers(): Promise<PhoneNumberItem[]> {
  return apiFetch<PhoneNumberItem[]>("/phone-numbers");
}

/** Append-only import/attach/detach/remove activity for the active organisation. */
export async function listPhoneNumberActivity(
  { limit = 50, offset = 0 }: { limit?: number; offset?: number } = {},
): Promise<PhoneNumberActivityResponse> {
  return apiFetch<PhoneNumberActivityResponse>(
    `/phone-numbers/activity?limit=${limit}&offset=${offset}`,
  );
}

/** Numbers on the org's telephony provider account (not necessarily imported yet). */
export async function listProviderInventory(provider: string): Promise<string[]> {
  const res = await apiFetch<PhoneNumberInventoryResponse>(
    `/phone-numbers/providers/${encodeURIComponent(provider)}/inventory`,
  );
  return res.numbers;
}

/** Adds the number to the org inventory, and links it to `agentId` when given. */
export async function attachPhoneNumber(
  phoneNumber: string,
  provider: string,
  agentId?: string,
): Promise<{ status: string; message: string }> {
  return apiFetch("/phone-numbers/attach", {
    method: "POST",
    body: JSON.stringify({ phone_number: phoneNumber, provider, agent_id: agentId ?? null }),
  });
}

/** Detaches from its agent and unlinks at the telephony provider; keeps the inventory row. */
export async function detachPhoneNumber(phoneNumber: string): Promise<{ status: string; message: string }> {
  return apiFetch("/phone-numbers/detach", {
    method: "DELETE",
    body: JSON.stringify({ phone_number: phoneNumber }),
  });
}

/** Removes the number from org inventory (detaches first if attached). Does not release it at the provider. */
export async function removePhoneNumber(phoneNumber: string): Promise<{ status: string; message: string }> {
  return apiFetch("/phone-numbers/remove", {
    method: "DELETE",
    body: JSON.stringify({ phone_number: phoneNumber }),
  });
}
