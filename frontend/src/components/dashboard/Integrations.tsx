"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Brain,
  Check,
  Eye,
  EyeOff,
  Mic,
  Phone,
  Plug,
  Plus,
  Save,
  Search,
  Settings2,
  Trash2,
  Volume2,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { ProviderTypeBadge } from "@/components/ui/ProviderTypeBadge";
import { Spinner } from "@/components/ui/Spinner";
import { Dialog, DialogHeader } from "@/components/ui/Dialog";
import {
  deleteProviderAuth,
  getAuthCatalog,
  getProviderAuth,
  listConfiguredProviders,
  upsertProviderAuth,
} from "@/lib/api-client";
import type { AuthCatalog, AuthProviderCatalog } from "@/lib/catalog-types";
import { AUTH_KIND_ORDER, formatProviderTypeLabel, humanizeFieldKey, secretFieldNames } from "@/lib/catalog-utils";

const KIND_META: Record<
  string,
  { label: string; fullLabel: string; icon: LucideIcon; badgeClass: string }
> = {
  llm: {
    label: "LLM",
    fullLabel: "Language Models",
    icon: Brain,
    badgeClass: "bg-purple-500/10 text-purple-700 border-purple-500/20",
  },
  stt: {
    label: "STT",
    fullLabel: "Speech-to-Text",
    icon: Mic,
    badgeClass: "bg-sky-500/10 text-sky-700 border-sky-500/20",
  },
  tts: {
    label: "TTS",
    fullLabel: "Text-to-Speech",
    icon: Volume2,
    badgeClass: "bg-emerald-500/10 text-emerald-700 border-emerald-500/20",
  },
  telephony: {
    label: "Telephony",
    fullLabel: "Telephony",
    icon: Phone,
    badgeClass: "bg-amber-500/10 text-amber-700 border-amber-500/20",
  },
};

function kindMeta(kind: string) {
  return (
    KIND_META[kind] ?? {
      label: kind.slice(0, 3).toUpperCase(),
      fullLabel: kind.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      icon: Plug,
      badgeClass: "bg-v-soft text-v-muted-2 border-v-line",
    }
  );
}

type ProviderEntry = { providerId: string; catalog: AuthProviderCatalog };

function authValuesToForm(secrets: string[], auth: Record<string, unknown>): Record<string, string> {
  return Object.fromEntries(
    secrets.map((k) => {
      const v = auth[k];
      return [k, v != null && v !== "" ? String(v) : ""];
    }),
  );
}

function SecretField({
  fieldKey,
  label,
  description,
  value,
  visible,
  onToggleVisible,
  onChange,
  disabled,
}: {
  fieldKey: string;
  label: string;
  description?: string;
  value: string;
  visible: boolean;
  onToggleVisible: () => void;
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={fieldKey} className="text-[13px] font-medium text-v-fg">
        {label}
      </label>
      <div className="relative">
        <input
          id={fieldKey}
          type={visible ? "text" : "password"}
          autoComplete="off"
          spellCheck={false}
          disabled={disabled}
          placeholder={disabled ? "Loading…" : `Enter ${label.toLowerCase()}`}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-v-sm border border-v-line-strong bg-white py-2.5 pl-3.5 pr-10 text-[14px] transition-colors focus:border-v-accent focus:outline-none disabled:cursor-wait disabled:bg-v-soft/60"
        />
        <button
          type="button"
          disabled={disabled}
          onClick={onToggleVisible}
          aria-label={visible ? `Hide ${label}` : `Show ${label}`}
          className="absolute right-2 top-1/2 flex size-8 -translate-y-1/2 cursor-pointer items-center justify-center rounded-v-sm text-v-muted transition-colors hover:bg-v-soft hover:text-v-fg disabled:pointer-events-none disabled:opacity-40"
        >
          {visible ? <EyeOff className="size-4" strokeWidth={1.75} /> : <Eye className="size-4" strokeWidth={1.75} />}
        </button>
      </div>
      {description ? <span className="text-xs font-light text-v-muted">{description}</span> : null}
    </div>
  );
}

function ConnectModal({
  entry,
  configured,
  saving,
  onSave,
  onDisconnect,
  onClose,
}: {
  entry: ProviderEntry;
  configured: boolean;
  saving: boolean;
  onSave: (values: Record<string, string>) => Promise<void> | void;
  onDisconnect: () => Promise<void> | void;
  onClose: () => void;
}) {
  const { providerId, catalog } = entry;
  const secrets = useMemo(() => secretFieldNames(catalog), [catalog]);
  const displayName = catalog.name ?? providerId;
  const kinds = catalog.kinds ?? [];

  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(secrets.map((k) => [k, ""])),
  );
  const [visible, setVisible] = useState<Record<string, boolean>>({});
  const [loadingAuth, setLoadingAuth] = useState(configured);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!configured) return;
    let cancelled = false;
    setLoadingAuth(true);
    getProviderAuth(providerId)
      .then((res) => {
        if (!cancelled) setValues(authValuesToForm(secrets, res.auth));
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load saved credentials.");
      })
      .finally(() => {
        if (!cancelled) setLoadingAuth(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [configured, providerId]);

  const hasRequiredValues = secrets.every((k) => (catalog.required?.includes(k) ? values[k]?.trim() : true));

  async function handleSave() {
    setError("");
    if (!hasRequiredValues) {
      setError("Fill in the required fields.");
      return;
    }
    try {
      await onSave(values);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save credentials.");
    }
  }

  return (
    <Dialog open onClose={onClose} widthClassName="max-w-md">
      <DialogHeader
        title={`${configured ? "Manage" : "Connect"} ${displayName}`}
        subtitle={
          configured
            ? "Update your credentials or disconnect this integration."
            : `Enter your ${displayName} credentials to enable ${kinds
                .map((k) => kindMeta(k).fullLabel)
                .join(", ")}.`
        }
        onClose={onClose}
      />

      {/* Explicit max-height: flex+max-h alone does not create a scrollport. */}
      <div className="flex max-h-[calc(85vh-10rem)] flex-col gap-4 overflow-y-auto overscroll-contain p-5">
        {kinds.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {kinds.map((k) => {
              const meta = kindMeta(k);
              const Icon = meta.icon;
              return (
                <span
                  key={k}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${meta.badgeClass}`}
                >
                  <Icon className="size-3.5" strokeWidth={1.75} />
                  {meta.fullLabel}
                </span>
              );
            })}
          </div>
        ) : null}

        <div className="flex flex-col gap-3.5">
          {secrets.map((key) => {
            const field = catalog.fields?.[key];
            return (
              <SecretField
                key={key}
                fieldKey={`${providerId}-${key}`}
                label={humanizeFieldKey(key)}
                description={field?.description}
                value={values[key] ?? ""}
                visible={Boolean(visible[key])}
                onToggleVisible={() => setVisible((prev) => ({ ...prev, [key]: !prev[key] }))}
                onChange={(v) => setValues((prev) => ({ ...prev, [key]: v }))}
                disabled={loadingAuth}
              />
            );
          })}
        </div>

        <p className="text-xs font-light text-v-muted">
          Your credentials are encrypted and stored securely.
        </p>

        {error ? <p className="text-[12.5px] text-v-danger">{error}</p> : null}
      </div>

      <div className="flex shrink-0 flex-col-reverse gap-2 border-t border-v-line bg-white px-5 py-4 sm:flex-row sm:items-center">
        {configured ? (
          <Button variant="danger-outline" size="sm" disabled={saving} onClick={onDisconnect} className="sm:mr-auto">
            <Trash2 className="size-3.5" strokeWidth={1.75} />
            Disconnect
          </Button>
        ) : null}
        <Button size="sm" disabled={saving || loadingAuth} onClick={handleSave} className="sm:ml-auto">
          {saving ? (
            <>
              <Spinner /> Saving…
            </>
          ) : (
            <>
              <Save className="size-3.5" strokeWidth={1.75} />
              {configured ? "Update" : "Connect"}
            </>
          )}
        </Button>
      </div>
    </Dialog>
  );
}

export function Integrations({
  onNotify,
}: {
  onNotify: (title: string, note: string) => void;
}) {
  const [catalog, setCatalog] = useState<AuthCatalog | null>(null);
  const [configured, setConfigured] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [search, setSearch] = useState("");
  const [activeKind, setActiveKind] = useState<"all" | string>("all");
  const [activeProviderType, setActiveProviderType] = useState<"all" | string>("all");
  const [selected, setSelected] = useState<ProviderEntry | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoadError("");
    try {
      const [cat, cfg] = await Promise.all([getAuthCatalog(), listConfiguredProviders()]);
      setCatalog(cat);
      setConfigured(cfg);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Could not load integrations.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const allProviders = useMemo<ProviderEntry[]>(() => {
    if (!catalog) return [];
    return Object.entries(catalog)
      .map(([providerId, entry]) => ({ providerId, catalog: entry }))
      .sort((a, b) => (a.catalog.name ?? a.providerId).localeCompare(b.catalog.name ?? b.providerId));
  }, [catalog]);

  const isTelephony = (entry: AuthProviderCatalog) => (entry.kinds ?? []).includes("telephony");

  const telephonyList = useMemo(
    () => allProviders.filter(({ catalog: entry }) => isTelephony(entry)),
    [allProviders],
  );

  const nonTelephonyProviders = useMemo(
    () => allProviders.filter(({ catalog: entry }) => !isTelephony(entry)),
    [allProviders],
  );

  const kindTabs = useMemo(() => {
    const present = new Set<string>();
    nonTelephonyProviders.forEach(({ catalog: entry }) => (entry.kinds ?? []).forEach((k) => present.add(k)));
    return [
      ...AUTH_KIND_ORDER.filter((k) => k !== "telephony" && present.has(k)),
      ...[...present]
        .filter((k) => k !== "telephony" && !(AUTH_KIND_ORDER as readonly string[]).includes(k))
        .sort(),
    ];
  }, [nonTelephonyProviders]);

  const providerTypeTabs = useMemo(() => {
    const present = new Set<string>();
    allProviders.forEach(({ catalog }) => {
      if (catalog.provider_type) present.add(catalog.provider_type);
    });
    return (["cloud", "adapter", "local"] as const).filter((t) => present.has(t));
  }, [allProviders]);

  const matchesProviderType = useCallback(
    (entry: AuthProviderCatalog) =>
      activeProviderType === "all" || entry.provider_type === activeProviderType,
    [activeProviderType],
  );

  const connectedList = useMemo(
    () =>
      nonTelephonyProviders.filter(
        ({ providerId, catalog: entry }) => configured.includes(providerId) && matchesProviderType(entry),
      ),
    [nonTelephonyProviders, configured, matchesProviderType],
  );

  const filteredTelephonyList = useMemo(
    () => telephonyList.filter(({ catalog: entry }) => matchesProviderType(entry)),
    [telephonyList, matchesProviderType],
  );

  const availableList = useMemo(() => {
    return nonTelephonyProviders.filter(({ providerId, catalog: entry }) => {
      if (configured.includes(providerId)) return false;
      const name = entry.name ?? providerId;
      const matchesSearch =
        search.trim() === "" ||
        name.toLowerCase().includes(search.trim().toLowerCase()) ||
        providerId.toLowerCase().includes(search.trim().toLowerCase());
      const matchesKind = activeKind === "all" || (entry.kinds ?? []).includes(activeKind);
      const matchesType = matchesProviderType(entry);
      return matchesSearch && matchesKind && matchesType;
    });
  }, [nonTelephonyProviders, configured, search, activeKind, matchesProviderType]);

  async function handleSave(entry: ProviderEntry, values: Record<string, string>) {
    setSaving(true);
    try {
      const secrets = secretFieldNames(entry.catalog);
      const auth: Record<string, unknown> = {};
      for (const key of secrets) {
        const v = values[key]?.trim();
        if (v) auth[key] = v;
      }
      if (!Object.keys(auth).length) throw new Error("Enter at least one credential field.");
      await upsertProviderAuth(entry.providerId, auth);
      onNotify("Saved", `${entry.catalog.name ?? entry.providerId} credentials updated.`);
      setSelected(null);
      await load();
    } finally {
      setSaving(false);
    }
  }

  async function handleDisconnect(entry: ProviderEntry) {
    setSaving(true);
    try {
      await deleteProviderAuth(entry.providerId);
      onNotify("Removed", `${entry.catalog.name ?? entry.providerId} credentials deleted.`);
      setSelected(null);
      await load();
    } catch (err) {
      onNotify("Couldn't disconnect", err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setSaving(false);
    }
  }

  const hasActiveFilters =
    search.trim().length > 0 || activeKind !== "all" || activeProviderType !== "all";
  const clearFilters = () => {
    setSearch("");
    setActiveKind("all");
    setActiveProviderType("all");
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1.5 border-b border-v-line pb-6">
        <h1 className="text-3xl font-semibold tracking-tight">Integrations</h1>
        <p className="max-w-2xl text-sm font-light leading-relaxed text-v-muted">
          Connect API providers to enable speech recognition, voice synthesis, and language models.
        </p>
      </div>

      {loadError ? (
        <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
          {loadError}
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-v-muted">
          <Spinner light={false} /> Loading integrations…
        </div>
      ) : (
        <>
          {providerTypeTabs.length > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[10px] uppercase tracking-[.16em] text-v-muted">Provider type</span>
              <div className="flex flex-wrap gap-1 rounded-v-sm border border-v-line bg-v-soft/50 p-1">
                <button
                  type="button"
                  onClick={() => setActiveProviderType("all")}
                  aria-pressed={activeProviderType === "all"}
                  className={`cursor-pointer rounded-v-sm px-3 py-1.5 text-[13px] font-medium transition-colors ${
                    activeProviderType === "all"
                      ? "bg-white text-v-fg shadow-[0_1px_0_rgba(11,11,12,0.06)]"
                      : "text-v-muted hover:text-v-fg"
                  }`}
                >
                  All
                </button>
                {providerTypeTabs.map((type) => {
                  const active = activeProviderType === type;
                  const label = formatProviderTypeLabel(type) ?? type;
                  return (
                    <button
                      key={type}
                      type="button"
                      onClick={() => setActiveProviderType(type)}
                      aria-pressed={active}
                      className={`cursor-pointer rounded-v-sm px-3 py-1.5 text-[13px] font-medium transition-colors ${
                        active ? "bg-white text-v-fg shadow-[0_1px_0_rgba(11,11,12,0.06)]" : "text-v-muted hover:text-v-fg"
                      }`}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
              {activeProviderType !== "all" ? (
                <Button size="sm" variant="ghost" onClick={() => setActiveProviderType("all")}>
                  Clear type
                </Button>
              ) : null}
            </div>
          ) : null}

          {connectedList.length > 0 ? (
            <section className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <h2 className="font-mono text-[10px] uppercase tracking-[.16em] text-v-muted">Connected</h2>
                <Badge tone="accent">{connectedList.length}</Badge>
              </div>
              <div className="overflow-hidden rounded-v-md border border-v-line bg-white">
                <div className="divide-y divide-v-line">
                  {connectedList.map((entry) => {
                    const name = entry.catalog.name ?? entry.providerId;
                    return (
                      <div
                        key={entry.providerId}
                        className="flex items-center justify-between gap-3 px-4 py-3.5 transition-colors hover:bg-v-soft/50"
                      >
                        <div className="flex min-w-0 items-center gap-3">
                          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-emerald-500/10">
                            <Check className="size-4 text-emerald-600" strokeWidth={2} />
                          </span>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-medium text-v-fg">{name}</span>
                              <div className="flex gap-1">
                                {(entry.catalog.kinds ?? []).map((k) => {
                                  const meta = kindMeta(k);
                                  return (
                                    <span
                                      key={k}
                                      className={`rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${meta.badgeClass}`}
                                    >
                                      {meta.label}
                                    </span>
                                  );
                                })}
                                <ProviderTypeBadge providerType={entry.catalog.provider_type} />
                              </div>
                            </div>
                          </div>
                        </div>
                        <Button variant="ghost" size="sm" onClick={() => setSelected(entry)}>
                          <Settings2 className="size-3.5" strokeWidth={1.75} />
                          Manage
                        </Button>
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>
          ) : null}

          {telephonyList.length > 0 ? (
            <section className="flex flex-col gap-3">
              <div className="flex items-center gap-2">
                <h2 className="font-mono text-[10px] uppercase tracking-[.16em] text-v-muted">Telephony</h2>
              </div>
              <div className="overflow-hidden rounded-v-md border border-v-line bg-white">
                <div className="divide-y divide-v-line">
                  {filteredTelephonyList.map((entry) => {
                    const name = entry.catalog.name ?? entry.providerId;
                    const connected = configured.includes(entry.providerId);
                    return (
                      <div
                        key={entry.providerId}
                        className="flex items-center justify-between gap-3 px-4 py-3.5 transition-colors hover:bg-v-soft/50"
                      >
                        <div className="flex min-w-0 items-center gap-3">
                          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-amber-500/10">
                            <Phone className="size-4 text-amber-600" strokeWidth={1.75} />
                          </span>
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-medium text-v-fg">{name}</span>
                              <span className="rounded-full border border-v-line bg-v-soft px-1.5 py-0.5 text-[10px] font-medium text-v-muted-2">
                                Telephony
                              </span>
                              <ProviderTypeBadge providerType={entry.catalog.provider_type} />
                              {connected ? (
                                <span className="flex size-5 items-center justify-center rounded-full bg-emerald-500/10">
                                  <Check className="size-3 text-emerald-600" strokeWidth={2} />
                                </span>
                              ) : null}
                            </div>
                          </div>
                        </div>
                        <Button variant="ghost" size="sm" onClick={() => setSelected(entry)}>
                          {connected ? (
                            <>
                              <Settings2 className="size-3.5" strokeWidth={1.75} />
                              Manage
                            </>
                          ) : (
                            <>
                              <Plus className="size-3.5" strokeWidth={1.75} />
                              Connect
                            </>
                          )}
                        </Button>
                      </div>
                    );
                  })}
                </div>
              </div>
            </section>
          ) : null}

          <section className="flex flex-col gap-4">
            <div className="flex items-center gap-2">
              <h2 className="font-mono text-[10px] uppercase tracking-[.16em] text-v-muted">Available</h2>
            </div>

            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="relative min-w-0 flex-1 sm:max-w-sm">
                <Search
                  className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-v-muted"
                  strokeWidth={1.75}
                />
                <input
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search providers…"
                  aria-label="Search providers"
                  className="w-full rounded-v-sm border border-v-line bg-v-soft/80 py-2.5 pl-10 pr-3.5 text-[14px] transition-colors placeholder:text-v-muted focus:border-v-accent focus:bg-white focus:outline-none"
                />
              </div>

              <div className="flex flex-wrap gap-1 rounded-v-sm border border-v-line bg-v-soft/50 p-1">
                <button
                  type="button"
                  onClick={() => setActiveKind("all")}
                  aria-pressed={activeKind === "all"}
                  className={`cursor-pointer rounded-v-sm px-3 py-1.5 text-[13px] font-medium transition-colors ${
                    activeKind === "all" ? "bg-white text-v-fg shadow-[0_1px_0_rgba(11,11,12,0.06)]" : "text-v-muted hover:text-v-fg"
                  }`}
                >
                  All kinds
                </button>
                {kindTabs.map((k) => {
                  const meta = kindMeta(k);
                  const Icon = meta.icon;
                  const active = activeKind === k;
                  return (
                    <button
                      key={k}
                      type="button"
                      onClick={() => setActiveKind(k)}
                      aria-pressed={active}
                      className={`inline-flex cursor-pointer items-center gap-1.5 rounded-v-sm px-3 py-1.5 text-[13px] font-medium transition-colors ${
                        active ? "bg-white text-v-fg shadow-[0_1px_0_rgba(11,11,12,0.06)]" : "text-v-muted hover:text-v-fg"
                      }`}
                    >
                      <Icon className="size-3.5" strokeWidth={1.75} />
                      {meta.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {availableList.length > 0 ? (
              <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
                {availableList.map((entry) => {
                  const name = entry.catalog.name ?? entry.providerId;
                  return (
                    <button
                      key={entry.providerId}
                      type="button"
                      onClick={() => setSelected(entry)}
                      className="group flex cursor-pointer flex-col gap-2 rounded-v-md border border-v-line bg-white p-4 text-left transition-shadow hover:shadow-[0_4px_16px_rgba(11,11,12,0.08)]"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <span className="font-medium text-v-fg">{name}</span>
                        <span className="flex items-center gap-1 rounded-full border border-v-line px-2.5 py-1 text-xs font-medium text-v-muted opacity-0 transition-opacity group-hover:opacity-100">
                          <Plus className="size-3.5" strokeWidth={1.75} />
                          Connect
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-1">
                        {(entry.catalog.kinds ?? []).map((k) => {
                          const meta = kindMeta(k);
                          return (
                            <span
                              key={k}
                              className={`rounded-full border px-1.5 py-0.5 text-[10px] font-medium ${meta.badgeClass}`}
                            >
                              {meta.label}
                            </span>
                          );
                        })}
                        <ProviderTypeBadge providerType={entry.catalog.provider_type} />
                      </div>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2 rounded-v-md border border-dashed border-v-line bg-white px-6 py-12 text-center">
                <div className="rounded-full bg-v-soft p-3">
                  <Search className="size-5 text-v-muted" strokeWidth={1.75} />
                </div>
                <p className="text-sm text-v-muted">
                  {hasActiveFilters ? "No providers match your filters" : "All providers are connected"}
                </p>
                {hasActiveFilters ? (
                  <Button size="sm" variant="ghost" onClick={clearFilters}>
                    Clear filters
                  </Button>
                ) : null}
              </div>
            )}
          </section>
        </>
      )}

      {selected ? (
        <ConnectModal
          entry={selected}
          configured={configured.includes(selected.providerId)}
          saving={saving}
          onSave={(values) => handleSave(selected, values)}
          onDisconnect={() => handleDisconnect(selected)}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  );
}
