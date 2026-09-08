import { apiFetch } from "@/lib/api/http";
import type {
  CampaignApiResponse,
  CampaignCsvUploadResponse,
  CampaignRunItem,
  CreateCampaignPayload,
} from "@/lib/api-types";

export async function listCampaigns(): Promise<CampaignApiResponse[]> {
  return apiFetch<CampaignApiResponse[]>("/campaign/");
}

/** CSV only — returns a source_id to pass straight through to createCampaign. */
export async function uploadCampaignCsv(file: File): Promise<CampaignCsvUploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetch<CampaignCsvUploadResponse>("/campaign/upload", {
    method: "POST",
    body: formData,
  });
}

export async function createCampaign(payload: CreateCampaignPayload): Promise<CampaignApiResponse> {
  return apiFetch<CampaignApiResponse>("/campaign/create", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function startCampaign(campaignId: string): Promise<{ status: string; campaign_id: string }> {
  return apiFetch(`/campaign/${encodeURIComponent(campaignId)}/start`, { method: "POST" });
}

export async function pauseCampaign(campaignId: string): Promise<{ status: string; campaign_id: string }> {
  return apiFetch(`/campaign/${encodeURIComponent(campaignId)}/pause`, { method: "POST" });
}

export async function resumeCampaign(campaignId: string): Promise<{ status: string; campaign_id: string }> {
  return apiFetch(`/campaign/${encodeURIComponent(campaignId)}/resume`, { method: "POST" });
}

export async function redialCampaign(campaignId: string, name: string): Promise<CampaignApiResponse> {
  return apiFetch<CampaignApiResponse>(`/campaign/${encodeURIComponent(campaignId)}/redial`, {
    method: "POST",
    body: JSON.stringify({ name }),
  });
}

export async function deleteCampaign(campaignId: string): Promise<{ status: string; message: string }> {
  return apiFetch(`/campaign/${encodeURIComponent(campaignId)}`, { method: "DELETE" });
}

export async function getCampaignRuns(
  campaignId: string,
  limit = 50,
  offset = 0,
): Promise<CampaignRunItem[]> {
  return apiFetch<CampaignRunItem[]>(
    `/campaign/${encodeURIComponent(campaignId)}/runs?limit=${limit}&offset=${offset}`,
  );
}
