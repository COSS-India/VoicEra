import type { CampaignApiResponse, CampaignState } from "@/lib/api-types";
import { humanizeToken } from "@/lib/campaign-artifacts";

export function campaignStateTone(state: CampaignState) {
  if (state === "running") return "live" as const;
  if (state === "completed" || state === "syncing") return "accent" as const;
  if (state === "failed") return "danger" as const;
  return "neutral" as const;
}

export function campaignStateLabel(state: CampaignState): string {
  return humanizeToken(state);
}

export function campaignProgressPct(
  campaign: Pick<CampaignApiResponse, "total_rows" | "processed_rows">,
): number {
  if (!campaign.total_rows) return 0;
  return (campaign.processed_rows / campaign.total_rows) * 100;
}
