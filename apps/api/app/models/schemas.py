"""Pydantic request/response schemas for auth and membership."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field

Role = Literal["super_admin", "admin", "member"]


class UserCreate(BaseModel):
    """Schema for creating a new user and organisation."""

    email: EmailStr
    password: str
    organisation_name: str


class OrganisationSummary(BaseModel):
    """Organisation entry for login / list responses."""

    org_id: str
    name: str
    role: Role


class UserResponse(BaseModel):
    """Schema for authenticated user profile."""

    email: str
    org_id: str
    role: Role
    organisation_name: Optional[str] = None
    organisations: list[OrganisationSummary] = []
    created_at: Optional[str] = None


class UserLogin(BaseModel):
    """Schema for user login."""

    email: EmailStr
    password: str


class UserLoginResponse(BaseModel):
    """Schema for login / switch-organisation response."""

    status: str
    message: str
    access_token: Optional[str] = None
    token_type: Optional[str] = None
    org_id: Optional[str] = None
    role: Optional[Role] = None
    organisations: list[OrganisationSummary] = []
    is_first_login: bool = False


class SwitchOrganisationRequest(BaseModel):
    """Switch the active organisation in the JWT."""

    org_id: str


class ForgotPasswordRequest(BaseModel):
    """Schema for forgot-password request."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Schema for password reset with token."""

    token: str
    new_password: str


class SuccessResponse(BaseModel):
    """Generic success response."""

    status: str = "success"
    message: str


class ErrorResponse(BaseModel):
    """Generic error response."""

    status: str = "fail"
    message: str


class MemberInvite(BaseModel):
    """Invite a user into the caller's active organisation."""

    email: EmailStr
    password: str


class MemberJoin(BaseModel):
    """Public self-serve join into an organisation via invite link (org_id as code)."""

    email: EmailStr
    password: str
    org_id: str


class MemberListItem(BaseModel):
    """One membership row for an organisation."""

    email: str
    role: Role
    created_at: Optional[str] = None


class AssignAdminRequest(BaseModel):
    """Promote a member to admin in the active organisation."""

    email: EmailStr


class RemoveMemberRequest(BaseModel):
    """Remove a member from the active organisation."""

    email: EmailStr


class CheckEmailResponse(BaseModel):
    """Invite UI helper: whether email exists and is already in an org."""

    exists: bool
    already_in_org: bool = False
    can_join: bool = True


class ProviderAuthUpsert(BaseModel):
    """Upsert org-scoped credentials for a provider."""

    provider: str
    auth: dict[str, Any]


class ProviderAuthResponse(BaseModel):
    """Stored provider auth for an organisation."""

    org_id: str
    provider: str
    auth: dict[str, Any]
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class BotTokenRequest(BaseModel):
    """Service request: exchange internal key for an org-scoped JWT."""

    org_id: str


class BotTokenResponse(BaseModel):
    """Bot bootstrap: org-scoped JWT for subsequent API calls."""

    access_token: str
    token_type: str = "bearer"
    org_id: str
    role: Role


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

AgentCategory = Literal["telephony", "websocket"]
AgentStatus = Literal["active", "archived"]
# Registered telephony provider id (see apps.telephony registry / GET /configuration).
TelephonyProvider = str


class AgentPrompts(BaseModel):
    """Prompt fields stored on an agent."""

    system_prompt: str = ""
    greeting_message: str


class AutomaticCallEnding(BaseModel):
    """Graceful call ending via LLM tool (Pipecat end_conversation pattern)."""

    enabled: bool = False
    graceful_llm_call_ending: bool = False


class AgentBehaviour(BaseModel):
    """Call / turn behaviour settings (aligned with mono voice-server knobs)."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "interruption_min_words": 2,
                    "user_silence_hangup_seconds": 30,
                    "call_timeout_seconds": 600,
                    "ignore_user_speech_before_greeting": True,
                    "hold_messages": ["One moment please."],
                    "hold_message_timeout_seconds": 0.6,
                    "user_online_detection_enabled": False,
                    "user_online_detection_message": "",
                    "user_online_detection_seconds": 10,
                    "user_online_detection_repeats": 1,
                    "user_online_detection_closing_message": "",
                    "automatic_call_ending": {
                        "enabled": True,
                        "graceful_llm_call_ending": True,
                    },
                }
            ]
        }
    )

    interruption_min_words: int = Field(
        default=0,
        ge=0,
        description="Minimum words before the caller can interrupt the agent.",
    )
    user_silence_hangup_seconds: float | None = Field(
        default=None,
        ge=0,
        description="Hang up after this many seconds of user silence (null = disabled).",
    )
    call_timeout_seconds: float | None = Field(
        default=None,
        ge=0,
        description="Maximum call duration in seconds (null = no hard limit).",
    )
    ignore_user_speech_before_greeting: bool = Field(
        default=False,
        description="Ignore caller speech until the greeting has finished playing.",
    )
    hold_messages: list[str] = Field(
        default_factory=list,
        description="Messages played while the agent is on hold / thinking.",
    )
    hold_message_timeout_seconds: float | None = Field(
        default=None,
        ge=0,
        description="Seconds to wait after LLM inference starts before playing a single hold message (null = disabled).",
    )
    user_online_detection_enabled: bool = Field(
        default=False,
        description="Prompt the caller after silence following bot speech.",
    )
    user_online_detection_message: str = Field(
        default="",
        description="Prompt played when checking if the user is still online.",
    )
    user_online_detection_seconds: float | None = Field(
        default=None,
        ge=0,
        description="Seconds of silence after bot speech before the online-detection prompt.",
    )
    user_online_detection_repeats: int | None = Field(
        default=None,
        ge=1,
        description="How many times to speak the online-detection prompt in one silence cycle.",
    )
    user_online_detection_closing_message: str = Field(
        default="",
        description="Spoken after the last online-detection prompt, before hangup.",
    )
    automatic_call_ending: AutomaticCallEnding = AutomaticCallEnding()


class AgentLanguage(BaseModel):
    """Primary and secondary languages for the agent."""

    primary: str
    secondary: list[str] = []


KnowledgeBaseMode = Literal["tool", "context"]


class AgentKnowledgeBase(BaseModel):
    """Optional knowledge-base attachment."""

    enabled: bool = False
    mode: KnowledgeBaseMode = "context"
    document_ids: list[str] = []
    top_k: int = Field(default=5, ge=1, le=10)


class AgentModels(BaseModel):
    """STT / TTS / LLM configs (non-secret fields only)."""

    stt_config: dict[str, Any]
    tts_config: dict[str, Any]
    llm_config: dict[str, Any]


class AgentConfigPayload(BaseModel):
    """Typed agent behaviour + AI config blob."""

    schema_version: int = 1
    prompts: AgentPrompts
    behaviour: AgentBehaviour = AgentBehaviour()
    language: AgentLanguage
    models: AgentModels
    knowledge_base: AgentKnowledgeBase = AgentKnowledgeBase()
    custom_variables: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Named variables available at call time; values are defaults "
            "overridden by per-call custom_variables on outbound calls."
        ),
    )


class AgentCreateRequest(BaseModel):
    """Create an agent in the caller's active organisation."""

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "name": "Support Agent",
                    "agent_category": "telephony",
                    "telephony_provider": "vobiz",
                    "config": {
                        "schema_version": 1,
                        "prompts": {
                            "system_prompt": "You are a helpful phone support agent.",
                            "greeting_message": "Hello! How can I help you today?",
                        },
                        "behaviour": {
                            "interruption_min_words": 2,
                            "user_silence_hangup_seconds": 30,
                            "call_timeout_seconds": 600,
                            "ignore_user_speech_before_greeting": True,
                            "hold_messages": ["One moment please."],
                            "hold_message_timeout_seconds": 0.6,
                            "user_online_detection_enabled": False,
                            "user_online_detection_message": "",
                            "user_online_detection_seconds": 10,
                            "user_online_detection_repeats": 1,
                            "user_online_detection_closing_message": "",
                            "automatic_call_ending": {
                                "enabled": True,
                                "graceful_llm_call_ending": True,
                            },
                        },
                        "language": {"primary": "en", "secondary": []},
                        "models": {
                            "stt_config": {
                                "provider": "deepgram",
                                "model": "nova-3-general",
                                "language": "en",
                            },
                            "tts_config": {
                                "provider": "cartesia",
                                "model": "sonic-3.5",
                                "language": "en",
                                "voice": "3faa81ae-d3d8-4ab1-9e44-e50e46d33c30",
                                "speed": 1.0,
                                "volume": 1.0,
                            },
                            "llm_config": {
                                "provider": "openai",
                                "model": "gpt-4.1",
                            },
                        },
                        "knowledge_base": {
                            "enabled": False,
                            "mode": "context",
                            "document_ids": [],
                            "top_k": 5,
                        },
                        "custom_variables": {
                            "customer_name": "",
                            "account_id": "unknown",
                        },
                    },
                }
            ]
        }
    )

    name: str
    agent_category: AgentCategory
    telephony_provider: Optional[TelephonyProvider] = None
    config: AgentConfigPayload


class AgentUpdateRequest(BaseModel):
    """Partial update for an agent in the caller's active organisation."""

    name: Optional[str] = None
    agent_category: Optional[AgentCategory] = None
    telephony_provider: Optional[TelephonyProvider] = None
    config: Optional[AgentConfigPayload] = None
    archived: Optional[bool] = None


class AgentTelephonyAttachment(BaseModel):
    """Provider application attachment (null until telephony slice)."""

    provider: str
    application_id: str
    answer_url: str
    # Optional for agents provisioned before hangup URLs were always set.
    hangup_url: Optional[str] = None


class AgentResponse(BaseModel):
    """Full agent document returned by the API."""

    agent_id: str
    org_id: str
    name: str
    status: AgentStatus
    archived: bool = False
    agent_category: AgentCategory
    created_by: str
    linked_phone_number: Optional[str] = None
    telephony: Optional[AgentTelephonyAttachment] = None
    config: AgentConfigPayload
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Phone numbers
# ---------------------------------------------------------------------------


class PhoneNumberAttachRequest(BaseModel):
    """Attach a phone number to the org inventory and optionally to an agent."""

    phone_number: str
    provider: TelephonyProvider
    agent_id: Optional[str] = None


class PhoneNumberDetachRequest(BaseModel):
    """Detach a phone number from its agent (keeps org inventory row)."""

    phone_number: str


class PhoneNumberResponse(BaseModel):
    """Phone number inventory document."""

    phone_number: str
    provider: str
    org_id: str
    agent_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    last_link_action: Optional[str] = None
    last_link_agent_id: Optional[str] = None
    last_link_by_email: Optional[str] = None
    last_link_at: Optional[str] = None


class PhoneNumberInventoryResponse(BaseModel):
    """Provider account phone numbers (not necessarily in org inventory)."""

    status: str = "success"
    numbers: list[str] = []


# ---------------------------------------------------------------------------
# Call logs / outbound calls
# ---------------------------------------------------------------------------

CallLogStatus = Literal[
    "initiated",
    "ringing",
    "failed",
    "in_progress",
    "completed",
]
CallType = Literal["inbound", "outbound", "web"]
CallResponse = Literal[
    "pending",
    "answered",
    "busy",
    "no_answer",
    "failed",
    "cancelled",
]


class OutboundCallRequest(BaseModel):
    """Initiate an outbound call to a customer number."""

    agent_id: str
    to_number: str = Field(..., description="Customer / callee phone number")
    from_number: Optional[str] = Field(
        default=None,
        description="Optional caller ID override",
    )
    custom_variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary per-call variables passed to the agent runtime",
    )

    model_config = ConfigDict(
        populate_by_name=True,
        json_schema_extra={
            "examples": [
                {
                    "agent_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
                    "to_number": "+14155551234",
                    "from_number": "+14155559999",
                    "custom_variables": {
                        "customer_name": "Jane Doe",
                        "account_id": "ACC-123",
                    },
                }
            ]
        },
    )


class OutboundCallResponse(BaseModel):
    """Response after initiating an outbound call."""

    call_id: str
    status: CallLogStatus
    provider_call_sid: Optional[str] = None
    from_number: str
    to_number: str
    agent_id: str
    custom_variables: dict[str, Any] = Field(default_factory=dict)


class InboundCallRegisterRequest(BaseModel):
    """Register an inbound call from the voice runtime answer webhook."""

    agent_id: str
    provider_call_sid: str
    from_number: str
    to_number: str


class InboundCallRegisterResponse(BaseModel):
    """Response after registering an inbound call."""

    call_id: str
    status: CallLogStatus
    provider_call_sid: str
    call_type: CallType
    from_number: str
    to_number: str
    agent_id: str


class WebCallRegisterRequest(BaseModel):
    """Register a browser websocket session."""

    agent_id: str
    custom_variables: dict[str, Any] = Field(default_factory=dict)


class WebCallRegisterResponse(BaseModel):
    """Response after registering a browser websocket session."""

    call_id: str
    status: CallLogStatus
    call_type: CallType
    agent_id: str
    custom_variables: dict[str, Any] = Field(default_factory=dict)


class CallLogUpdateRequest(BaseModel):
    """Partial update for call artifact URLs, end-of-call timing, or disposition."""

    transcript_url: Optional[str] = None
    recording_url: Optional[str] = None
    end_time_utc: Optional[str] = None
    status: Optional[CallLogStatus] = None
    call_response: Optional[CallResponse] = None


class CallMetricsBody(BaseModel):
    """Pipeline metrics payload written at call end."""

    summary: dict[str, Any] = Field(default_factory=dict)
    transport: Optional[dict[str, Any]] = None
    turns: list[dict[str, Any]] = Field(default_factory=list)
    latencies: dict[str, Any] = Field(default_factory=dict)


class CallMetricsResponse(BaseModel):
    """Metrics stored for one call."""

    call_id: str
    org_id: str
    recorded_at: str
    summary: dict[str, Any] = Field(default_factory=dict)
    transport: Optional[dict[str, Any]] = None
    turns: list[dict[str, Any]] = Field(default_factory=list)
    latencies: dict[str, Any] = Field(default_factory=dict)


class CallLogResponse(BaseModel):
    """Full call log document (for future GET endpoints)."""

    call_id: str
    org_id: str
    agent_id: str
    agent_name: Optional[str] = None
    call_type: CallType
    status: CallLogStatus
    call_response: Optional[CallResponse] = None
    from_number: str
    to_number: str
    telephony_provider: Optional[str] = None
    provider_call_sid: Optional[str] = None
    custom_variables: dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    start_time_utc: Optional[str] = None
    end_time_utc: Optional[str] = None
    duration: Optional[float] = None
    recording_url: Optional[str] = None
    transcript_url: Optional[str] = None
    error_message: Optional[str] = None
    campaign_id: Optional[str] = None
    queued_run_id: Optional[str] = None


class CallLogListResponse(BaseModel):
    """Paginated call logs for an organisation."""

    calls: list[CallLogResponse] = Field(default_factory=list)
    limit: int
    offset: int
    total: int


class AgentCallCount(BaseModel):
    """One row of the per-agent call-volume breakdown."""

    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    call_count: int = 0


class ModelUsageEntry(BaseModel):
    """The most-used model for one pipeline stage, ranked by call volume
    (not by how many agents happen to be configured with it)."""

    model: Optional[str] = None
    provider: Optional[str] = None
    call_count: int = 0


class ModelUsageSummary(BaseModel):
    """Most-used STT/TTS/LLM model across the org's calls."""

    stt: Optional[ModelUsageEntry] = None
    tts: Optional[ModelUsageEntry] = None
    llm: Optional[ModelUsageEntry] = None


class CallAnalyticsResponse(BaseModel):
    """Org-wide call analytics: all-time volume plus a trailing-week trend."""

    calls_attempted: int
    calls_connected: int
    calls_failed: int = 0
    connection_rate: float = 0.0
    total_duration_seconds: float = 0.0
    average_duration_seconds: float = 0.0
    trend_vs_last_week_pct: Optional[float] = None
    agent_performance: list[AgentCallCount] = Field(default_factory=list)
    model_usage: ModelUsageSummary = Field(default_factory=ModelUsageSummary)


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

CampaignState = Literal[
    "created",
    "syncing",
    "running",
    "paused",
    "completed",
    "failed",
]


class RetryConfigRequest(BaseModel):
    enabled: bool = True
    max_retries: int = Field(default=2, ge=0, le=10)
    retry_delay_seconds: int = Field(default=120, ge=30, le=3600)
    retry_on_busy: bool = True
    retry_on_no_answer: bool = True
    retry_on_voicemail: bool = False


class ScheduleSlotRequest(BaseModel):
    day_of_week: int = Field(..., ge=0, le=6, description="0=Monday, 6=Sunday")
    start_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field(..., pattern=r"^\d{2}:\d{2}$")


class ScheduleConfigRequest(BaseModel):
    enabled: bool = False
    timezone: str = "UTC"
    slots: list[ScheduleSlotRequest] = Field(default_factory=list)


class CircuitBreakerConfigRequest(BaseModel):
    enabled: bool = True
    failure_threshold: float = Field(default=0.5, ge=0.1, le=1.0)
    window_seconds: int = Field(default=300, ge=60, le=3600)
    min_calls_in_window: int = Field(default=5, ge=1, le=100)


class CreateCampaignRequest(BaseModel):
    name: str
    agent_id: str
    source_type: str = "csv"
    source_id: str
    rate_limit_per_second: int = Field(default=1, ge=1, le=20)
    max_concurrency: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Max simultaneous active calls for this campaign",
    )
    from_number: Optional[str] = Field(
        default=None,
        description="Optional caller ID; one number may back many concurrent calls",
    )
    retry_config: Optional[RetryConfigRequest] = None
    schedule_config: Optional[ScheduleConfigRequest] = None
    circuit_breaker: Optional[CircuitBreakerConfigRequest] = None


class UpdateCampaignRequest(BaseModel):
    name: Optional[str] = None
    rate_limit_per_second: Optional[int] = Field(default=None, ge=1, le=20)
    max_concurrency: Optional[int] = Field(default=None, ge=1, le=20)
    retry_config: Optional[RetryConfigRequest] = None
    schedule_config: Optional[ScheduleConfigRequest] = None
    circuit_breaker: Optional[CircuitBreakerConfigRequest] = None


class CampaignResponse(BaseModel):
    campaign_id: str
    org_id: str
    name: str
    agent_id: str
    source_type: str
    source_id: str
    state: CampaignState
    total_rows: int = 0
    processed_rows: int = 0
    failed_rows: int = 0
    rate_limit_per_second: int = 1
    retry_config: dict[str, Any] = Field(default_factory=dict)
    orchestrator_metadata: dict[str, Any] = Field(default_factory=dict)
    from_number: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class CampaignCsvUploadResponse(BaseModel):
    """Response after uploading a campaign CSV via multipart form."""

    source_id: str = Field(description="MinIO object key; pass as source_id on create")
    filename: str
    contact_rows: int = Field(description="Number of data rows with a phone_number")


class CampaignProgressResponse(BaseModel):
    campaign_id: str
    state: CampaignState
    total_rows: int
    processed_rows: int
    failed_rows: int
    progress_percentage: float
    rate_limit: Optional[int] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class CampaignCallStatusRequest(BaseModel):
    org_id: str
    call_id: str
    call_response: Optional[str] = None


class RedialCampaignRequest(BaseModel):
    name: str


KnowledgeDocumentStatus = Literal["processing", "ready", "failed"]


class KnowledgeDocumentResponse(BaseModel):
    """Knowledge base document metadata."""

    document_id: str
    org_id: str
    original_filename: str
    status: KnowledgeDocumentStatus
    chunk_count: Optional[int] = None
    embedding_model: Optional[str] = None
    storage_key: Optional[str] = None
    error_message: Optional[str] = None
    created_at: str
    updated_at: str


class KnowledgeUploadResponse(BaseModel):
    """Response after scheduling PDF ingest."""

    document_id: str
    org_id: str
    original_filename: str
    status: KnowledgeDocumentStatus = "processing"


class KnowledgeDeleteResponse(BaseModel):
    """Response after deleting a knowledge document."""

    deleted: bool = True


class KnowledgeRetrieveRequest(BaseModel):
    """Service-to-service RAG retrieval request."""

    org_id: str
    question: str
    document_ids: Optional[list[str]] = None
    top_k: int = Field(default=5, ge=1, le=10)


class KnowledgeChunkResponse(BaseModel):
    """One retrieved knowledge chunk."""

    chunk_id: str
    document_id: Optional[str] = None
    source_filename: Optional[str] = None
    text: str
    distance: Optional[float] = None


class KnowledgeRetrieveResponse(BaseModel):
    """RAG retrieval response."""

    chunks: list[KnowledgeChunkResponse] = Field(default_factory=list)
