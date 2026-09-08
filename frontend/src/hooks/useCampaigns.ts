"use client";

import { useCallback, useEffect, useState } from "react";
import {
  createCampaign,
  deleteCampaign,
  listCampaigns,
  pauseCampaign,
  redialCampaign,
  resumeCampaign,
  startCampaign,
  uploadCampaignCsv,
} from "@/lib/api/campaigns";
import type { CampaignApiResponse, CampaignCsvUploadResponse, CreateCampaignPayload } from "@/lib/api-types";

const POLL_INTERVAL_MS = 5000;

export function useCampaigns(onNotify: (title: string, note: string) => void) {
  const [campaigns, setCampaigns] = useState<CampaignApiResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError("");
    try {
      const res = await listCampaigns();
      setCampaigns(res);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Couldn't load campaigns.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Progress (processed_rows/total_rows) only moves while dialing is actually
  // happening server-side — poll the list so cards stay live without a
  // per-card /progress call.
  const hasActive = campaigns.some((c) => c.state === "running" || c.state === "syncing");
  useEffect(() => {
    if (!hasActive) return;
    const id = window.setInterval(load, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [hasActive, load]);

  async function uploadCsv(file: File): Promise<CampaignCsvUploadResponse | null> {
    setUploading(true);
    try {
      return await uploadCampaignCsv(file);
    } catch (err) {
      onNotify("Couldn't upload CSV", err instanceof Error ? err.message : "Something went wrong.");
      return null;
    } finally {
      setUploading(false);
    }
  }

  async function create(payload: CreateCampaignPayload): Promise<boolean> {
    setCreating(true);
    try {
      const campaign = await createCampaign(payload);
      setCampaigns((prev) => [campaign, ...prev]);
      onNotify("Campaign created", `${campaign.name} is ready to start.`);
      return true;
    } catch (err) {
      onNotify("Couldn't create campaign", err instanceof Error ? err.message : "Something went wrong.");
      return false;
    } finally {
      setCreating(false);
    }
  }

  async function runAction(
    campaignId: string,
    action: (id: string) => Promise<unknown>,
    successTitle: string,
    successNote: string,
  ): Promise<boolean> {
    setBusyId(campaignId);
    try {
      await action(campaignId);
      onNotify(successTitle, successNote);
      await load();
      return true;
    } catch (err) {
      onNotify(`Couldn't ${successTitle.toLowerCase()}`, err instanceof Error ? err.message : "Something went wrong.");
      return false;
    } finally {
      setBusyId(null);
    }
  }

  const start = (campaignId: string) => runAction(campaignId, startCampaign, "Started", "Calls are being placed.");
  const pause = (campaignId: string) => runAction(campaignId, pauseCampaign, "Paused", "Dialing has been paused.");
  const resume = (campaignId: string) => runAction(campaignId, resumeCampaign, "Resumed", "Dialing has resumed.");
  const remove = (campaignId: string) =>
    runAction(campaignId, deleteCampaign, "Deleted", "The campaign was removed.");

  async function redial(campaignId: string, name: string): Promise<boolean> {
    setBusyId(campaignId);
    try {
      const child = await redialCampaign(campaignId, name);
      setCampaigns((prev) => [child, ...prev]);
      onNotify("Redial campaign created", `${child.name} is ready to start.`);
      return true;
    } catch (err) {
      onNotify("Couldn't create redial campaign", err instanceof Error ? err.message : "Something went wrong.");
      return false;
    } finally {
      setBusyId(null);
    }
  }

  return {
    campaigns,
    loading,
    loadError,
    uploading,
    creating,
    busyId,
    uploadCsv,
    create,
    start,
    pause,
    resume,
    redial,
    remove,
    reload: load,
  };
}
