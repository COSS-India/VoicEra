"use client";

import { Fragment, useEffect, useMemo, useState } from "react";
import { Check, Copy, HelpCircle, Link2, Phone, Search, Unlink } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { Dialog, DialogHeader } from "@/components/ui/Dialog";
import { usePhoneNumbers } from "@/hooks/usePhoneNumbers";
import { listProviderInventory } from "@/lib/api/phone-numbers";
import type { AgentApiResponse, PhoneNumberItem } from "@/lib/api-types";
import type { ProviderList } from "@/lib/catalog-types";

function formatDateTime(iso?: string | null): string {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "–";
  return d.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function providerLabel(providers: ProviderList, provider: string): string {
  return providers[provider]?.name ?? provider;
}

function activityLine(number: PhoneNumberItem, agentsById: Map<string, AgentApiResponse>): string | null {
  if (!number.last_link_by_email || !number.last_link_action) return null;
  const when = formatDateTime(number.last_link_at);
  if (number.last_link_action === "detached") {
    const agentName = number.last_link_agent_id
      ? agentsById.get(number.last_link_agent_id)?.name ?? "an agent"
      : "an agent";
    return `Detached from ${agentName} by ${number.last_link_by_email} · ${when}`;
  }
  if (number.last_link_action === "attached") {
    return `Attached by ${number.last_link_by_email} · ${when}`;
  }
  if (number.last_link_action === "imported") {
    return `Added by ${number.last_link_by_email} · ${when}`;
  }
  return `${number.last_link_action} by ${number.last_link_by_email} · ${when}`;
}

function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <button
      type="button"
      aria-label="Copy number"
      onClick={copy}
      className="flex size-7 shrink-0 cursor-pointer items-center justify-center rounded-v-sm border border-v-line text-v-muted transition-colors hover:border-v-accent hover:text-v-accent"
    >
      {copied ? <Check className="size-3.5" strokeWidth={1.75} /> : <Copy className="size-3.5" strokeWidth={1.75} />}
    </button>
  );
}

/** Docs for adding/porting a number on each provider's own console — linked
 * from the Add Number dialog header for Plivo / Vobiz. */
const PROVIDER_ADD_NUMBER_DOCS: Record<string, string> = {
  plivo: "https://www.plivo.com/docs/cli/voice-agent/connect-number",
  vobiz: "https://www.vobiz.ai/docs/applications/attach-number",
};

/** Provider account inventory -> pick a number -> import it (no agent yet).
 * Only providers with auth configured under Integrations are offered, and the
 * account's numbers load automatically (no manual "list numbers" step). */
function AddNumberDialog({
  providers,
  existingNumbers,
  busy,
  onImport,
  onClose,
}: {
  providers: ProviderList;
  existingNumbers: Set<string>;
  busy: boolean;
  onImport: (phoneNumber: string, provider: string) => Promise<boolean>;
  onClose: () => void;
}) {
  const providerOptions = useMemo(() => Object.values(providers), [providers]);
  const [provider, setProvider] = useState(providerOptions[0]?.provider ?? "");
  const [inventory, setInventory] = useState<string[]>([]);
  const [invLoading, setInvLoading] = useState(false);
  const [invError, setInvError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [loadedFor, setLoadedFor] = useState<string | null>(null);
  const [numberQuery, setNumberQuery] = useState("");

  useEffect(() => {
    if (!provider) return;
    let cancelled = false;
    setInvLoading(true);
    setInvError("");
    setSelected(null);
    listProviderInventory(provider)
      .then((nums) => {
        if (cancelled) return;
        setInventory(nums);
        setLoadedFor(provider);
      })
      .catch((err) => {
        if (!cancelled) setInvError(err instanceof Error ? err.message : "Couldn't load provider numbers.");
      })
      .finally(() => {
        if (!cancelled) setInvLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [provider]);

  const availableNumbers = inventory.filter((n) => !existingNumbers.has(n));
  const q = numberQuery.trim().toLowerCase();
  const shownNumbers = q ? availableNumbers.filter((n) => n.toLowerCase().includes(q)) : availableNumbers;
  const docsUrl = PROVIDER_ADD_NUMBER_DOCS[provider];
  const providerName = providers[provider]?.name ?? provider;

  return (
    <Dialog open onClose={onClose} widthClassName="max-w-lg">
      <DialogHeader
        title="Add a new number"
        subtitle="List your telephony provider's account and import one into this workspace."
        onClose={onClose}
        titleEnd={
          docsUrl ? (
            <a
              href={docsUrl}
              target="_blank"
              rel="noreferrer"
              title={`Help finding numbers in ${providerName}`}
              aria-label={`Open ${providerName} docs for attaching a number`}
              className="flex size-7 shrink-0 items-center justify-center rounded-v-sm border border-v-line text-v-muted transition-colors hover:border-v-accent hover:text-v-accent"
            >
              <HelpCircle className="size-3.5" strokeWidth={1.9} />
            </a>
          ) : null
        }
      />
      <div className="flex flex-col gap-4 p-5">
        <div className="flex flex-col gap-1.5">
          <label className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">Provider</label>
          <div className="flex flex-wrap gap-2">
            {providerOptions.length === 0 ? (
              <span className="text-sm font-light text-v-muted">
                No telephony providers connected yet — add one under Integrations first.
              </span>
            ) : (
              providerOptions.map((p) => (
                <button
                  key={p.provider}
                  type="button"
                  onClick={() => setProvider(p.provider)}
                  className={`cursor-pointer rounded-full border px-3.5 py-2 text-xs font-medium transition-colors ${
                    provider === p.provider
                      ? "border-v-fg bg-v-fg text-white"
                      : "border-v-line text-v-muted-2 hover:border-v-accent"
                  }`}
                >
                  {p.name}
                </button>
              ))
            )}
          </div>
        </div>

        {invLoading ? (
          <div className="flex items-center gap-2 py-4 text-sm text-v-muted">
            <Spinner light={false} /> Loading numbers on this account…
          </div>
        ) : invError ? (
          <p className="text-sm text-v-danger">{invError}</p>
        ) : loadedFor === provider && availableNumbers.length === 0 ? (
          <div className="flex flex-col items-center gap-1 rounded-v-md border border-dashed border-v-line p-6 text-center">
            <span className="text-sm font-semibold text-v-fg">No numbers linked</span>
            <span className="text-xs font-light text-v-muted">
              This provider account has no numbers yet.
            </span>
          </div>
        ) : loadedFor === provider ? (
          <div className="flex flex-col gap-2.5">
            <div className="relative">
              <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-v-muted" />
              <input
                type="search"
                placeholder="Search numbers"
                value={numberQuery}
                onChange={(e) => setNumberQuery(e.target.value)}
                className="w-full rounded-v-lg border border-v-line-strong bg-white py-2.5 pl-10 pr-3.5 text-[13px] text-v-fg transition-colors duration-[120ms] focus:border-v-accent"
              />
            </div>
            {shownNumbers.length === 0 ? (
              <p className="text-sm font-light text-v-muted">Nothing matches &quot;{numberQuery}&quot;.</p>
            ) : (
              <div className="flex max-h-56 flex-col gap-1.5 overflow-y-auto rounded-v-md border border-v-line p-2">
                {shownNumbers.map((n) => (
                  <button
                    key={n}
                    type="button"
                    onClick={() => setSelected(n)}
                    className={`flex cursor-pointer items-center justify-between rounded-v-sm px-3 py-2 text-left text-sm transition-colors ${
                      selected === n ? "bg-v-fg text-white" : "hover:bg-v-soft"
                    }`}
                  >
                    {n}
                    {selected === n ? <Check className="size-4" strokeWidth={1.75} /> : null}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : null}

        <div className="flex justify-end gap-2 border-t border-v-line pt-4">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!selected || busy}
            onClick={async () => {
              if (!selected) return;
              const ok = await onImport(selected, provider);
              if (ok) onClose();
            }}
          >
            {busy ? <Spinner /> : null}
            Add number
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

/** Pick a telephony agent (matching the number's provider) to attach to. */
function AttachDialog({
  number,
  agents,
  busy,
  onAttach,
  onClose,
}: {
  number: PhoneNumberItem;
  agents: AgentApiResponse[];
  busy: boolean;
  onAttach: (agentId: string) => Promise<boolean>;
  onClose: () => void;
}) {
  const eligible = useMemo(
    () =>
      agents.filter(
        (a) =>
          a.agent_category === "telephony" &&
          a.telephony?.provider === number.provider &&
          !a.linked_phone_number,
      ),
    [agents, number.provider],
  );
  const [agentId, setAgentId] = useState<string | null>(null);
  const [agentQuery, setAgentQuery] = useState("");

  const filtered = useMemo(() => {
    const q = agentQuery.trim().toLowerCase();
    if (!q) return eligible;
    return eligible.filter((a) => a.name.toLowerCase().includes(q));
  }, [eligible, agentQuery]);

  return (
    <Dialog open onClose={onClose} widthClassName="max-w-md">
      <DialogHeader
        title={`Attach ${number.phone_number}`}
        subtitle="Choose a telephony agent on the same provider with no number attached yet."
        onClose={onClose}
      />
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1 flex-col gap-3 px-5 pt-5">
          {eligible.length === 0 ? (
            <p className="pb-1 text-sm font-light text-v-muted">
              No eligible {number.provider} telephony agents. Create one, or detach its current number
              first.
            </p>
          ) : (
            <>
              <div className="relative shrink-0">
                <Search className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-v-muted" />
                <input
                  type="search"
                  placeholder="Search agents"
                  value={agentQuery}
                  onChange={(e) => setAgentQuery(e.target.value)}
                  className="w-full rounded-v-lg border border-v-line-strong bg-white py-2.5 pl-10 pr-3.5 text-[13px] text-v-fg transition-colors duration-[120ms] focus:border-v-accent focus:outline-none"
                />
              </div>
              {filtered.length === 0 ? (
                <p className="text-sm font-light text-v-muted">
                  Nothing matches &quot;{agentQuery.trim()}&quot;.
                </p>
              ) : (
                <div className="flex max-h-[min(50vh,22rem)] min-h-0 flex-col gap-1.5 overflow-y-auto overscroll-contain rounded-v-md border border-v-line p-2">
                  {filtered.map((a) => (
                    <button
                      key={a.agent_id}
                      type="button"
                      onClick={() => setAgentId(a.agent_id)}
                      className={`flex shrink-0 cursor-pointer items-center justify-between rounded-v-sm px-3 py-2 text-left text-sm transition-colors ${
                        agentId === a.agent_id ? "bg-v-fg text-white" : "hover:bg-v-soft"
                      }`}
                    >
                      {a.name}
                      {agentId === a.agent_id ? <Check className="size-4" strokeWidth={1.75} /> : null}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
        <div className="flex shrink-0 justify-end gap-2 border-t border-v-line p-5 pt-4">
          <Button variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button
            size="sm"
            disabled={!agentId || busy}
            onClick={async () => {
              if (!agentId) return;
              const ok = await onAttach(agentId);
              if (ok) onClose();
            }}
          >
            {busy ? <Spinner /> : null}
            Attach
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

export function PhoneNumbers({ onNotify }: { onNotify: (title: string, note: string) => void }) {
  const {
    numbers,
    agents,
    providers,
    configuredProviders,
    loading,
    loadError,
    busyNumber,
    importNumber,
    attachToAgent,
    detach,
  } = usePhoneNumbers(onNotify);
  const [query, setQuery] = useState("");
  const [addOpen, setAddOpen] = useState(false);
  const [attachTarget, setAttachTarget] = useState<PhoneNumberItem | null>(null);
  const [detachTarget, setDetachTarget] = useState<PhoneNumberItem | null>(null);

  const agentsById = useMemo(() => new Map(agents.map((a) => [a.agent_id, a])), [agents]);
  const existingNumbers = useMemo(() => new Set(numbers.map((n) => n.phone_number)), [numbers]);
  // Only offer providers that are both a real telephony provider and have
  // auth configured under Integrations — otherwise "list numbers" has
  // nothing to authenticate with.
  const connectedProviders = useMemo(
    () => Object.fromEntries(Object.entries(providers).filter(([id]) => configuredProviders.has(id))),
    [providers, configuredProviders],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return numbers;
    return numbers.filter(
      (n) =>
        n.phone_number.toLowerCase().includes(q) ||
        n.provider.toLowerCase().includes(q) ||
        (n.agent_id ? agentsById.get(n.agent_id)?.name.toLowerCase().includes(q) : false),
    );
  }, [numbers, query, agentsById]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-v-line pb-6">
        <div className="flex flex-col gap-1.5">
          <h1 className="text-3xl font-semibold tracking-tight">Numbers</h1>
          <p className="max-w-[62ch] text-sm font-light leading-relaxed text-v-muted">
            Import numbers from your telephony provider and attach them to agents.
          </p>
        </div>
        <Button onClick={() => setAddOpen(true)}>
          <Phone className="size-4" strokeWidth={1.75} />
          Add New Number
        </Button>
      </div>

      {loadError ? (
        <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
          {loadError}
        </div>
      ) : null}

      <div className="relative max-w-md">
        <Search className="pointer-events-none absolute left-4 top-1/2 h-4 w-4 -translate-y-1/2 text-v-muted" />
        <input
          type="search"
          placeholder="Search numbers"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full rounded-v-lg border border-v-line-strong bg-white py-3 pl-11 pr-4 text-[13.5px] text-v-fg transition-colors duration-[120ms] focus:border-v-accent"
        />
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-v-muted">
          <Spinner light={false} /> Loading numbers…
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center gap-1 rounded-v-md border border-dashed border-v-line bg-white p-12 text-center">
          <span className="text-sm font-semibold">{query ? "Nothing matches" : "No numbers yet"}</span>
          <span className="text-xs font-light text-v-muted">
            {query ? "Try another search." : "Add a number from your telephony provider to get started."}
          </span>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-v-md border border-v-line bg-white">
          <table className="w-full min-w-[720px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-v-line text-left font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">
                <th className="px-4 py-3 font-medium">Number</th>
                <th className="px-4 py-3 font-medium">Added On</th>
                <th className="px-4 py-3 font-medium">Provider</th>
                <th className="px-4 py-3 font-medium">Used By</th>
                <th className="px-4 py-3 text-right font-medium">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((n) => {
                const busy = busyNumber === n.phone_number;
                const agentName = n.agent_id ? agentsById.get(n.agent_id)?.name : undefined;
                const activity = activityLine(n, agentsById);
                return (
                  <Fragment key={n.phone_number}>
                    <tr className="border-b border-v-line last:border-b-0">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <CopyButton value={n.phone_number} />
                          <span className="font-medium">{n.phone_number}</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-v-muted">{formatDateTime(n.created_at)}</td>
                      <td className="px-4 py-3">
                        <Badge tone="accent">{providerLabel(providers, n.provider)}</Badge>
                      </td>
                      <td className="px-4 py-3">{agentName ?? <span className="text-v-muted">–</span>}</td>
                      <td className="px-4 py-3 text-right">
                        {n.agent_id ? (
                          <Button variant="danger-outline" size="sm" disabled={busy} onClick={() => setDetachTarget(n)}>
                            {busy ? <Spinner light={false} /> : <Unlink className="size-3.5" strokeWidth={1.75} />}
                            Detach
                          </Button>
                        ) : (
                          <Button variant="primary" size="sm" disabled={busy} onClick={() => setAttachTarget(n)}>
                            {busy ? <Spinner /> : <Link2 className="size-3.5" strokeWidth={1.75} />}
                            Attach
                          </Button>
                        )}
                      </td>
                    </tr>
                    {activity ? (
                      <tr className="border-b border-v-line bg-v-soft/40 last:border-b-0">
                        <td colSpan={5} className="px-4 py-2 text-xs font-light text-v-muted">
                          <span className="inline-flex items-center gap-1.5">
                            <Link2 className="size-3 shrink-0" strokeWidth={1.75} />
                            {activity}
                          </span>
                        </td>
                      </tr>
                    ) : null}
                  </Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {addOpen ? (
        <AddNumberDialog
          providers={connectedProviders}
          existingNumbers={existingNumbers}
          busy={busyNumber !== null}
          onImport={importNumber}
          onClose={() => setAddOpen(false)}
        />
      ) : null}

      {attachTarget ? (
        <AttachDialog
          number={attachTarget}
          agents={agents}
          busy={busyNumber === attachTarget.phone_number}
          onAttach={(agentId) => attachToAgent(attachTarget, agentId)}
          onClose={() => setAttachTarget(null)}
        />
      ) : null}

      {detachTarget ? (
        <Dialog open onClose={() => setDetachTarget(null)} widthClassName="max-w-md">
          <DialogHeader title="Detach this number?" onClose={() => setDetachTarget(null)} />
          <div className="flex flex-col gap-4 p-5">
            <p className="text-sm font-light text-v-body">
              Do you want to detach {detachTarget.phone_number} from its agent?
            </p>
            <div className="flex justify-end gap-2 border-t border-v-line pt-4">
              <Button variant="ghost" size="sm" onClick={() => setDetachTarget(null)}>
                Cancel
              </Button>
              <Button
                variant="danger-outline"
                size="sm"
                disabled={busyNumber === detachTarget.phone_number}
                onClick={async () => {
                  await detach(detachTarget);
                  setDetachTarget(null);
                }}
              >
                {busyNumber === detachTarget.phone_number ? <Spinner light={false} /> : null}
                Detach
              </Button>
            </div>
          </div>
        </Dialog>
      ) : null}
    </div>
  );
}
