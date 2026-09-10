"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { csvParse } from "d3";
import { AlertCircle, Download, LayoutGrid, List, Trash2, Upload } from "lucide-react";
import { Button, IconButton } from "@/components/ui/Button";
import { StatCard } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { ProgressBar } from "@/components/ui/ProgressBar";
import { Dialog, DialogHeader } from "@/components/ui/Dialog";
import { Select } from "@/components/ui/Select";
import { Input } from "@/components/ui/Field";
import { Switch } from "@/components/ui/Switch";
import { Spinner } from "@/components/ui/Spinner";
import { Tooltip } from "@/components/ui/Tooltip";
import { useCampaigns } from "@/hooks/useCampaigns";
import { getCampaignRuns } from "@/lib/api/campaigns";
import { listAgents } from "@/lib/api-client";
import { formatDateTime, maskPhoneNumber } from "@/lib/format";
import type {
  AgentApiResponse,
  CampaignApiResponse,
  CampaignRetryConfig,
  CampaignRunItem,
  CampaignScheduleConfig,
  CampaignScheduleSlot,
  CampaignState,
  CreateCampaignPayload,
} from "@/lib/api-types";

const STATES: CampaignState[] = ["created", "syncing", "running", "paused", "completed", "failed"];
const FILTERS = ["All", ...STATES] as const;
type Filter = (typeof FILTERS)[number];

const TIMEZONE_OPTIONS = [
  { value: "Asia/Kolkata", label: "IST (Asia/Kolkata)" },
  { value: "UTC", label: "UTC" },
  { value: "America/New_York", label: "America/New_York" },
  { value: "America/Los_Angeles", label: "America/Los_Angeles" },
  { value: "Europe/London", label: "Europe/London" },
] as const;

const DEFAULT_RETRY_CONFIG: CampaignRetryConfig = {
  enabled: true,
  max_retries: 2,
  retry_delay_seconds: 120,
  retry_on_busy: true,
  retry_on_no_answer: true,
  retry_on_voicemail: false,
};

/** API slots are per weekday (0=Mon … 6=Sun); expand one daily window to every day. */
function slotsForEveryday(start_time: string, end_time: string): CampaignScheduleSlot[] {
  return Array.from({ length: 7 }, (_, day_of_week) => ({
    day_of_week,
    start_time,
    end_time,
  }));
}

const DEFAULT_SCHEDULE_CONFIG: CampaignScheduleConfig = {
  enabled: false,
  timezone: "Asia/Kolkata",
  slots: slotsForEveryday("09:00", "17:00"),
};

function stateTone(state: CampaignState) {
  if (state === "running") return "live" as const;
  if (state === "completed") return "accent" as const;
  if (state === "syncing") return "accent" as const;
  if (state === "failed") return "danger" as const;
  return "neutral" as const; // created, paused
}

function stateLabel(state: CampaignState) {
  return state.charAt(0).toUpperCase() + state.slice(1);
}

function progressPct(c: CampaignApiResponse): number {
  if (!c.total_rows) return 0;
  return (c.processed_rows / c.total_rows) * 100;
}

// --- Upload → preview → details dialog -------------------------------------

type UploadStep = "select" | "preview" | "details";

function UploadCampaignDialog({
  open,
  agents,
  uploading,
  creating,
  onUploadCsv,
  onCreate,
  onClose,
}: {
  open: boolean;
  agents: AgentApiResponse[];
  uploading: boolean;
  creating: boolean;
  onUploadCsv: (file: File) => Promise<{ source_id: string; filename: string; contact_rows: number } | null>;
  onCreate: (payload: CreateCampaignPayload) => Promise<boolean>;
  onClose: () => void;
}) {
  const [step, setStep] = useState<UploadStep>("select");
  const [dragOver, setDragOver] = useState(false);
  const [parseError, setParseError] = useState("");
  const [pendingFile, setPendingFile] = useState<File | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [previewRows, setPreviewRows] = useState<string[][]>([]);
  const [totalRows, setTotalRows] = useState(0);
  const [uploadResult, setUploadResult] = useState<{ source_id: string; filename: string; contact_rows: number } | null>(
    null,
  );
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [rateLimit, setRateLimit] = useState(1);
  const [maxConcurrency, setMaxConcurrency] = useState(5);
  const [retryConfig, setRetryConfig] = useState<CampaignRetryConfig>(DEFAULT_RETRY_CONFIG);
  const [scheduleConfig, setScheduleConfig] = useState<CampaignScheduleConfig>(DEFAULT_SCHEDULE_CONFIG);
  const inputRef = useRef<HTMLInputElement>(null);

  const eligibleAgents = useMemo(
    () => agents.filter((a) => a.agent_category === "telephony" && a.linked_phone_number),
    [agents],
  );
  const hasPhoneColumn = headers.includes("phone_number");
  const scheduleWindow = scheduleConfig.slots[0] ?? { start_time: "09:00", end_time: "17:00" };

  function reset() {
    setStep("select");
    setDragOver(false);
    setParseError("");
    setPendingFile(null);
    setHeaders([]);
    setPreviewRows([]);
    setTotalRows(0);
    setUploadResult(null);
    setName("");
    setAgentId("");
    setRateLimit(1);
    setMaxConcurrency(5);
    setRetryConfig(DEFAULT_RETRY_CONFIG);
    setScheduleConfig(DEFAULT_SCHEDULE_CONFIG);
  }

  function patchRetry<K extends keyof CampaignRetryConfig>(key: K, value: CampaignRetryConfig[K]) {
    setRetryConfig((prev) => ({ ...prev, [key]: value }));
  }

  function patchScheduleWindow(patch: { start_time?: string; end_time?: string }) {
    setScheduleConfig((prev) => {
      const start = patch.start_time ?? prev.slots[0]?.start_time ?? "09:00";
      const end = patch.end_time ?? prev.slots[0]?.end_time ?? "17:00";
      return { ...prev, slots: slotsForEveryday(start, end) };
    });
  }

  function handleClose() {
    reset();
    onClose();
  }

  async function handleFile(file: File) {
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setParseError("Only CSV files are supported.");
      setPendingFile(null);
      return;
    }
    setParseError("");
    setPendingFile(file);
    try {
      const text = await file.text();
      const parsed = csvParse(text);
      const cols = parsed.columns ?? [];
      setHeaders(cols);
      setPreviewRows(parsed.slice(0, 10).map((row) => cols.map((h) => String(row[h] ?? ""))));
      setTotalRows(parsed.length);
      setStep("preview");
    } catch {
      setParseError("Couldn't read this CSV — check the file and try again.");
      setPendingFile(null);
    }
  }

  async function confirmUpload() {
    if (!pendingFile) return;
    const result = await onUploadCsv(pendingFile);
    if (result) {
      setUploadResult(result);
      setStep("details");
    }
  }

  async function confirmCreate() {
    if (!uploadResult || !name.trim() || !agentId) return;
    const ok = await onCreate({
      name: name.trim(),
      agent_id: agentId,
      source_type: "csv",
      source_id: uploadResult.source_id,
      rate_limit_per_second: rateLimit,
      max_concurrency: maxConcurrency,
      retry_config: retryConfig,
    });
    if (ok) handleClose();
  }

  return (
    <Dialog open={open} onClose={handleClose} widthClassName="max-w-2xl">
      <DialogHeader
        title="New campaign"
        subtitle={
          step === "select"
            ? "Upload a CSV of contacts to call."
            : step === "preview"
              ? "Check the contacts before uploading."
              : "Name it and pick which agent calls."
        }
        onClose={handleClose}
      />
      <div className="flex flex-col gap-4 p-5">
        {step === "select" ? (
          <>
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragOver(true);
              }}
              onDragLeave={() => setDragOver(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(false);
                const file = e.dataTransfer.files[0];
                if (file) handleFile(file);
              }}
              onClick={() => inputRef.current?.click()}
              className={`flex cursor-pointer flex-col items-center gap-2 rounded-v-md border border-dashed p-10 text-center transition-colors ${
                dragOver ? "border-v-accent bg-v-pale" : "border-v-line bg-v-soft hover:border-v-accent"
              }`}
            >
              <Upload className="size-5 text-v-muted" strokeWidth={1.75} />
              <span className="text-sm font-semibold">
                {pendingFile ? pendingFile.name : "Drop a CSV here"}
              </span>
              <span className="text-xs text-v-muted">
                Needs a &quot;phone_number&quot; column · up to 50,000 rows
              </span>
              <input
                ref={inputRef}
                type="file"
                accept=".csv,text/csv"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleFile(file);
                  e.target.value = "";
                }}
              />
            </div>
            <p className="text-center text-xs text-v-muted">
              Need a template?{" "}
              <a
                href="/samples/sample_phone_numbers.csv"
                download="sample_phone_numbers.csv"
                onClick={(e) => e.stopPropagation()}
                className="inline-flex items-center gap-1 font-medium text-v-accent hover:underline"
              >
                <Download className="size-3" strokeWidth={1.75} />
                Download sample CSV
              </a>
            </p>
            {parseError ? <p className="text-sm text-v-danger">{parseError}</p> : null}
          </>
        ) : null}

        {step === "preview" ? (
          <>
            <div className="flex items-center justify-between gap-3">
              <span className="flex flex-col gap-0.5">
                <span className="text-sm font-semibold">{pendingFile?.name}</span>
                <span className="text-xs text-v-muted">{totalRows.toLocaleString()} rows parsed</span>
              </span>
              <Button variant="ghost" size="sm" onClick={() => setStep("select")}>
                Choose a different file
              </Button>
            </div>

            {!hasPhoneColumn ? (
              <p className="flex items-start gap-1.5 rounded-v-md border border-v-danger-line bg-v-danger-pale px-3.5 py-2.5 text-sm text-v-danger">
                <AlertCircle className="mt-0.5 size-4 shrink-0" strokeWidth={1.75} />
                This CSV needs a column named &quot;phone_number&quot; — choose a different file.
              </p>
            ) : null}

            <div className="overflow-x-auto rounded-v-md border border-v-line">
              <table className="w-full min-w-[480px] border-collapse text-xs">
                <thead>
                  <tr className="border-b border-v-line bg-v-soft text-left font-mono uppercase tracking-[.08em] text-v-muted">
                    {headers.map((h) => (
                      <th key={h} className="whitespace-nowrap px-3 py-2 font-medium">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {previewRows.map((row, i) => (
                    <tr key={i} className="border-b border-v-line last:border-b-0">
                      {row.map((cell, j) => (
                        <td key={j} className="whitespace-nowrap px-3 py-2">
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="flex justify-end gap-2 border-t border-v-line pt-4">
              <Button variant="ghost" size="sm" onClick={handleClose}>
                Cancel
              </Button>
              <Button size="sm" disabled={!hasPhoneColumn || uploading} onClick={confirmUpload}>
                {uploading ? <Spinner /> : <Upload className="size-3.5" strokeWidth={1.75} />}
                Confirm upload
              </Button>
            </div>
          </>
        ) : null}

        {step === "details" ? (
          <>
            <p className="text-sm text-v-muted">
              <strong className="font-semibold text-v-fg">{uploadResult?.contact_rows.toLocaleString()}</strong>{" "}
              contacts ready to call.
            </p>

            <label className="flex flex-col gap-1.5 text-[13px] font-medium">
              Campaign name
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Kharif advisory — Belagavi"
              />
            </label>

            <label className="flex flex-col gap-1.5 text-[13px] font-medium">
              Agent
              <Select value={agentId} onChange={(e) => setAgentId(e.target.value)} disabled={eligibleAgents.length === 0}>
                <option value="">Select an agent…</option>
                {eligibleAgents.map((a) => (
                  <option key={a.agent_id} value={a.agent_id}>
                    {a.name}
                  </option>
                ))}
              </Select>
              {eligibleAgents.length === 0 ? (
                <span className="text-xs font-light text-v-muted">
                  No telephony agent has a linked phone number yet — attach one under Agents first.
                </span>
              ) : null}
            </label>

            <div className="flex flex-col gap-4 rounded-v-md border border-v-line bg-v-soft p-3.5">
              <span className="text-xs font-semibold uppercase tracking-[.08em] text-v-muted">Advanced settings</span>

              <div className="grid grid-cols-2 gap-3">
                <label className="flex flex-col gap-1.5 text-[13px] font-medium">
                  Calls per second
                  <Input
                    type="number"
                    min={1}
                    max={20}
                    value={rateLimit}
                    onChange={(e) => setRateLimit(Number(e.target.value) || 1)}
                  />
                </label>
                <label className="flex flex-col gap-1.5 text-[13px] font-medium">
                  Max concurrent calls
                  <Input
                    type="number"
                    min={1}
                    max={20}
                    value={maxConcurrency}
                    onChange={(e) => setMaxConcurrency(Number(e.target.value) || 1)}
                  />
                </label>
              </div>

              <div className="flex flex-col gap-3 border-t border-v-line pt-3.5">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-[13px] font-semibold">Retry failed calls</span>
                    <span className="text-xs font-light text-v-muted">Re-queue contacts that don't connect.</span>
                  </div>
                  <Switch
                    checked={retryConfig.enabled}
                    label="Retry failed calls"
                    onChange={(checked) => patchRetry("enabled", checked)}
                  />
                </div>

                {retryConfig.enabled ? (
                  <>
                    <div className="grid grid-cols-2 gap-3">
                      <label className="flex flex-col gap-1.5 text-[13px] font-medium">
                        Max retries
                        <Input
                          type="number"
                          min={0}
                          max={10}
                          value={retryConfig.max_retries}
                          onChange={(e) => patchRetry("max_retries", Math.min(10, Math.max(0, Number(e.target.value) || 0)))}
                        />
                      </label>
                      <label className="flex flex-col gap-1.5 text-[13px] font-medium">
                        Retry delay (seconds)
                        <Input
                          type="number"
                          min={30}
                          max={3600}
                          value={retryConfig.retry_delay_seconds}
                          onChange={(e) =>
                            patchRetry("retry_delay_seconds", Math.min(3600, Math.max(30, Number(e.target.value) || 30)))
                          }
                        />
                      </label>
                    </div>
                    <div className="flex flex-col gap-2.5">
                      {(
                        [
                          ["retry_on_busy", "Retry on busy"],
                          ["retry_on_no_answer", "Retry on no answer"],
                          ["retry_on_voicemail", "Retry on voicemail"],
                        ] as const
                      ).map(([key, label]) => (
                        <div key={key} className="flex items-center justify-between gap-3">
                          <span className="text-[13px] font-medium">{label}</span>
                          <Switch
                            checked={retryConfig[key]}
                            label={label}
                            onChange={(checked) => patchRetry(key, checked)}
                          />
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}
              </div>

              <div className="flex flex-col gap-3 border-t border-v-line pt-3.5">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex flex-col gap-0.5">
                    <span className="text-[13px] font-semibold">Calling schedule</span>
                    <span className="text-xs font-light text-v-muted">Limit dialling to a daily time window.</span>
                  </div>
                  <Switch
                    checked={scheduleConfig.enabled}
                    label="Calling schedule"
                    onChange={(checked) => setScheduleConfig((prev) => ({ ...prev, enabled: checked }))}
                  />
                </div>

                {scheduleConfig.enabled ? (
                  <>
                    <label className="flex flex-col gap-1.5 text-[13px] font-medium">
                      Timezone
                      <Select
                        value={scheduleConfig.timezone}
                        onChange={(e) => setScheduleConfig((prev) => ({ ...prev, timezone: e.target.value }))}
                      >
                        {TIMEZONE_OPTIONS.map((tz) => (
                          <option key={tz.value} value={tz.value}>
                            {tz.label}
                          </option>
                        ))}
                      </Select>
                    </label>
                    <div className="grid grid-cols-2 gap-3">
                      <label className="flex flex-col gap-1.5 text-[13px] font-medium">
                        Start
                        <Input
                          type="time"
                          value={scheduleWindow.start_time}
                          onChange={(e) => patchScheduleWindow({ start_time: e.target.value })}
                        />
                      </label>
                      <label className="flex flex-col gap-1.5 text-[13px] font-medium">
                        End
                        <Input
                          type="time"
                          value={scheduleWindow.end_time}
                          onChange={(e) => patchScheduleWindow({ end_time: e.target.value })}
                        />
                      </label>
                    </div>
                  </>
                ) : null}
              </div>
            </div>

            <div className="flex justify-between gap-2 border-t border-v-line pt-4">
              <Button variant="ghost" size="sm" onClick={() => setStep("preview")}>
                Back
              </Button>
              <Button size="sm" disabled={!name.trim() || !agentId || creating} onClick={confirmCreate}>
                {creating ? <Spinner /> : null}
                Create campaign
              </Button>
            </div>
          </>
        ) : null}
      </div>
    </Dialog>
  );
}

// --- Redial dialog -----------------------------------------------------------

function RedialDialog({
  campaign,
  busy,
  onConfirm,
  onClose,
}: {
  campaign: CampaignApiResponse | null;
  busy: boolean;
  onConfirm: (name: string) => void;
  onClose: () => void;
}) {
  const [name, setName] = useState("");

  useEffect(() => {
    if (campaign) setName(`${campaign.name} — redial`);
  }, [campaign]);

  return (
    <Dialog open={Boolean(campaign)} onClose={onClose} widthClassName="max-w-sm">
      <DialogHeader title="Redial failed contacts" onClose={onClose} />
      <div className="flex flex-col gap-4 p-5">
        <p className="text-sm font-light leading-relaxed text-v-fg">
          Creates a new campaign that redials everyone from{" "}
          <strong className="font-semibold">{campaign?.name}</strong> who didn&apos;t answer.
        </p>
        <label className="flex flex-col gap-1.5 text-[13px] font-medium">
          New campaign name
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" disabled={!name.trim() || busy} onClick={() => onConfirm(name.trim())}>
            {busy ? <Spinner /> : null}
            Create redial campaign
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

// --- Call-status ("View calls") dialog ---------------------------------------

function RunsDialog({ campaign, onClose }: { campaign: CampaignApiResponse | null; onClose: () => void }) {
  const [runs, setRuns] = useState<CampaignRunItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!campaign) return;
    let cancelled = false;
    setLoading(true);
    setError("");
    getCampaignRuns(campaign.campaign_id)
      .then((res) => {
        if (!cancelled) setRuns(res);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Couldn't load calls.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [campaign]);

  return (
    <Dialog open={Boolean(campaign)} onClose={onClose} widthClassName="max-w-3xl">
      <DialogHeader title={`Calls — ${campaign?.name ?? ""}`} onClose={onClose} />
      <div className="flex flex-col gap-4 overflow-y-auto p-5">
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-v-muted">
            <Spinner light={false} /> Loading calls…
          </div>
        ) : error ? (
          <p className="text-sm text-v-danger">{error}</p>
        ) : runs.length === 0 ? (
          <p className="text-sm text-v-muted">No calls placed yet.</p>
        ) : (
          <div className="overflow-x-auto rounded-v-md border border-v-line">
            <table className="w-full min-w-[560px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-v-line text-left font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
                  <th className="px-4 py-3 font-medium">Number</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Response</th>
                  <th className="px-4 py-3 font-medium">Duration</th>
                  <th className="px-4 py-3 font-medium">When</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r, i) => (
                  <tr key={r.call_id ?? i} className="border-b border-v-line last:border-b-0">
                    <td className="px-4 py-3 font-mono text-xs">{maskPhoneNumber(r.to_number)}</td>
                    <td className="px-4 py-3">{r.status ?? "–"}</td>
                    <td className="px-4 py-3">{r.call_response ?? "–"}</td>
                    <td className="px-4 py-3">{r.duration != null ? `${r.duration}s` : "–"}</td>
                    <td className="px-4 py-3 text-xs text-v-muted">{formatDateTime(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Dialog>
  );
}

// --- Delete confirmation dialog ----------------------------------------------

function DeleteCampaignDialog({
  campaign,
  busy,
  onConfirm,
  onClose,
}: {
  campaign: CampaignApiResponse | null;
  busy: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  return (
    <Dialog open={Boolean(campaign)} onClose={onClose} widthClassName="max-w-sm">
      <DialogHeader title="Delete campaign?" onClose={onClose} />
      <div className="flex flex-col gap-4 p-5">
        <p className="text-sm font-light leading-relaxed text-v-fg">
          Are you sure you want to delete <strong className="font-semibold">{campaign?.name}</strong>? This
          can&apos;t be undone.
        </p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger-outline" size="sm" disabled={busy} onClick={onConfirm}>
            {busy ? <Spinner light={false} /> : null}
            Delete
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

// --- Main page ---------------------------------------------------------------

export function Campaigns({ onNotify }: { onNotify: (title: string, note: string) => void }) {
  const {
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
  } = useCampaigns(onNotify);
  const [agents, setAgents] = useState<AgentApiResponse[]>([]);
  const [filter, setFilter] = useState<Filter>("All");
  const [layout, setLayout] = useState<"cards" | "list">("cards");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [redialTarget, setRedialTarget] = useState<CampaignApiResponse | null>(null);
  const [runsTarget, setRunsTarget] = useState<CampaignApiResponse | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<CampaignApiResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    listAgents()
      .then((res) => {
        if (!cancelled) setAgents(res);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const agentNameById = useMemo(() => {
    const map: Record<string, string> = {};
    for (const a of agents) map[a.agent_id] = a.name;
    return map;
  }, [agents]);

  const counts = useMemo(() => {
    const c: Record<string, number> = { All: campaigns.length };
    for (const camp of campaigns) c[camp.state] = (c[camp.state] ?? 0) + 1;
    return c;
  }, [campaigns]);

  const rows = filter === "All" ? campaigns : campaigns.filter((c) => c.state === filter);

  const stats = useMemo(() => {
    const totalContacts = campaigns.reduce((sum, c) => sum + c.total_rows, 0);
    const running = campaigns.filter((c) => c.state === "running").length;
    const completed = campaigns.filter((c) => c.state === "completed").length;
    return { total: campaigns.length, running, totalContacts, completed };
  }, [campaigns]);

  function actionFor(c: CampaignApiResponse) {
    const busy = busyId === c.campaign_id;
    if (c.state === "created") {
      return (
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => start(c.campaign_id)}>
          {busy ? <Spinner light={false} /> : null}
          Start
        </Button>
      );
    }
    if (c.state === "running") {
      return (
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => pause(c.campaign_id)}>
          {busy ? <Spinner light={false} /> : null}
          Pause
        </Button>
      );
    }
    if (c.state === "paused") {
      return (
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => resume(c.campaign_id)}>
          {busy ? <Spinner light={false} /> : null}
          Resume
        </Button>
      );
    }
    if (c.state === "completed" || c.state === "failed") {
      return (
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => setRedialTarget(c)}>
          Redial
        </Button>
      );
    }
    return (
      <Button variant="ghost" size="sm" disabled>
        Syncing…
      </Button>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-end justify-between gap-4 border-b border-v-line pb-6">
        <div className="flex flex-col gap-1.5">
          <h1 className="text-3xl font-semibold tracking-tight">Campaigns</h1>
          <p className="max-w-[64ch] text-sm font-light leading-relaxed text-v-muted">
            Calls you make, not calls you take — a campaign is a telephony agent plus a list of
            people.
          </p>
        </div>
        <Button variant="primary" onClick={() => setUploadOpen(true)}>
          + New campaign
        </Button>
      </div>

      {loadError ? (
        <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
          {loadError}
        </div>
      ) : null}

      {!loading && campaigns.length > 0 ? (
        <div className="grid grid-cols-2 gap-3.5 sm:grid-cols-4">
          <StatCard label="Campaigns" value={String(stats.total)} />
          <StatCard label="Running now" value={String(stats.running)} />
          <StatCard label="Contacts queued" value={stats.totalContacts.toLocaleString()} />
          <StatCard label="Completed" value={String(stats.completed)} />
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-1.5">
          {FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`cursor-pointer rounded-full border px-3 py-1.5 text-xs font-medium capitalize ${
                filter === f ? "border-v-fg bg-v-fg text-white" : "border-v-line bg-white text-v-muted-2 hover:border-v-accent"
              }`}
            >
              {f} {counts[f] ? <span className="ml-1 opacity-70">{counts[f]}</span> : null}
            </button>
          ))}
        </div>
        <div className="flex overflow-hidden rounded-full border border-v-line bg-white">
          <button
            type="button"
            onClick={() => setLayout("cards")}
            aria-label="Grid view"
            className={`cursor-pointer px-3 py-2 transition-colors ${
              layout === "cards" ? "bg-v-fg text-white" : "text-v-muted-2 hover:bg-v-soft"
            }`}
          >
            <LayoutGrid className="h-4 w-4" strokeWidth={1.75} />
          </button>
          <button
            type="button"
            onClick={() => setLayout("list")}
            aria-label="List view"
            className={`cursor-pointer px-3 py-2 transition-colors ${
              layout === "list" ? "bg-v-fg text-white" : "text-v-muted-2 hover:bg-v-soft"
            }`}
          >
            <List className="h-4 w-4" strokeWidth={1.75} />
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-v-muted">
          <Spinner light={false} /> Loading campaigns…
        </div>
      ) : rows.length === 0 ? (
        <div className="flex flex-col items-center gap-1 rounded-v-md border border-dashed border-v-line bg-white p-12 text-center">
          <span className="text-sm font-semibold">
            {filter === "All" ? "No campaigns yet" : "Nothing matches"}
          </span>
          <span className="text-xs font-light text-v-muted">
            {filter === "All" ? "Upload a CSV to start your first campaign." : "Try another filter."}
          </span>
        </div>
      ) : layout === "cards" ? (
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
          {rows.map((c) => (
            <div key={c.campaign_id} className="flex flex-col gap-3.5 rounded-v-md border border-v-line bg-white p-4.5">
              <Badge tone={stateTone(c.state)}>{stateLabel(c.state)}</Badge>
              <span className="flex flex-col gap-1 min-w-0">
                <span className="truncate text-[15px] font-semibold">{c.name}</span>
                <span className="text-xs font-light text-v-muted">
                  {agentNameById[c.agent_id] ?? c.agent_id}
                </span>
              </span>
              <div className="flex flex-col gap-1.5">
                <ProgressBar pct={progressPct(c)} thick />
                <span className="flex items-center justify-between text-[10.5px] font-mono text-v-muted">
                  <span>
                    {c.processed_rows.toLocaleString()} of {c.total_rows ? c.total_rows.toLocaleString() : "–"} placed
                  </span>
                  <span>{c.failed_rows.toLocaleString()} failed</span>
                </span>
              </div>
              <div className="flex items-center justify-between gap-2 border-t border-v-line pt-3">
                <span className="font-mono text-[10.5px] text-v-muted">
                  {formatDateTime(c.started_at ?? c.created_at)}
                </span>
                <span className="flex items-center gap-1.5">
                  <Tooltip text="View calls">
                    <IconButton
                      aria-label="View calls"
                      onClick={() => setRunsTarget(c)}
                      className="bg-v-soft hover:border-v-accent hover:bg-v-pale hover:text-v-accent"
                    >
                      <List className="size-4" strokeWidth={1.75} />
                    </IconButton>
                  </Tooltip>
                  <Tooltip text="Delete campaign">
                    <IconButton
                      aria-label="Delete campaign"
                      onClick={() => setDeleteTarget(c)}
                      className="bg-v-soft hover:border-v-danger-line hover:bg-v-danger-pale hover:text-v-danger"
                    >
                      <Trash2 className="size-4" strokeWidth={1.75} />
                    </IconButton>
                  </Tooltip>
                  {actionFor(c)}
                </span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex flex-col rounded-v-md border border-v-line bg-white">
          {rows.map((c) => (
            <div key={c.campaign_id} className="flex flex-wrap items-center justify-between gap-3 border-b border-v-line px-4.5 py-3 last:border-0">
              <span className="flex min-w-0 flex-col">
                <span className="truncate text-[13.5px] font-medium">{c.name}</span>
                <span className="text-xs font-light text-v-muted">
                  {agentNameById[c.agent_id] ?? c.agent_id} · {formatDateTime(c.started_at ?? c.created_at)}
                </span>
              </span>
              <span className="flex items-center gap-3">
                <span className="w-24">
                  <ProgressBar pct={progressPct(c)} />
                </span>
                <span className="font-mono text-[10.5px] w-16 text-right text-v-muted">
                  {Math.round(progressPct(c))}%
                </span>
                <Badge tone={stateTone(c.state)}>{stateLabel(c.state)}</Badge>
              </span>
            </div>
          ))}
        </div>
      )}

      <UploadCampaignDialog
        open={uploadOpen}
        agents={agents}
        uploading={uploading}
        creating={creating}
        onUploadCsv={uploadCsv}
        onCreate={create}
        onClose={() => setUploadOpen(false)}
      />

      <RedialDialog
        campaign={redialTarget}
        busy={busyId === redialTarget?.campaign_id}
        onConfirm={async (name) => {
          if (!redialTarget) return;
          const ok = await redial(redialTarget.campaign_id, name);
          if (ok) setRedialTarget(null);
        }}
        onClose={() => setRedialTarget(null)}
      />

      <RunsDialog campaign={runsTarget} onClose={() => setRunsTarget(null)} />

      <DeleteCampaignDialog
        campaign={deleteTarget}
        busy={busyId === deleteTarget?.campaign_id}
        onConfirm={async () => {
          if (!deleteTarget) return;
          const ok = await remove(deleteTarget.campaign_id);
          if (ok) setDeleteTarget(null);
        }}
        onClose={() => setDeleteTarget(null)}
      />
    </div>
  );
}
