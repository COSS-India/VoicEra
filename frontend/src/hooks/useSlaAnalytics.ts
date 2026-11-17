"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/http";
import {
  getSlaAvailability,
  getSlaBaseDetails,
  getSlaGpu,
  getSlaTelemetry,
  getSlaTelephony,
} from "@/lib/api/sla";
import type {
  SlaBaseDetailsResponse,
  SlaMetricsPayload,
  SlaTelemetryResponse,
} from "@/lib/sla-types";

type NotifyFn = (title: string, note: string) => void;

export function useSlaAnalytics(
  initialCampaignId: string | null | undefined,
  onNotify: NotifyFn,
) {
  const [campaignIdInput, setCampaignIdInput] = useState(
    () => initialCampaignId?.trim() ?? "",
  );
  const [loadedCampaignId, setLoadedCampaignId] = useState<string | null>(null);
  const [baseDetails, setBaseDetails] = useState<SlaBaseDetailsResponse | null>(
    null,
  );
  const [telemetry, setTelemetry] = useState<SlaTelemetryResponse | null>(null);
  const [gpu, setGpu] = useState<SlaMetricsPayload | null>(null);
  const [telephony, setTelephony] = useState<SlaMetricsPayload | null>(null);
  const [availability, setAvailability] = useState<SlaMetricsPayload | null>(
    null,
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const autoLoadedId = useRef<string | null>(null);

  const resetResults = useCallback(() => {
    setBaseDetails(null);
    setTelemetry(null);
    setGpu(null);
    setTelephony(null);
    setAvailability(null);
    setLoadedCampaignId(null);
    setError("");
  }, []);

  const loadCampaign = useCallback(
    async (id: string) => {
      const campaignId = id.trim();
      if (!campaignId) {
        setError("Enter a campaign ID.");
        return;
      }
      setLoading(true);
      setError("");
      try {
        const [baseRes, telemRes, gpuRes, telRes, availRes] = await Promise.all([
          getSlaBaseDetails(campaignId),
          getSlaTelemetry(campaignId),
          getSlaGpu(),
          getSlaTelephony(),
          getSlaAvailability(),
        ]);
        setBaseDetails(baseRes);
        setTelemetry(telemRes);
        setGpu(gpuRes);
        setTelephony(telRes);
        setAvailability(availRes);
        setLoadedCampaignId(campaignId);
        setCampaignIdInput(campaignId);
      } catch (err) {
        resetResults();
        const message =
          err instanceof ApiError && err.status === 404
            ? "Campaign not found for this organisation."
            : err instanceof Error
              ? err.message
              : "Couldn't load SLA analytics.";
        setError(message);
        if (!(err instanceof ApiError && err.status === 404)) {
          onNotify("SLA analytics", message);
        }
      } finally {
        setLoading(false);
      }
    },
    [onNotify, resetResults],
  );

  useEffect(() => {
    const id = initialCampaignId?.trim();
    if (!id || autoLoadedId.current === id) return;
    autoLoadedId.current = id;
    setCampaignIdInput(id);
    void loadCampaign(id);
  }, [initialCampaignId, loadCampaign]);

  return {
    campaignIdInput,
    setCampaignIdInput,
    loadedCampaignId,
    baseDetails,
    telemetry,
    gpu,
    telephony,
    availability,
    loading,
    error,
    loadCampaign,
    resetResults,
  };
}
