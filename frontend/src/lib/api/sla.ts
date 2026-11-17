import { apiFetch } from "@/lib/api/http";
import type {
  SlaBaseDetailsResponse,
  SlaMetricsPayload,
  SlaTelemetryResponse,
} from "@/lib/sla-types";

export async function getSlaBaseDetails(
  campaignId: string,
): Promise<SlaBaseDetailsResponse> {
  return apiFetch<SlaBaseDetailsResponse>(
    `/sla/campaigns/${encodeURIComponent(campaignId)}/base-details`,
  );
}

export async function getSlaTelemetry(
  campaignId: string,
): Promise<SlaTelemetryResponse> {
  return apiFetch<SlaTelemetryResponse>(
    `/sla/campaigns/${encodeURIComponent(campaignId)}/telemetry`,
  );
}

export async function getSlaGpu(): Promise<SlaMetricsPayload> {
  return apiFetch<SlaMetricsPayload>("/sla/gpu");
}

export async function getSlaTelephony(): Promise<SlaMetricsPayload> {
  return apiFetch<SlaMetricsPayload>("/sla/telephony");
}

export async function getSlaAvailability(): Promise<SlaMetricsPayload> {
  return apiFetch<SlaMetricsPayload>("/sla/availability");
}
