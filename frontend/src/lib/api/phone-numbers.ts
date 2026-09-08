import { apiFetch } from "@/lib/api/http";
import type { PhoneNumberInventoryResponse, PhoneNumberItem } from "@/lib/api-types";

/** All phone numbers in the caller's active organisation's inventory. */
export async function listPhoneNumbers(): Promise<PhoneNumberItem[]> {
  return apiFetch<PhoneNumberItem[]>("/phone-numbers");
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
