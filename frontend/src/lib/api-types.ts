export type UserRole = "super_admin" | "admin" | "member";

export interface OrganisationSummary {
  org_id: string;
  name: string;
  role: UserRole;
}

export interface LoginResponse {
  status: string;
  message: string;
  access_token: string;
  token_type: string;
  org_id: string;
  role: string;
  organisations: OrganisationSummary[];
  is_first_login?: boolean;
}

export interface UserProfile {
  email: string;
  org_id: string;
  role: UserRole;
  organisation_name?: string;
  organisations: OrganisationSummary[];
  created_at?: string;
}

export interface MemberListItem {
  email: string;
  role: UserRole;
  created_at?: string;
}

export interface MemberListResponse {
  status: string;
  members: MemberListItem[];
  count: number;
}

export interface UserOrganisationsResponse {
  status: string;
  organisations: OrganisationSummary[];
  count: number;
}

export interface CheckEmailResult {
  exists: boolean;
  already_in_org: boolean;
  can_join: boolean;
}

export interface AgentApiResponse {
  agent_id: string;
  org_id: string;
  name: string;
  status: "active" | "archived";
  archived: boolean;
  agent_category: "telephony" | "websocket";
  created_by: string;
  linked_phone_number: string | null;
  telephony: {
    provider: string;
    application_id: string;
    answer_url: string;
    hangup_url?: string | null;
  } | null;
  config: {
    schema_version: number;
    prompts: {
      system_prompt: string;
      greeting_message: string;
    };
    behaviour: Record<string, unknown>;
    language: {
      primary: string;
      secondary: string[];
    };
    models: {
      stt_config: Record<string, unknown>;
      tts_config: Record<string, unknown>;
      llm_config: Record<string, unknown>;
    };
    knowledge_base: {
      enabled: boolean;
      document_ids: string[];
      top_k: number;
    };
    custom_variables?: Record<string, string>;
  };
  created_at?: string;
  updated_at?: string;
}

export interface AgentCreatePayload {
  name: string;
  agent_category: "telephony" | "websocket";
  telephony_provider?: string | null;
  config: AgentApiResponse["config"];
  archived?: boolean;
}

export interface PhoneNumberItem {
  phone_number: string;
  provider: string;
  org_id: string;
  agent_id?: string | null;
  created_at?: string;
  updated_at?: string;
  last_link_action?: "attached" | "detached" | "imported" | string | null;
  last_link_agent_id?: string | null;
  last_link_by_email?: string | null;
  last_link_at?: string | null;
}

export interface PhoneNumberInventoryResponse {
  status: string;
  numbers: string[];
}

export type CallLogStatus = "initiated" | "ringing" | "failed" | "in_progress" | "completed";

export type CallType = "inbound" | "outbound" | "web";

export type CallResponseStatus = "pending" | "answered" | "busy" | "no_answer" | "failed" | "cancelled";

export interface OutboundCallRequest {
  agent_id: string;
  to_number: string;
  from_number?: string;
  custom_variables?: Record<string, unknown>;
}

export interface OutboundCallResponse {
  call_id: string;
  status: CallLogStatus;
  provider_call_sid?: string | null;
  from_number: string;
  to_number: string;
  agent_id: string;
  custom_variables: Record<string, unknown>;
}

export interface WebCallRegisterRequest {
  agent_id: string;
  custom_variables?: Record<string, unknown>;
}

export interface WebCallRegisterResponse {
  call_id: string;
  status: CallLogStatus;
  call_type: CallType;
  agent_id: string;
  custom_variables: Record<string, unknown>;
}

export type KnowledgeDocumentStatus = "processing" | "ready" | "failed";

export interface KnowledgeDocumentItem {
  document_id: string;
  org_id: string;
  original_filename: string;
  status: KnowledgeDocumentStatus;
  chunk_count?: number | null;
  embedding_model?: string | null;
  storage_key?: string | null;
  error_message?: string | null;
  created_at: string;
  updated_at: string;
}

export interface CallLogItem {
  call_id: string;
  org_id: string;
  agent_id: string;
  agent_name?: string | null;
  call_type: CallType;
  status: CallLogStatus;
  call_response?: CallResponseStatus | null;
  from_number: string;
  to_number: string;
  telephony_provider?: string | null;
  provider_call_sid?: string | null;
  custom_variables: Record<string, unknown>;
  created_at?: string | null;
  updated_at?: string | null;
  start_time_utc?: string | null;
  end_time_utc?: string | null;
  duration?: number | null;
  recording_url?: string | null;
  transcript_url?: string | null;
  error_message?: string | null;
  campaign_id?: string | null;
  queued_run_id?: string | null;
}

export interface CallLogListResponse {
  calls: CallLogItem[];
  limit: number;
  offset: number;
  total: number;
}

/** turns[] has two entries per turn_number: a "started" record and a
 * "duration_secs/was_interrupted" record written when the turn ends. */
export interface CallMetricsTurnRecord {
  turn_number: number;
  started?: boolean;
  duration_secs?: number;
  was_interrupted?: boolean;
}

export interface CallMetricsTtfbEntry {
  processor: string;
  model: string;
  start_time: number;
  duration_secs: number;
  /** Pipeline role stamped at write time (stt/llm/tts). Prefer over name heuristics. */
  stage?: "stt" | "llm" | "tts";
}

/** breakdowns[] aligns positionally with turns[] (breakdowns[i] ↔ turn_number i+1).
 * A null user_turn_start_time means the entry is bot-initiated speech (e.g. an
 * opening greeting), not a real user turn. */
export interface CallMetricsBreakdown {
  ttfb: CallMetricsTtfbEntry[];
  text_aggregation?: { processor: string; start_time: number; duration_secs: number } | null;
  user_turn_start_time?: number | null;
  user_turn_secs?: number | null;
  function_calls?: unknown[];
}

export interface CallMetricsResponse {
  call_id: string;
  org_id: string;
  recorded_at: string;
  summary: {
    turn_count?: number;
    interrupted_turn_count?: number;
    user_bot_latency_avg_secs?: number;
    user_bot_latency_min_secs?: number;
    user_bot_latency_max_secs?: number;
    /** Computed server-side (not stored) from the ttfb breakdowns at read
     * time: the sum of whichever of avg_stt/avg_tts/avg_llm are available. */
    avg_stt_secs?: number | null;
    avg_tts_secs?: number | null;
    avg_llm_secs?: number | null;
    avg_latency_secs?: number | null;
    [key: string]: unknown;
  };
  transport?: {
    start_time?: number;
    bot_connected_secs?: number | null;
    client_connected_secs?: number;
    [key: string]: unknown;
  } | null;
  turns: CallMetricsTurnRecord[];
  latencies: {
    first_bot_speech_secs?: number;
    user_to_bot_secs?: number[];
    breakdowns?: CallMetricsBreakdown[];
    [key: string]: unknown;
  };
}

export interface ProviderAuthResponse {
  org_id: string;
  provider: string;
  auth: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
}

export type CampaignState = "created" | "syncing" | "running" | "paused" | "completed" | "failed";

export interface CampaignApiResponse {
  campaign_id: string;
  org_id: string;
  name: string;
  agent_id: string;
  source_type: string;
  source_id: string;
  state: CampaignState;
  total_rows: number;
  processed_rows: number;
  failed_rows: number;
  rate_limit_per_second: number;
  retry_config: Record<string, unknown>;
  orchestrator_metadata: Record<string, unknown>;
  from_number?: string | null;
  created_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface CampaignCsvUploadResponse {
  source_id: string;
  filename: string;
  contact_rows: number;
}

export interface CampaignRetryConfig {
  enabled: boolean;
  max_retries: number;
  retry_delay_seconds: number;
  retry_on_busy: boolean;
  retry_on_no_answer: boolean;
  retry_on_voicemail: boolean;
}

export interface CampaignScheduleSlot {
  day_of_week: number;
  start_time: string;
  end_time: string;
}

export interface CampaignScheduleConfig {
  enabled: boolean;
  timezone: string;
  slots: CampaignScheduleSlot[];
}

export interface CreateCampaignPayload {
  name: string;
  agent_id: string;
  source_type: string;
  source_id: string;
  rate_limit_per_second?: number;
  max_concurrency?: number;
  from_number?: string | null;
  retry_config?: CampaignRetryConfig;
}

/** GET /campaign/{id}/runs returns raw call-log dicts server-side — only a
 * loose shape is guaranteed, so treat unlisted fields as unknown. */
export interface CampaignRunItem {
  call_id?: string;
  to_number?: string;
  status?: string;
  call_response?: string | null;
  duration?: number | null;
  created_at?: string | null;
  [key: string]: unknown;
}

export interface AgentCallCount {
  agent_id: string | null;
  agent_name: string | null;
  call_count: number;
}

export interface ModelUsageEntry {
  model: string | null;
  provider: string | null;
  call_count: number;
}

export interface ModelUsageSummary {
  stt: ModelUsageEntry | null;
  tts: ModelUsageEntry | null;
  llm: ModelUsageEntry | null;
}

export interface CallAnalyticsResponse {
  calls_attempted: number;
  calls_connected: number;
  calls_failed: number;
  connection_rate: number;
  total_duration_seconds: number;
  average_duration_seconds: number;
  trend_vs_last_week_pct: number | null;
  agent_performance: AgentCallCount[];
  model_usage: ModelUsageSummary;
}
