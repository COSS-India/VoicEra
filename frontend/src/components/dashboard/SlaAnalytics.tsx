"use client";

import { useEffect, useMemo, useState } from "react";
import { ClipboardCheck } from "lucide-react";
import { SlaOverviewTab } from "@/components/dashboard/sla/SlaOverviewTab";
import { SlaPerformanceTab } from "@/components/dashboard/sla/SlaPerformanceTab";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Field";
import { SearchSelect } from "@/components/ui/SearchSelect";
import { Spinner } from "@/components/ui/Spinner";
import { useAuth } from "@/components/AuthProvider";
import { useSlaAnalytics } from "@/hooks/useSlaAnalytics";
import { listCampaigns } from "@/lib/api/campaigns";
import type { CampaignApiResponse } from "@/lib/api-types";

type Tab = "overview" | "performance";

type Props = {
  initialCampaignId?: string | null;
  onNotify: (title: string, note: string) => void;
};

export function SlaAnalytics({ initialCampaignId, onNotify }: Props) {
  const { session } = useAuth();
  const [tab, setTab] = useState<Tab>("overview");
  const [campaigns, setCampaigns] = useState<CampaignApiResponse[]>([]);
  const [campaignsLoading, setCampaignsLoading] = useState(false);

  const {
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
  } = useSlaAnalytics(initialCampaignId, onNotify);

  useEffect(() => {
    if (!session?.accessToken) return;
    let cancelled = false;
    setCampaignsLoading(true);
    listCampaigns()
      .then((rows) => {
        if (!cancelled) setCampaigns(rows);
      })
      .catch(() => {
        if (!cancelled) setCampaigns([]);
      })
      .finally(() => {
        if (!cancelled) setCampaignsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [session?.accessToken]);

  const campaignOptions = useMemo(
    () =>
      campaigns.map((c) => ({
        value: c.campaign_id,
        label: `${c.name || "Untitled"} · ${c.campaign_id}`,
      })),
    [campaigns],
  );

  const campaignName =
    baseDetails?.campaign_name || telemetry?.campaign_name || null;

  return (
    <div className="flex w-full flex-col gap-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-col gap-1">
          <h1 className="flex items-center gap-2 text-[22px] font-extrabold tracking-[-.4px] text-v-fg">
            <ClipboardCheck className="size-5 shrink-0 text-v-accent" strokeWidth={1.8} />
            SLA analytics
          </h1>
          <p className="text-sm text-v-muted">
            Campaign health overview and agreed targets versus actuals.
          </p>
        </div>

        <div className="inline-flex rounded-v-md border border-v-line bg-v-soft p-1">
          {(
            [
              { id: "overview", label: "Overview" },
              { id: "performance", label: "Performance" },
            ] as const
          ).map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setTab(item.id)}
              className={`cursor-pointer rounded-v-sm px-3.5 py-1.5 text-[13px] font-medium transition-colors ${
                tab === item.id
                  ? "bg-v-panel text-v-fg shadow-[var(--v-shadow-card)]"
                  : "text-v-muted hover:text-v-fg"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-col gap-3 rounded-v-md border border-v-line bg-v-soft/40 p-4">
        <span className="text-[13px] font-medium text-v-body">
          Select a campaign to load SLA details for that campaign.
        </span>
        <div className="flex flex-wrap items-end gap-2">
          <label className="flex min-w-[16rem] flex-1 flex-col gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
              Campaign
            </span>
            <SearchSelect
              options={campaignOptions}
              value={campaignIdInput}
              onChange={setCampaignIdInput}
              placeholder={
                campaignsLoading ? "Loading campaigns…" : "Search campaigns"
              }
              disabled={campaignsLoading && campaignOptions.length === 0}
            />
          </label>
          <label className="flex min-w-[14rem] flex-1 flex-col gap-1.5">
            <span className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
              Campaign ID
            </span>
            <Input
              value={campaignIdInput}
              onChange={(e) => setCampaignIdInput(e.target.value)}
              placeholder="Paste campaign id"
              className="font-mono text-[13px]"
              onKeyDown={(e) => {
                if (e.key === "Enter") void loadCampaign(campaignIdInput);
              }}
            />
          </label>
          <Button
            type="button"
            onClick={() => void loadCampaign(campaignIdInput)}
            disabled={loading || !campaignIdInput.trim()}
          >
            {loading ? "Loading…" : "Load"}
          </Button>
        </div>
        {campaignName && loadedCampaignId ? (
          <p className="text-xs text-v-muted">
            Showing{" "}
            <span className="font-medium text-v-fg">{campaignName}</span>
            <span className="font-mono text-v-faint"> · {loadedCampaignId}</span>
          </p>
        ) : null}
      </div>

      {error ? (
        <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center justify-center gap-2 py-16 text-sm text-v-muted">
          <Spinner />
          Loading SLA analytics…
        </div>
      ) : null}

      {!loading && !baseDetails && !error ? (
        <div className="flex flex-col items-center gap-1 rounded-v-md border border-dashed border-v-line bg-white p-12 text-center">
          <span className="text-sm font-semibold">No campaign loaded</span>
          <span className="text-xs font-light text-v-muted">
            Pick a campaign above and press Load to see overview and performance.
          </span>
        </div>
      ) : null}

      {!loading && baseDetails && tab === "overview" ? (
        <SlaOverviewTab data={baseDetails} />
      ) : null}

      {!loading && loadedCampaignId && tab === "performance" ? (
        <SlaPerformanceTab
          telemetry={telemetry}
          gpu={gpu}
          telephony={telephony}
          availability={availability}
        />
      ) : null}
    </div>
  );
}
