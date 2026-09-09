"use client";

import { useEffect, useMemo } from "react";
import {
  PipecatClientAudio,
  PipecatClientProvider,
} from "@pipecat-ai/client-react";
import { CallStage } from "@/components/call/CallStage";
import { createBrowserPipecatClient } from "@/lib/pipecat/createBrowserClient";

interface BrowserCallSessionProps {
  orgId: string;
  agentId: string;
  agentName: string;
}

/**
 * One Pipecat client per test-call surface: provider + official bot audio
 * element + CallStage. Disconnects on unmount so the mic is always released.
 */
export function BrowserCallSession({ orgId, agentId, agentName }: BrowserCallSessionProps) {
  const client = useMemo(() => createBrowserPipecatClient(), []);

  useEffect(() => {
    return () => {
      void client.disconnect().catch(() => {});
    };
  }, [client]);

  return (
    <PipecatClientProvider client={client}>
      <PipecatClientAudio />
      <CallStage orgId={orgId} agentId={agentId} agentName={agentName} />
    </PipecatClientProvider>
  );
}
