/** Types matching apps/api SLA collector response shapes. */

export type SlaMetricStatus = "met" | "missed" | "no_data";
export type SlaOperatingStatus =
  | "working_normally"
  | "not_working_normally"
  | "unknown";
export type SlaMetricScope = "campaign" | "deployment";

export type SlaMetric = {
  key: string;
  label: string;
  target: number;
  comparator: string;
  unit: string;
  actual: number | null;
  status: SlaMetricStatus;
  operating_status: SlaOperatingStatus;
  source: string;
  scope: SlaMetricScope;
  sample_count?: number;
};

export type SlaServiceStatus =
  | "working"
  | "not_working"
  | "unknown"
  | "running"
  | "not_running";

export type SlaServiceCard = {
  id: string;
  label: string;
  scope: SlaMetricScope;
  status: SlaServiceStatus;
  operating_status?: SlaOperatingStatus;
  active_since: string | null;
  down_since: string | null;
  duration_seconds: number | null;
  last_call_at?: string | null;
  call_happened_ago_seconds?: number | null;
  call_happened?: string | null;
  rule?: string;
};

export type SlaBaseDetailsSummary = {
  affected_services: string[];
  started_at: string;
  next_update_at: string;
  expected_fix_by: string;
  session_start_pct?: number | null;
};

export type SlaBaseDetailsResponse = {
  campaign_id: string;
  campaign_name?: string | null;
  pipeline_last_active_at: string | null;
  services: SlaServiceCard[];
  summary: SlaBaseDetailsSummary | null;
};

export type SlaMetricsPayload = {
  scope?: SlaMetricScope;
  source?: string;
  metrics: SlaMetric[];
  campaign_id?: string;
  campaign_name?: string | null;
  call_count?: number;
  reason?: string | null;
  gpus?: unknown[];
  history?: Record<string, unknown>;
  configured?: boolean;
};

export type SlaTelemetryResponse = {
  campaign_id: string;
  campaign_name?: string | null;
  scope: SlaMetricScope;
  call_count: number;
  capacity: { metrics: SlaMetric[] };
  inference: { metrics: SlaMetric[]; gateway?: unknown };
  orchestration: { metrics: SlaMetric[] };
  metrics: SlaMetric[];
};
