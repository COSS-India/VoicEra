"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckCircle2, Pencil, Plug, Plus, Save, Trash2, XCircle } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Dialog, DialogHeader } from "@/components/ui/Dialog";
import { Input, Select } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Spinner";
import { Switch } from "@/components/ui/Switch";
import {
  createProviderConnection,
  deleteProviderConnection,
  listProviderConnections,
  probeProviderEndpoint,
  testProviderConnection,
  updateProviderConnection,
} from "@/lib/api-client";
import type { HistoryMode, ProviderConnection, SystemPromptMode } from "@/lib/api-types";

/** A provider whose endpoint the operator supplies (`connection_based` in the
 * auth catalog). Each one can hold several endpoints, so the vendor key form
 * does not apply to it. */
export interface ConnectionProviderOption {
  providerId: string;
  name: string;
}

interface FormState {
  provider: string;
  name: string;
  baseUrl: string;
  apiKey: string;
  models: string;
  defaultModel: string;
  supportsTools: boolean;
  historyMode: HistoryMode;
  systemPromptMode: SystemPromptMode;
  sendCallerPhone: boolean;
  enabled: boolean;
}

const HISTORY_MODE_LABELS: Record<HistoryMode, string> = {
  full: "Full conversation",
  current_turn: "Current turn only",
};


function emptyForm(provider: string): FormState {
  return {
    provider,
    name: "",
    baseUrl: "",
    apiKey: "",
    models: "",
    defaultModel: "",
    supportsTools: false,
    historyMode: "full",
    systemPromptMode: "send",
    sendCallerPhone: false,
    enabled: true,
  };
}

function formFrom(connection: ProviderConnection): FormState {
  return {
    provider: connection.provider,
    name: connection.name,
    baseUrl: connection.base_url,
    // Stored keys come back masked; an empty box means "keep the saved key".
    apiKey: "",
    models: connection.models.join(", "),
    defaultModel: connection.default_model ?? "",
    supportsTools: connection.supports_tools,
    historyMode: connection.history_mode ?? "full",
    systemPromptMode: connection.system_prompt_mode ?? "send",
    sendCallerPhone: connection.send_caller_phone ?? false,
    enabled: connection.enabled,
  };
}

function parseModels(value: string): string[] {
  return value
    .split(",")
    .map((m) => m.trim())
    .filter(Boolean);
}

function ConnectionDialog({
  providers,
  editing,
  onClose,
  onSaved,
  onNotify,
}: {
  providers: ConnectionProviderOption[];
  editing: ProviderConnection | null;
  onClose: () => void;
  onSaved: () => Promise<void> | void;
  onNotify: (title: string, note: string) => void;
}) {
  const [form, setForm] = useState<FormState>(() =>
    editing ? formFrom(editing) : emptyForm(providers[0]?.providerId ?? "openai_compatible"),
  );
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; note: string } | null>(null);
  const [error, setError] = useState("");

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  async function handleTest() {
    setTesting(true);
    setTestResult(null);
    try {
      // The saved key never comes back from the API, so an edit dialog with an
      // empty key box has to be tested by id — and only against the URL it was
      // saved with, since that is the pair the server holds.
      const typedKey = form.apiKey.trim();
      const stored = typedKey ? null : editing;
      if (stored && form.baseUrl.trim() !== stored.base_url) {
        setTestResult({
          ok: false,
          note: "Save the new URL first, or enter the API key to test it now.",
        });
        return;
      }
      // An endpoint that serves no /models list is checked with a one-token
      // completion instead, which needs a model id to ask for.
      const probeModel = form.defaultModel.trim() || parseModels(form.models)[0];
      const result = stored
        ? await testProviderConnection(stored.id)
        : await probeProviderEndpoint(form.baseUrl, typedKey || undefined, probeModel);
      if (result.ok) {
        const latency = result.latency_ms != null ? `, ${result.latency_ms} ms` : "";
        if (result.models.length > 0) {
          // A published list is the only reliable source of model ids, so adopt it.
          set("models", result.models.join(", "));
          setTestResult({
            ok: true,
            note: `Reachable — ${result.models.length} model(s)${latency}.`,
          });
        } else {
          setTestResult({
            ok: true,
            note: result.note || `Reachable${latency}.`,
          });
        }
      } else {
        setTestResult({ ok: false, note: result.error ?? "Endpoint did not answer." });
      }
    } catch (err) {
      setTestResult({
        ok: false,
        note: err instanceof Error ? err.message : "Could not reach the endpoint.",
      });
    } finally {
      setTesting(false);
    }
  }

  async function handleSave() {
    setError("");
    if (!form.name.trim() || !form.baseUrl.trim()) {
      setError("Name and endpoint URL are required.");
      return;
    }
    if (!editing && !form.apiKey.trim()) {
      setError("An API key is required. Use any placeholder if the endpoint checks none.");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: form.name.trim(),
        base_url: form.baseUrl.trim(),
        models: parseModels(form.models),
        default_model: form.defaultModel.trim() || null,
        supports_tools: form.supportsTools,
        history_mode: form.historyMode,
        system_prompt_mode: form.systemPromptMode,
        send_caller_phone: form.sendCallerPhone,
        enabled: form.enabled,
      };
      if (editing) {
        await updateProviderConnection(editing.id, {
          ...payload,
          // Omitted key keeps the stored one.
          ...(form.apiKey.trim() ? { api_key: form.apiKey.trim() } : {}),
        });
        onNotify("Saved", `${payload.name} updated.`);
      } else {
        await createProviderConnection({
          ...payload,
          provider: form.provider,
          api_key: form.apiKey.trim(),
        });
        onNotify("Added", `${payload.name} is ready to use.`);
      }
      await onSaved();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the endpoint.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onClose={onClose} widthClassName="max-w-lg">
      <DialogHeader
        title={editing ? `Edit ${editing.name}` : "Add OpenAI-compatible endpoint"}
        subtitle="Any server that speaks the OpenAI chat API — vLLM, Ollama, TGI, or a hosted gateway."
        onClose={onClose}
      />

      <div className="flex max-h-[calc(85vh-10rem)] flex-col gap-4 overflow-y-auto overscroll-contain p-5">
        {providers.length > 1 && !editing ? (
          <label className="flex flex-col gap-1.5 text-[13px] font-medium">
            Provider
            <Select value={form.provider} onChange={(e) => set("provider", e.target.value)}>
              {providers.map((p) => (
                <option key={p.providerId} value={p.providerId}>
                  {p.name}
                </option>
              ))}
            </Select>
          </label>
        ) : null}

        <label className="flex flex-col gap-1.5 text-[13px] font-medium">
          Name
          <Input
            value={form.name}
            onChange={(e) => set("name", e.target.value)}
            placeholder="Local vLLM"
          />
          <span className="text-xs font-light text-v-muted">
            Shown wherever an agent picks this endpoint.
          </span>
        </label>

        <label className="flex flex-col gap-1.5 text-[13px] font-medium">
          Endpoint URL
          <Input
            value={form.baseUrl}
            onChange={(e) => set("baseUrl", e.target.value)}
            placeholder="http://vllm.internal:8000/v1"
            spellCheck={false}
          />
          <span className="text-xs font-light text-v-muted">
            Include the version path, as in the endpoint&apos;s own examples.
          </span>
        </label>

        <label className="flex flex-col gap-1.5 text-[13px] font-medium">
          API key
          <Input
            type="password"
            autoComplete="off"
            spellCheck={false}
            value={form.apiKey}
            onChange={(e) => set("apiKey", e.target.value)}
            placeholder={editing ? "Leave blank to keep the stored key" : "sk-…"}
          />
          <span className="text-xs font-light text-v-muted">
            Encrypted at rest. An endpoint that checks no key still needs a placeholder.
          </span>
        </label>

        <div className="flex flex-col gap-2 rounded-v-sm border border-v-line bg-v-soft/40 p-3">
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" disabled={testing || !form.baseUrl} onClick={handleTest}>
              {testing ? <Spinner light={false} /> : <Plug className="size-3.5" strokeWidth={1.75} />}
              Test connection
            </Button>
          </div>
          {testResult ? (
            // A failure carries the endpoint's own response body, which can be a
            // long unbroken string (HTML, a JSON blob, a URL). It gets its own
            // full-width row that wraps mid-token rather than widening the dialog.
            <div
              className={`flex items-start gap-1.5 text-[12.5px] [overflow-wrap:anywhere] ${
                testResult.ok ? "text-emerald-600" : "text-v-danger"
              }`}
            >
              {testResult.ok ? (
                <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" strokeWidth={1.9} />
              ) : (
                <XCircle className="mt-0.5 size-3.5 shrink-0" strokeWidth={1.9} />
              )}
              <span className="min-w-0 max-h-32 overflow-y-auto">{testResult.note}</span>
            </div>
          ) : null}
          <span className="text-xs font-light text-v-muted">
            Lists the endpoint&apos;s models and fills the box below.
          </span>
        </div>

        <label className="flex flex-col gap-1.5 text-[13px] font-medium">
          Models
          <Input
            value={form.models}
            onChange={(e) => set("models", e.target.value)}
            placeholder="Qwen/Qwen3-8B-Instruct, meta-llama/Llama-3.1-8B-Instruct"
            spellCheck={false}
          />
          <span className="text-xs font-light text-v-muted">
            Comma-separated. These fill the agent&apos;s model picker.
          </span>
        </label>

        <label className="flex flex-col gap-1.5 text-[13px] font-medium">
          Default model
          <Input
            value={form.defaultModel}
            onChange={(e) => set("defaultModel", e.target.value)}
            placeholder="Qwen/Qwen3-8B-Instruct"
            spellCheck={false}
          />
        </label>

        <label className="flex flex-col gap-1.5 text-[13px] font-medium">
          Conversation history
          <Select
            value={form.historyMode}
            onChange={(e) => set("historyMode", e.target.value as HistoryMode)}
          >
            {(Object.keys(HISTORY_MODE_LABELS) as HistoryMode[]).map((mode) => (
              <option key={mode} value={mode}>
                {HISTORY_MODE_LABELS[mode]}
              </option>
            ))}
          </Select>
          <span className="text-xs font-light text-v-muted">
            What every agent on this endpoint sends each turn, unless the agent
            overrides it.
          </span>
        </label>

        {/* Two states, so a switch rather than the history picker's select —
         * the wire value stays the `send` / `omit` pair an agent also uses. */}
        <div className="flex flex-col gap-1.5 text-[13px] font-medium">
          <span className="flex items-center gap-3">
            <Switch
              checked={form.systemPromptMode === "send"}
              label="Send the agent's system prompt"
              onChange={(checked) => set("systemPromptMode", checked ? "send" : "omit")}
            />
            Send the agent&apos;s system prompt
          </span>
          <span className="text-xs font-light text-v-muted">
            Turn this off when the endpoint composes its own instructions and
            ignores whatever we send.
          </span>
        </div>

        <div className="flex flex-col gap-1.5 text-[13px] font-medium">
          <span className="flex items-center gap-3">
            <Switch
              checked={form.sendCallerPhone}
              label="Send the caller's phone number"
              onChange={(checked) => set("sendCallerPhone", checked)}
            />
            Send the caller&apos;s phone number
          </span>
          <span className="text-xs font-light text-v-muted">
            Adds metadata.caller_phone (digits with country code) to every
            request. Calls with no known number, such as web calls, will not
            start.
          </span>
        </div>

        <label className="flex items-center gap-2 text-[13px] font-medium">
          <input
            type="checkbox"
            checked={form.supportsTools}
            onChange={(e) => set("supportsTools", e.target.checked)}
            className="size-4 cursor-pointer accent-v-accent"
          />
          Supports tool calling
          <span className="text-xs font-light text-v-muted">
            Required for knowledge base in &quot;tool&quot; mode.
          </span>
        </label>

        <label className="flex items-center gap-2 text-[13px] font-medium">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(e) => set("enabled", e.target.checked)}
            className="size-4 cursor-pointer accent-v-accent"
          />
          Enabled
        </label>

        {error ? (
          <p className="text-[12.5px] text-v-danger [overflow-wrap:anywhere]">{error}</p>
        ) : null}
      </div>

      <div className="flex shrink-0 flex-col-reverse gap-2 border-t border-v-line bg-white px-5 py-4 sm:flex-row sm:items-center">
        <Button size="sm" disabled={saving} onClick={handleSave} className="sm:ml-auto">
          {saving ? (
            <>
              <Spinner /> Saving…
            </>
          ) : (
            <>
              <Save className="size-3.5" strokeWidth={1.75} />
              {editing ? "Update" : "Add endpoint"}
            </>
          )}
        </Button>
      </div>
    </Dialog>
  );
}

export function ProviderConnections({
  providers,
  onNotify,
  onChanged,
}: {
  providers: ConnectionProviderOption[];
  onNotify: (title: string, note: string) => void;
  /** Lets the parent refresh its "configured providers" list after a change. */
  onChanged?: () => Promise<void> | void;
}) {
  const [connections, setConnections] = useState<ProviderConnection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<ProviderConnection | null>(null);

  const providerIds = useMemo(() => providers.map((p) => p.providerId), [providers]);
  const providerKey = providerIds.join(",");

  const load = useCallback(async () => {
    setError("");
    try {
      const all = await listProviderConnections();
      setConnections(all.filter((c) => providerIds.includes(c.provider)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load endpoints.");
    } finally {
      setLoading(false);
    }
    // providerKey is the stable derived form of providerIds.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerKey]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleDelete(connection: ProviderConnection) {
    try {
      await deleteProviderConnection(connection.id);
      onNotify("Removed", `${connection.name} deleted.`);
      await load();
      await onChanged?.();
    } catch (err) {
      // A 409 here means an agent still points at it — surface that verbatim.
      onNotify("Couldn't remove", err instanceof Error ? err.message : "Something went wrong.");
    }
  }

  if (providers.length === 0) return null;

  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="font-mono text-[10px] uppercase tracking-[.16em] text-v-muted">
            Custom LLM endpoints
          </h2>
          {connections.length > 0 ? <Badge tone="accent">{connections.length}</Badge> : null}
        </div>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            setEditing(null);
            setDialogOpen(true);
          }}
        >
          <Plus className="size-3.5" strokeWidth={1.75} />
          Add endpoint
        </Button>
      </div>

      {error ? <p className="text-[12.5px] text-v-danger">{error}</p> : null}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-v-muted">
          <Spinner light={false} /> Loading endpoints…
        </div>
      ) : connections.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-v-md border border-dashed border-v-line bg-white px-6 py-10 text-center">
          <div className="rounded-full bg-v-soft p-3">
            <Plug className="size-5 text-v-muted" strokeWidth={1.75} />
          </div>
          <p className="text-sm text-v-muted">
            No OpenAI-compatible endpoints yet — add vLLM, Ollama, or any hosted gateway.
          </p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-v-md border border-v-line bg-white">
          <div className="divide-y divide-v-line">
            {connections.map((connection) => (
              <div
                key={connection.id}
                className="flex items-center justify-between gap-3 px-4 py-3.5 transition-colors hover:bg-v-soft/50"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-purple-500/10">
                    <Plug className="size-4 text-purple-600" strokeWidth={1.75} />
                  </span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-v-fg">{connection.name}</span>
                      {!connection.enabled ? (
                        <span className="rounded-full border border-v-line bg-v-soft px-1.5 py-0.5 text-[10px] font-medium text-v-muted-2">
                          Disabled
                        </span>
                      ) : null}
                      {connection.supports_tools ? (
                        <span className="rounded-full border border-purple-500/20 bg-purple-500/10 px-1.5 py-0.5 text-[10px] font-medium text-purple-700">
                          Tools
                        </span>
                      ) : null}
                      {connection.history_mode === "current_turn" ? (
                        // Only the non-default modes are worth a badge; the
                        // defaults are what every endpoint did before these
                        // settings existed.
                        <span className="rounded-full border border-v-line bg-v-soft px-1.5 py-0.5 text-[10px] font-medium text-v-muted-2">
                          Current turn only
                        </span>
                      ) : null}
                      {connection.system_prompt_mode === "omit" ? (
                        <span className="rounded-full border border-v-line bg-v-soft px-1.5 py-0.5 text-[10px] font-medium text-v-muted-2">
                          No system prompt
                        </span>
                      ) : null}
                      {connection.send_caller_phone ? (
                        <span className="rounded-full border border-v-line bg-v-soft px-1.5 py-0.5 text-[10px] font-medium text-v-muted-2">
                          Caller phone
                        </span>
                      ) : null}
                    </div>
                    <p className="truncate text-xs font-light text-v-muted">
                      {connection.base_url}
                      {connection.models.length > 0
                        ? ` · ${connection.models.length} model(s)`
                        : ""}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setEditing(connection);
                      setDialogOpen(true);
                    }}
                  >
                    <Pencil className="size-3.5" strokeWidth={1.75} />
                    Edit
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => handleDelete(connection)}>
                    <Trash2 className="size-3.5" strokeWidth={1.75} />
                    Remove
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {dialogOpen ? (
        <ConnectionDialog
          providers={providers}
          editing={editing}
          onClose={() => setDialogOpen(false)}
          onSaved={async () => {
            await load();
            await onChanged?.();
          }}
          onNotify={onNotify}
        />
      ) : null}
    </section>
  );
}
