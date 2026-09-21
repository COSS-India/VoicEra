"use client";

import { useState } from "react";
import { CallStageSession } from "@/components/call/CallStage";

interface BrowserCallSessionProps {
  orgId: string;
  agentId: string;
  agentName: string;
}

/**
 * Owns the remount key for a test-call session. Pipecat's conversation state
 * (usePipecatConversation) is global to the client instance and has no
 * reset API — the only way to get a clean transcript for "New call" is a
 * fresh PipecatClient, which means remounting the provider subtree, which
 * means a new React key.
 */
export function BrowserCallSession({ orgId, agentId, agentName }: BrowserCallSessionProps) {
  const [sessionId, setSessionId] = useState(0);

  return (
    <CallStageSession
      key={sessionId}
      orgId={orgId}
      agentId={agentId}
      agentName={agentName}
      autoStart={sessionId > 0}
      onRequestNewSession={() => setSessionId((id) => id + 1)}
    />
  );
}
