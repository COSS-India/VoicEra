import { apiFetch, apiFetchBlob } from "@/lib/api/http";
import type {
  CampaignAnalyticsResponse,
  CampaignApiResponse,
  CampaignCsvUploadResponse,
  CampaignProgressResponse,
  CampaignRunItem,
  CampaignRunsListResponse,
  CreateCampaignPayload,
} from "@/lib/api-types";

export async function listCampaigns(): Promise<CampaignApiResponse[]> {
  return apiFetch<CampaignApiResponse[]>("/campaign/");
}

export async function getCampaign(campaignId: string): Promise<CampaignApiResponse> {
  return apiFetch<CampaignApiResponse>(`/campaign/${encodeURIComponent(campaignId)}`);
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

export type CampaignRunsQuery = {
  limit?: number;
  offset?: number;
  status?: string;
  call_response?: string;
  created_after?: string;
  created_before?: string;
};

export async function getCampaignRuns(
  campaignId: string,
  params: CampaignRunsQuery = {},
): Promise<CampaignRunsListResponse> {
  const q = new URLSearchParams();
  q.set("limit", String(params.limit ?? 50));
  q.set("offset", String(params.offset ?? 0));
  if (params.status) q.set("status", params.status);
  if (params.call_response) q.set("call_response", params.call_response);
  if (params.created_after) q.set("created_after", params.created_after);
  if (params.created_before) q.set("created_before", params.created_before);
  return apiFetch<CampaignRunsListResponse>(
    `/campaign/${encodeURIComponent(campaignId)}/runs?${q.toString()}`,
  );
}

/** Page through every call for a campaign (exports / bulk downloads). */
export async function listAllCampaignRuns(
  campaignId: string,
  filters: Omit<CampaignRunsQuery, "limit" | "offset"> = {},
  pageSize = 100,
): Promise<CampaignRunItem[]> {
  const all: CampaignRunItem[] = [];
  let offset = 0;
  for (;;) {
    const res = await getCampaignRuns(campaignId, {
      ...filters,
      limit: pageSize,
      offset,
    });
    all.push(...res.calls);
    offset += res.calls.length;
    if (res.calls.length === 0 || offset >= res.total) break;
  }
  return all;
}

export async function getCampaignProgress(campaignId: string): Promise<CampaignProgressResponse> {
  return apiFetch<CampaignProgressResponse>(
    `/campaign/${encodeURIComponent(campaignId)}/progress`,
  );
}

export async function getCampaignAnalytics(campaignId: string): Promise<CampaignAnalyticsResponse> {
  return apiFetch<CampaignAnalyticsResponse>(
    `/campaign/${encodeURIComponent(campaignId)}/analytics`,
  );
}

export async function downloadCampaignReport(
  campaignId: string,
  opts: { created_after?: string; created_before?: string } = {},
): Promise<Blob> {
  const q = new URLSearchParams();
  if (opts.created_after) q.set("created_after", opts.created_after);
  if (opts.created_before) q.set("created_before", opts.created_before);
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return apiFetchBlob(`/campaign/${encodeURIComponent(campaignId)}/report${suffix}`);
}
