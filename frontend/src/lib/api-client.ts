import { apiFetch, langQuery } from "@/lib/api/http";
import type {
  AgentApiResponse,
  AgentCreatePayload,
  ProviderAuthResponse,
  ProviderConnection,
  ProviderConnectionPayload,
  ProviderConnectionProbe,
} from "@/lib/api-types";
import type {
  AuthCatalog,
  LanguagesMap,
  ProviderList,
  ProviderSettingsCatalog,
} from "@/lib/catalog-types";

export { ApiError } from "@/lib/api/http";
// User-domain functions now live in lib/api/users.ts; re-exported here so existing
// call sites (AuthProvider, login/signup pages) don't need to change their import path.
export { login, signup, getMe } from "@/lib/api/users";

// --- Agents ---

export async function listAgents(): Promise<AgentApiResponse[]> {
  return apiFetch<AgentApiResponse[]>("/agents");
}

export async function getAgent(agentId: string): Promise<AgentApiResponse> {
  return apiFetch<AgentApiResponse>(`/agents/${encodeURIComponent(agentId)}`);
}

export async function deleteAgent(agentId: string): Promise<void> {
  return apiFetch<void>(`/agents/${encodeURIComponent(agentId)}`, { method: "DELETE" });
}

export async function archiveAgent(agentId: string, archived: boolean): Promise<AgentApiResponse> {
  return apiFetch<AgentApiResponse>(`/agents/${encodeURIComponent(agentId)}`, {
    method: "PATCH",
    body: JSON.stringify({ archived }),
  });
}

export async function createAgent(payload: AgentCreatePayload): Promise<AgentApiResponse> {
  return apiFetch<AgentApiResponse>("/agents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateAgent(
  agentId: string,
  payload: Partial<AgentCreatePayload>,
): Promise<AgentApiResponse> {
  return apiFetch<AgentApiResponse>(`/agents/${encodeURIComponent(agentId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

// --- Provider auth (Integrations) ---

export async function getAuthCatalog(): Promise<AuthCatalog> {
  return apiFetch<AuthCatalog>("/auth/catalog");
}

export async function listConfiguredProviders(): Promise<string[]> {
  return apiFetch<string[]>("/auth/configured");
}

export async function upsertProviderAuth(
  provider: string,
  auth: Record<string, unknown>,
): Promise<ProviderAuthResponse> {
  return apiFetch<ProviderAuthResponse>("/auth", {
    method: "POST",
    body: JSON.stringify({ provider, auth }),
  });
}

export async function getProviderAuth(provider: string): Promise<ProviderAuthResponse> {
  return apiFetch<ProviderAuthResponse>(`/auth/${encodeURIComponent(provider)}`);
}

export async function deleteProviderAuth(provider: string): Promise<void> {
  return apiFetch<void>(`/auth/${encodeURIComponent(provider)}`, { method: "DELETE" });
}

// --- Provider connections (named endpoints for OpenAI-compatible providers) ---

export async function listProviderConnections(
  params: { provider?: string; enabledOnly?: boolean } = {},
): Promise<ProviderConnection[]> {
  const query = new URLSearchParams();
  if (params.provider) query.set("provider", params.provider);
  if (params.enabledOnly) query.set("enabled_only", "true");
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  return apiFetch<ProviderConnection[]>(`/provider-connections${suffix}`);
}

export async function createProviderConnection(
  payload: ProviderConnectionPayload,
): Promise<ProviderConnection> {
  return apiFetch<ProviderConnection>("/provider-connections", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateProviderConnection(
  connectionId: string,
  payload: Partial<ProviderConnectionPayload>,
): Promise<ProviderConnection> {
  return apiFetch<ProviderConnection>(`/provider-connections/${encodeURIComponent(connectionId)}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function deleteProviderConnection(connectionId: string): Promise<void> {
  return apiFetch<void>(`/provider-connections/${encodeURIComponent(connectionId)}`, {
    method: "DELETE",
  });
}

/** Reach an endpoint that has not been saved yet (the dialog's Test button). */
export async function probeProviderEndpoint(
  baseUrl: string,
  apiKey?: string,
  model?: string,
): Promise<ProviderConnectionProbe> {
  return apiFetch<ProviderConnectionProbe>("/provider-connections/probe", {
    method: "POST",
    body: JSON.stringify({
      base_url: baseUrl,
      api_key: apiKey || null,
      model: model || null,
    }),
  });
}

/** Re-probe a stored connection; the API caches the returned model list. */
export async function testProviderConnection(
  connectionId: string,
): Promise<ProviderConnectionProbe> {
  return apiFetch<ProviderConnectionProbe>(
    `/provider-connections/${encodeURIComponent(connectionId)}/test`,
    { method: "POST" },
  );
}

// --- Configuration catalogs ---

export async function getLanguages(): Promise<{ languages: LanguagesMap }> {
  return apiFetch<{ languages: LanguagesMap }>("/languages");
}

export async function listSttProviders(langs: string[] = []): Promise<ProviderList> {
  return apiFetch<ProviderList>(`/configuration/stt${langQuery(langs)}`);
}

export async function listTtsProviders(langs: string[] = []): Promise<ProviderList> {
  return apiFetch<ProviderList>(`/configuration/tts${langQuery(langs)}`);
}

export async function listLlmProviders(): Promise<ProviderList> {
  return apiFetch<ProviderList>("/configuration/llm");
}

export async function listTelephonyProviders(): Promise<ProviderList> {
  return apiFetch<ProviderList>("/configuration/telephony");
}

export async function getSttSettings(
  provider: string,
  langs: string[] = [],
): Promise<ProviderSettingsCatalog> {
  return apiFetch<ProviderSettingsCatalog>(
    `/configuration/stt/setting/${encodeURIComponent(provider)}${langQuery(langs)}`,
  );
}

export async function getTtsSettings(
  provider: string,
  langs: string[] = [],
): Promise<ProviderSettingsCatalog> {
  return apiFetch<ProviderSettingsCatalog>(
    `/configuration/tts/setting/${encodeURIComponent(provider)}${langQuery(langs)}`,
  );
}

export async function getLlmSettings(provider: string): Promise<ProviderSettingsCatalog> {
  return apiFetch<ProviderSettingsCatalog>(
    `/configuration/llm/setting/${encodeURIComponent(provider)}`,
  );
}
