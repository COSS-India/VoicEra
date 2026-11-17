import { PipecatClient } from "@pipecat-ai/client-js";
import {
  ProtobufFrameSerializer,
  WebSocketTransport,
} from "@pipecat-ai/websocket-transport";
import { createWebCall } from "@/lib/api/calls";

/** Matches runtime `WEBSOCKET_SAMPLE_RATE` (default 16000). */
export const BROWSER_SAMPLE_RATE = 16000;

/** Same-origin WebSocket — Next rewrites `/agent/*` → runtime via `RUNTIME_PROXY_TARGET`. */
export function getBrowserWsUrl(orgId: string, agentId: string, callId?: string): string {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const path = `${protocol}//${window.location.host}/agent/${orgId}/${agentId}`;
  return callId ? `${path}?call_id=${encodeURIComponent(callId)}` : path;
}

/** Pipecat client for browser test calls (protobuf WebSocket, no Daily/WebRTC transport). */
export function createBrowserPipecatClient(): PipecatClient {
  return new PipecatClient({
    transport: new WebSocketTransport({
      serializer: new ProtobufFrameSerializer(),
      recorderSampleRate: BROWSER_SAMPLE_RATE,
      playerSampleRate: BROWSER_SAMPLE_RATE,
    }),
    enableMic: true,
    enableCam: false,
  });
}

/**
 * Register a CallLog, then connect the client to the agent socket.
 * Registration failures (for example 422 when the agent is not websocket)
 * are thrown so the UI can show the API reason instead of connecting anyway.
 */
export async function connectBrowserCall(
  client: PipecatClient,
  orgId: string,
  agentId: string,
): Promise<void> {
  if (!orgId || !agentId) {
    throw new Error("Missing org or agent id");
  }

  const call = await createWebCall({ agent_id: agentId });

  await client.connect({
    wsUrl: getBrowserWsUrl(orgId, agentId, call.call_id),
  });
}
