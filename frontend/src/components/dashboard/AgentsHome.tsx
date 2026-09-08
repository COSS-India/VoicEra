"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { motion, type Variants } from "framer-motion";
import {
  Archive,
  ArchiveRestore,
  Clock,
  Copy,
  Eye,
  EyeOff,
  Laptop,
  MoreVertical,
  Pencil,
  Phone,
  Plus,
  RefreshCw,
  Search,
  Trash2,
  User,
} from "lucide-react";
import { Button, IconButton } from "@/components/ui/Button";
import { Dialog, DialogHeader } from "@/components/ui/Dialog";
import { Select } from "@/components/ui/Select";
import { Spinner } from "@/components/ui/Spinner";
import { archiveAgent, createAgent, deleteAgent, getAgent, listAgents } from "@/lib/api-client";
import { listOrgCalls } from "@/lib/api/calls";
import { listPhoneNumbers } from "@/lib/api/phone-numbers";
import { formatDuration, nameFromEmail, truncateLabel } from "@/lib/format";
import { agentPurposeFromApi } from "@/lib/agent-mapper";
import { useAuth } from "@/components/AuthProvider";
import { AgentTestModal } from "@/components/dashboard/AgentTestModal";
import { TestCallSheet } from "@/components/dashboard/TestCallSheet";
import type { AgentApiResponse, CallLogItem, PhoneNumberItem } from "@/lib/api-types";

type SortOption = "recent" | "oldest" | "name";
const SORT_LABEL: Record<SortOption, string> = {
  recent: "Recently created",
  oldest: "Oldest first",
  name: "Name (A–Z)",
};

const SPARKLINE_SLOTS = 12;
// Same slow-round-trip threshold used elsewhere for latency call-outs.
const SLOW_AVG_DURATION_SECS = 240;

interface DashboardAgent {
  id: string;
  name: string;
  purpose: string;
  createdAt: number;
}

interface AgentCallStats {
  onCall: number;
  today: number;
  avgDuration: number | null;
  /** Most-recent-first presence flags for the last N calls, used by the
   * sparkline — built from the same bounded recent-calls window as the rest
   * of these stats, not a separate fetch. */
  sparkline: boolean[];
}

const EMPTY_STATS: AgentCallStats = { onCall: 0, today: 0, avgDuration: null, sparkline: [] };

/** Buckets an org's recent calls per agent for the row/card stats and the
 * sparkline. Built from a bounded recent-calls window (not full history) —
 * this is a live-dashboard glance, not an exhaustive report; History has that. */
function buildAgentStats(calls: CallLogItem[]): Record<string, AgentCallStats> {
  const stats: Record<string, { onCall: number; todayCount: number; durations: number[]; recent: CallLogItem[] }> = {};
  const todayKey = new Date().toDateString();

  for (const call of calls) {
    const bucket = (stats[call.agent_id] ??= { onCall: 0, todayCount: 0, durations: [], recent: [] });
    if (call.status === "ringing" || call.status === "in_progress" || call.status === "initiated") {
      bucket.onCall += 1;
    }
    const at = call.start_time_utc ?? call.created_at;
    if (at && new Date(at).toDateString() === todayKey) bucket.todayCount += 1;
    if (call.status === "completed" && typeof call.duration === "number") {
      bucket.durations.push(call.duration);
    }
    bucket.recent.push(call);
  }

  return Object.fromEntries(
    Object.entries(stats).map(([agentId, b]) => {
      const ordered = [...b.recent].sort((a, c) => {
        const at = new Date(a.start_time_utc ?? a.created_at ?? 0).getTime();
        const ct = new Date(c.start_time_utc ?? c.created_at ?? 0).getTime();
        return ct - at;
      });
      const sparkline = Array.from({ length: SPARKLINE_SLOTS }, (_, i) => i < ordered.length);
      return [
        agentId,
        {
          onCall: b.onCall,
          today: b.todayCount,
          avgDuration: b.durations.length
            ? b.durations.reduce((sum, d) => sum + d, 0) / b.durations.length
            : null,
          sparkline,
        },
      ];
    }),
  );
}

type LinkStatusTone = "ok" | "error" | "neutral";

function linkStatus(raw: AgentApiResponse | undefined): { tone: LinkStatusTone; label: string } {
  if (!raw) return { tone: "neutral", label: "—" };
  if (raw.agent_category === "websocket") {
    return { tone: "neutral", label: "WebSocket" };
  }
  if (raw.linked_phone_number) {
    const provider = raw.telephony?.provider;
    const suffix = provider ? ` (${provider.toUpperCase()})` : "";
    return { tone: "ok", label: `${raw.linked_phone_number}${suffix}` };
  }
  return { tone: "error", label: "Not linked" };
}

const LINK_STATUS_STYLES: Record<LinkStatusTone, { pill: string; dot: string }> = {
  ok: { pill: "bg-v-ok-tint text-v-ok-ink", dot: "bg-v-ok" },
  error: { pill: "bg-v-danger-pale text-v-danger", dot: "bg-v-danger" },
  neutral: { pill: "bg-v-pale text-v-accent", dot: "bg-v-accent" },
};

const cardVariants: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.06, duration: 0.35, ease: [0.4, 0, 0.2, 1] as const },
  }),
};

function relativeTime(from: Date, now: Date): string {
  const seconds = Math.max(0, Math.round((now.getTime() - from.getTime()) / 1000));
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

interface MenuAction {
  label: string;
  icon: typeof Copy;
  onClick: () => void;
  danger?: boolean;
}

/**
 * Overflow menu (3-dot): Duplicate / Delete. Its popup is rendered in a portal
 * to document.body and positioned `fixed` from the trigger's own bounding box, so it
 * fully escapes an ancestor's overflow:hidden instead of being clipped by it.
 */
function AgentCardMenu({ actions, busy }: { actions: MenuAction[]; busy?: boolean }) {
  const [open, setOpen] = useState(false);
  const [coords, setCoords] = useState<{ top: number; right: number } | null>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDocMouseDown(e: MouseEvent) {
      if (menuRef.current?.contains(e.target as Node) || btnRef.current?.contains(e.target as Node)) return;
      setOpen(false);
    }
    function close() {
      setOpen(false);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      document.removeEventListener("mousedown", onDocMouseDown);
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);

  function toggle(e: React.MouseEvent) {
    e.stopPropagation();
    if (!open && btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect();
      setCoords({ top: rect.bottom + 4, right: Math.max(8, window.innerWidth - rect.right) });
    }
    setOpen((v) => !v);
  }

  return (
    <>
      <IconButton ref={btnRef} aria-label="More actions" aria-haspopup="menu" aria-expanded={open} onClick={toggle}>
        <MoreVertical className="size-4" strokeWidth={1.8} />
      </IconButton>
      {open && coords
        ? createPortal(
          <div
            ref={menuRef}
            role="menu"
            onClick={(e) => e.stopPropagation()}
            style={{ position: "fixed", top: coords.top, right: coords.right }}
            className="z-[1000] w-40 overflow-hidden rounded-v-md border border-v-line bg-white py-1 shadow-[0_8px_24px_rgba(20,22,26,0.12)]"
          >
            {actions.map((action) => (
              <button
                key={action.label}
                type="button"
                role="menuitem"
                disabled={action.danger ? busy : undefined}
                onClick={() => {
                  setOpen(false);
                  action.onClick();
                }}
                className={`flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-[13px] transition-colors duration-[120ms] hover:bg-v-soft disabled:cursor-not-allowed disabled:opacity-45 ${action.danger ? "text-v-danger" : "text-v-fg"
                  }`}
              >
                <action.icon className="size-3.5" strokeWidth={1.8} />
                {action.label}
              </button>
            ))}
          </div>,
          document.body,
        )
        : null}
    </>
  );
}

interface AgentCardActions {
  onOpenEdit: () => void;
  onTestCall: () => void;
  onTestBrowser: () => void;
  onOpenLogs: () => void;
  onDuplicate: () => void;
  onDelete: () => void;
  onArchive: () => void;
}

function cardMenuActions(a: AgentCardActions, archived: boolean): MenuAction[] {
  return [
    { label: "History", icon: Clock, onClick: a.onOpenLogs },
    { label: "Duplicate", icon: Copy, onClick: a.onDuplicate },
    { label: "Delete", icon: Trash2, onClick: a.onDelete, danger: true },
    archived
      ? { label: "Unarchive", icon: ArchiveRestore, onClick: a.onArchive }
      : { label: "Archive", icon: Archive, onClick: a.onArchive },
  ];
}

interface AgentCardProps extends AgentCardActions {
  agent: DashboardAgent;
  raw: AgentApiResponse | undefined;
  stats: AgentCallStats;
  busy: boolean;
  index: number;
  attachedByEmail?: string | null;
}

/** Grid card: channel icon, identity, link status, and test actions. */
function AgentCard({
  agent,
  raw,
  busy,
  index,
  attachedByEmail,
  onOpenEdit,
  onTestCall,
  onTestBrowser,
  onOpenLogs,
  onDuplicate,
  onDelete,
  onArchive,
}: AgentCardProps) {
  const isTelephony = raw?.agent_category === "telephony";
  const canTestCall = isTelephony && Boolean(raw?.linked_phone_number);
  const status = linkStatus(raw);
  const statusStyle = LINK_STATUS_STYLES[status.tone];
  const createdByName = raw?.created_by ? nameFromEmail(raw.created_by) : null;
  const attachedByName =
    raw?.linked_phone_number && attachedByEmail ? nameFromEmail(attachedByEmail) : null;

  return (
    <motion.div
      custom={index}
      variants={cardVariants}
      initial="hidden"
      animate="visible"
      className="flex flex-col gap-3.5 overflow-hidden rounded-v-xl border border-v-line bg-white p-5 shadow-[var(--v-shadow-card)] transition-colors duration-[120ms] hover:border-v-fg"
    >
      <div className="flex min-w-0 items-start justify-between gap-2">
        <button
          type="button"
          onClick={onOpenEdit}
          className="min-w-0 flex-1 cursor-pointer overflow-hidden text-left"
        >
          <span
            className="block truncate text-[17px] font-extrabold tracking-[-.35px] text-v-fg"
            title={agent.name}
          >
            {truncateLabel(agent.name, 30)}
          </span>
        </button>
        <div className="flex shrink-0 items-center gap-1.5">
          <AgentCardMenu
            busy={busy}
            actions={cardMenuActions(
              { onOpenEdit, onTestCall, onTestBrowser, onOpenLogs, onDuplicate, onDelete, onArchive },
              Boolean(raw?.archived),
            )}
          />
        </div>
      </div>



      <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 w-full">
        {createdByName ? (
          <span
            className="flex min-w-0 items-center gap-1.5 truncate text-[11.5px] font-light text-v-muted"
            title={`Created by ${createdByName}`}
          >
            <User className="size-3 shrink-0" strokeWidth={1.9} />
            <span className="truncate">{createdByName}</span>
          </span>
        ) : <span />}
        <span
          className={`inline-flex w-fit max-w-full items-center gap-1.5 rounded-full px-2.5 py-1 text-[11.5px] font-semibold ${statusStyle.pill}`}
        >
          <span className={`size-1.5 shrink-0 rounded-full ${statusStyle.dot}`} />
          <span className="truncate">{status.label}</span>
        </span>
      </div>
 

     

      <div className="flex items-center gap-2 border-t border-v-hairline pt-3.5">
        {isTelephony ? (
          <Button variant="outline" size="sm" onClick={onTestCall} disabled={!canTestCall} className="h-[42px] flex-1 justify-center">
            <Phone className="size-3.5" strokeWidth={1.9} />
            Test Call
          </Button>
        ) : (
          <Button variant="outline" size="sm" onClick={onTestBrowser} className="h-[42px] flex-1 justify-center">
            <Laptop className="size-3.5" strokeWidth={1.9} />
            Test on Browser
          </Button>
        )}
        <IconButton aria-label="Edit agent" onClick={onOpenEdit} className="size-[42px]">
          <Pencil className="size-4" strokeWidth={1.9} />
        </IconButton>
      </div>
    </motion.div>
  );
}

const STATS_VISIBLE_KEY = "voicera_stats_visible";

export function AgentsHome({ onNotify }: { onNotify: (title: string, note: string) => void }) {
  const { session } = useAuth();
  const router = useRouter();
  const [agents, setAgents] = useState<DashboardAgent[]>([]);
  const [statsVisible, setStatsVisible] = useState(() => {
    if (typeof window === "undefined") return true;
    const stored = window.localStorage.getItem(STATS_VISIBLE_KEY);
    return stored === null ? true : stored === "1";
  });
  const [rawAgents, setRawAgents] = useState<Record<string, AgentApiResponse>>({});
  const [phoneNumbersByAgentId, setPhoneNumbersByAgentId] = useState<Record<string, PhoneNumberItem>>({});
  const [callStats, setCallStats] = useState<Record<string, AgentCallStats>>({});
  const [testAgentId, setTestAgentId] = useState<string | null>(null);
  const [testCallAgentId, setTestCallAgentId] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DashboardAgent | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [query, setQuery] = useState("");
  const [sortBy, setSortBy] = useState<SortOption>("recent");
  const [showArchived, setShowArchived] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [now, setNow] = useState(() => new Date());
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchRef.current?.focus();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  function toDashboardAgent(a: AgentApiResponse): DashboardAgent {
    return {
      id: a.agent_id,
      name: a.name,
      purpose: agentPurposeFromApi(a),
      createdAt: a.created_at ? new Date(a.created_at).getTime() : Date.now(),
    };
  }

  const loadAgents = useCallback(async () => {
    setLoadError("");
    try {
      const data = await listAgents();
      setRawAgents(Object.fromEntries(data.map((a) => [a.agent_id, a])));
      setAgents(data.map(toDashboardAgent));
      setLastUpdated(new Date());
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Couldn't load agents.");
    } finally {
      setLoading(false);
    }
  }, []);

  const testAgent = testAgentId ? rawAgents[testAgentId] ?? null : null;
  const testCallAgent = testCallAgentId ? rawAgents[testCallAgentId] ?? null : null;

  function openTestCall(id: string) {
    setTestCallAgentId(id);
  }

  function openTestBrowser(id: string) {
    setTestAgentId(id);
  }

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  useEffect(() => {
    let cancelled = false;
    listPhoneNumbers()
      .then((numbers) => {
        if (cancelled) return;
        const byAgentId: Record<string, PhoneNumberItem> = {};
        for (const n of numbers) {
          if (n.agent_id) byAgentId[n.agent_id] = n;
        }
        setPhoneNumbersByAgentId(byAgentId);
      })
      .catch(() => {
        /* cards fall back to showing no attach info */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // On call / today / avg duration / sparkline per agent, from a bounded
  // recent-calls window — a live-dashboard glance, not a full report
  // (History has that). Same fetch as before; no new API calls.
  useEffect(() => {
    if (!session?.orgId) return;
    let cancelled = false;
    listOrgCalls(session.orgId, { limit: 500 })
      .then((res) => {
        if (!cancelled) setCallStats(buildAgentStats(res.calls));
      })
      .catch(() => {
        /* cards fall back to zeroed stats */
      });
    return () => {
      cancelled = true;
    };
  }, [session?.orgId]);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  const hasAgents = agents.length > 0;

  const orgStats = useMemo(() => {
    const rows = Object.values(callStats);
    const callsToday = rows.reduce((sum, s) => sum + s.today, 0);
    const durations = rows.map((s) => s.avgDuration).filter((v): v is number => v !== null);
    const avgDuration = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null;
    return { callsToday, avgDuration };
  }, [callStats]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const result = agents.filter((a) => {
      const archived = Boolean(rawAgents[a.id]?.archived);
      if (archived !== showArchived) return false;
      if (!q) return true;
      // Search agent name/purpose, the linked number, and prompt text
      // (system prompt + greeting) — matches the search box's own placeholder
      // ("Search agents, numbers, prompts…"), not just the agent's name.
      const raw = rawAgents[a.id];
      const haystack = [
        a.name,
        a.purpose,
        raw?.linked_phone_number,
        raw?.config?.prompts?.system_prompt,
        raw?.config?.prompts?.greeting_message,
      ]
        .filter((v): v is string => Boolean(v))
        .join(" \n ")
        .toLowerCase();
      return haystack.includes(q);
    });
    const sorted = [...result];
    if (sortBy === "recent") sorted.sort((a, b) => b.createdAt - a.createdAt);
    else if (sortBy === "oldest") sorted.sort((a, b) => a.createdAt - b.createdAt);
    else sorted.sort((a, b) => a.name.localeCompare(b.name));
    return sorted;
  }, [agents, query, sortBy, rawAgents, showArchived]);

  const pageItems = filtered;

  const eyebrow = `${new Date()
    .toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })
    .toUpperCase()}${session?.orgName ? ` · ${session.orgName.toUpperCase()}` : ""}`;

  // Determine time of day for greeting
  function getGreeting() {
    const now = new Date();
    const hour = now.getHours();
    if (hour < 12) return "Good morning";
    if (hour < 18) return "Good afternoon";
    return "Good evening";
  }

  // Attempt to extract user name from session (using common fields: displayName, name, email fallback)
  const userName =
    (session && ("displayName" in session) && (session as any).displayName) ||
    (session && ("name" in session) && (session as any).name) ||
    (session && ("userName" in session) && (session as any).userName) ||
    (session && ("email" in session) && (session as any).email.split("@")[0]) ||
    "";

  const greeting = `${getGreeting()}${userName ? `, ${userName}` : ""}`;

  const headline = greeting;

  function goToEdit(id: string) {
    router.push(`/agents/${id}/edit`);
  }

  function goToLogs(id: string) {
    router.push(`/history?agent=${id}`);
  }

  function handleDelete(a: DashboardAgent) {
    setDeleteTarget(a);
  }

  async function handleArchive(a: DashboardAgent) {
    const archived = !rawAgents[a.id]?.archived;
    setBusyId(a.id);
    try {
      const updated = await archiveAgent(a.id, archived);
      setRawAgents((prev) => ({ ...prev, [a.id]: updated }));
      onNotify(archived ? "Archived" : "Unarchived", `${a.name} ${archived ? "was archived." : "is active again."}`);
    } catch (err) {
      onNotify(
        archived ? "Couldn't archive" : "Couldn't unarchive",
        err instanceof Error ? err.message : "Something went wrong.",
      );
    } finally {
      setBusyId(null);
    }
  }

  async function confirmDelete() {
    const a = deleteTarget;
    if (!a) return;
    setBusyId(a.id);
    try {
      await deleteAgent(a.id);
      setAgents((prev) => prev.filter((x) => x.id !== a.id));
      setRawAgents((prev) => {
        const next = { ...prev };
        delete next[a.id];
        return next;
      });
      onNotify("Deleted", `${a.name} was removed.`);
    } catch (err) {
      onNotify("Couldn't delete", err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusyId(null);
      setDeleteTarget(null);
    }
  }

  async function handleDuplicate(a: DashboardAgent) {
    setBusyId(a.id);
    try {
      const source = rawAgents[a.id] ?? (await getAgent(a.id));
      const created = await createAgent({
        name: `${source.name} (copy)`,
        agent_category: source.agent_category,
        telephony_provider: source.telephony?.provider ?? null,
        config: source.config,
      });
      setRawAgents((prev) => ({ ...prev, [created.agent_id]: created }));
      setAgents((prev) => [...prev, toDashboardAgent(created)]);
      onNotify("Duplicated", `${created.name} created.`);
    } catch (err) {
      onNotify("Couldn't duplicate", err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusyId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center gap-2 text-sm text-v-muted">
        <Spinner light={false} /> Loading agents…
      </div>
    );
  }

  const roundTripSlow = orgStats.avgDuration !== null && orgStats.avgDuration >= SLOW_AVG_DURATION_SECS;

  return (
    <div className="flex flex-col gap-[22px]">
      {/* Header */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="flex flex-col gap-1.5">
          <span className="font-mono text-[10px] font-semibold uppercase tracking-[.16em] text-v-dim">{eyebrow}</span>
          <h1 className="text-[30px] font-extrabold leading-[1.1] tracking-[-.7px] text-v-fg">{headline}</h1>
        </div>
        <div className="flex items-center gap-2.5">
          {hasAgents ? (
            <button
              type="button"
              onClick={() =>
                setStatsVisible((v) => {
                  const next = !v;
                  window.localStorage.setItem(STATS_VISIBLE_KEY, next ? "1" : "0");
                  return next;
                })
              }
              className="flex cursor-pointer items-center gap-1.5 rounded-v-lg border border-v-line bg-white px-3.5 py-2.5 text-xs font-medium text-v-muted-2 transition-colors duration-[120ms] hover:border-v-accent"
            >
              {statsVisible ? <Eye className="size-3.5" strokeWidth={1.8} /> : <EyeOff className="size-3.5" strokeWidth={1.8} />}
              {statsVisible ? "Hide metrics" : "Show metrics"}
            </button>
          ) : null}
          <span className="flex items-center gap-1.5 rounded-v-md border border-v-line bg-white px-3 py-[9px] text-xs font-medium text-v-body">
            <span className="size-1.5 shrink-0 rounded-full bg-v-ok" />
            Live · updated {lastUpdated ? relativeTime(lastUpdated, now) : "…"}
          </span>
          <button
            type="button"
            aria-label="Refresh agent list"
            title="Refresh"
            onClick={async () => {
              await loadAgents();
              onNotify("Refreshed", "Agent list is up to date.");
            }}
            className="flex size-[34px] shrink-0 cursor-pointer items-center justify-center rounded-v-md border border-v-line text-v-body transition-colors duration-[120ms] hover:bg-v-soft"
          >
            <RefreshCw className="size-4" strokeWidth={1.9} />
          </button>
          <Link href="/agent-creation">
            <Button data-tour="new-agent-button">
              <Plus className="size-4" strokeWidth={2.2} />
              New agent
            </Button>
          </Link>
        </div>
      </div>

      {loadError ? (
        <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
          {loadError}
        </div>
      ) : null}

      {/* Stat strip */}
      {hasAgents && statsVisible ? (
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-v-xl border border-v-line bg-v-line sm:grid-cols-3">
          {[
            { label: "CALLS TODAY", value: String(orgStats.callsToday), warn: false },
            { label: "AVG DURATION", value: formatDuration(orgStats.avgDuration), warn: false },
            {
              label: "AGENTS",
              value: String(agents.filter((a) => !rawAgents[a.id]?.archived).length),
              warn: false,
            },
          ].map((cell) => (
            <div key={cell.label} className="flex flex-col gap-1.5 bg-white px-5 py-4">
              <span className="font-mono text-[10px] font-semibold uppercase tracking-[.14em] text-v-dim">{cell.label}</span>
              <span
                className={`text-2xl font-bold tabular-nums ${cell.label === "AVG DURATION" && roundTripSlow ? "text-v-warn" : "text-v-fg"
                  }`}
              >
                {cell.value}
                {cell.label === "AVG DURATION" && roundTripSlow ? (
                  <span className="ml-1.5 text-xs font-medium lowercase text-v-warn">slow</span>
                ) : null}
              </span>
            </div>
          ))}
        </div>
      ) : null}

      {/* Toolbar */}
      <div data-tour="agents-search-toolbar" className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-56 flex-1">
          <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-v-dim" strokeWidth={1.9} />
          <input
            ref={searchRef}
            type="search"
            placeholder="Search agents, numbers, prompts…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="w-full rounded-v-lg border border-v-line-strong bg-white py-[11px] pl-10 pr-16 text-[13.5px] text-v-fg transition-colors duration-[120ms] placeholder:text-v-dim focus:border-[1.5px] focus:border-v-accent focus:shadow-[0_0_0_4px_rgba(31,78,232,0.10)] focus:outline-none"
          />
          <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rounded-[5px] border border-v-line px-1.5 py-0.5 font-mono text-[10.5px] text-v-faint">
            CTRL+K
          </span>
        </div>

        <Select size="sm" aria-label="Sort agents" value={sortBy} onChange={(e) => setSortBy(e.target.value as SortOption)}>
          {(Object.entries(SORT_LABEL) as [SortOption, string][]).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>

        <button
          type="button"
          onClick={() => setShowArchived((v) => !v)}
          className={`flex cursor-pointer items-center gap-1.5 rounded-v-lg border px-3.5 py-2.5 text-xs font-medium transition-colors duration-[120ms] ${showArchived
              ? "border-v-fg bg-v-fg text-white"
              : "border-v-line bg-white text-v-muted-2 hover:border-v-accent"
            }`}
        >
          <Archive className="size-3.5" strokeWidth={1.8} />
          {showArchived ? "Archived" : "Show archived"}
        </button>
      </div>

      {pageItems.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-v-xl border border-v-line bg-white p-14 text-center shadow-[var(--v-shadow-card)]">
          <h2 className="text-[22px] font-extrabold tracking-[-.4px] text-v-fg">
            {query
              ? `Nothing matches "${query}"`
              : showArchived
                ? "No archived agents"
                : "No agents answering yet"}
          </h2>
          <p className="max-w-sm text-sm font-light text-v-muted">
            {query
              ? "Try another word."
              : showArchived
                ? "Agents you archive will show up here."
                : "Create your first agent to start taking calls."}
          </p>
          {!query && !showArchived ? (
            <div className="mt-4 flex flex-wrap items-center justify-center gap-3">
              <Link href="/agent-creation">
                <Button>
                  <Plus className="size-4" strokeWidth={2.2} />
                  Start from scratch
                </Button>
              </Link>
            </div>
          ) : null}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-[18px] sm:grid-cols-2 lg:grid-cols-3">
          {pageItems.map((a, index) => (
            <AgentCard
              key={a.id}
              agent={a}
              raw={rawAgents[a.id]}
              stats={callStats[a.id] ?? EMPTY_STATS}
              busy={busyId === a.id}
              index={index}
              attachedByEmail={phoneNumbersByAgentId[a.id]?.last_link_by_email}
              onOpenEdit={() => goToEdit(a.id)}
              onTestCall={() => openTestCall(a.id)}
              onTestBrowser={() => openTestBrowser(a.id)}
              onOpenLogs={() => goToLogs(a.id)}
              onDuplicate={() => handleDuplicate(a)}
              onDelete={() => handleDelete(a)}
              onArchive={() => handleArchive(a)}
            />
          ))}
        </div>
      )}

      {testAgent && session?.orgId ? (
        <AgentTestModal key={testAgent.agent_id} agent={testAgent} orgId={session.orgId} onClose={() => setTestAgentId(null)} />
      ) : null}

      {testCallAgent ? (
        <TestCallSheet key={testCallAgent.agent_id} agent={testCallAgent} onClose={() => setTestCallAgentId(null)} onNotify={onNotify} />
      ) : null}

      <Dialog open={Boolean(deleteTarget)} onClose={() => setDeleteTarget(null)} widthClassName="max-w-sm">
        <DialogHeader title="Delete agent?" onClose={() => setDeleteTarget(null)} />
        <div className="flex flex-col gap-4 p-5">
          <p className="text-sm font-light leading-relaxed text-v-fg">
            Are you sure you want to delete <strong className="font-semibold">{deleteTarget?.name}</strong>? This
            can&apos;t be undone.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button variant="danger-outline" size="sm" disabled={busyId === deleteTarget?.id} onClick={confirmDelete}>
              {busyId === deleteTarget?.id ? <Spinner light={false} /> : null}
              Delete
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}
