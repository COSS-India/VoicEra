"use client";

import { useCallback, useEffect, useState } from "react";
import { listAgents, listConfiguredProviders, listTelephonyProviders } from "@/lib/api-client";
import { attachPhoneNumber, detachPhoneNumber, listPhoneNumbers } from "@/lib/api/phone-numbers";
import type { AgentApiResponse, PhoneNumberItem } from "@/lib/api-types";
import type { ProviderList } from "@/lib/catalog-types";

export function usePhoneNumbers(onNotify: (title: string, note: string) => void) {
  const [numbers, setNumbers] = useState<PhoneNumberItem[]>([]);
  const [agents, setAgents] = useState<AgentApiResponse[]>([]);
  const [providers, setProviders] = useState<ProviderList>({});
  const [configuredProviders, setConfiguredProviders] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [busyNumber, setBusyNumber] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoadError("");
    try {
      const [numberList, agentList, providerList, configuredList] = await Promise.all([
        listPhoneNumbers(),
        listAgents(),
        listTelephonyProviders(),
        listConfiguredProviders(),
      ]);
      setNumbers(numberList);
      setAgents(agentList);
      setProviders(providerList);
      setConfiguredProviders(new Set(configuredList));
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Couldn't load phone numbers.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function importNumber(phoneNumber: string, provider: string): Promise<boolean> {
    setBusyNumber(phoneNumber);
    try {
      await attachPhoneNumber(phoneNumber, provider);
      onNotify("Number added", `${phoneNumber} was added to your inventory.`);
      await load();
      return true;
    } catch (err) {
      onNotify("Couldn't add number", err instanceof Error ? err.message : "Something went wrong.");
      return false;
    } finally {
      setBusyNumber(null);
    }
  }

  async function attachToAgent(number: PhoneNumberItem, agentId: string): Promise<boolean> {
    setBusyNumber(number.phone_number);
    try {
      await attachPhoneNumber(number.phone_number, number.provider, agentId);
      onNotify("Attached", `${number.phone_number} is now attached to that agent.`);
      await load();
      return true;
    } catch (err) {
      onNotify("Couldn't attach", err instanceof Error ? err.message : "Something went wrong.");
      return false;
    } finally {
      setBusyNumber(null);
    }
  }

  async function detach(number: PhoneNumberItem) {
    setBusyNumber(number.phone_number);
    try {
      await detachPhoneNumber(number.phone_number);
      onNotify("Detached", `${number.phone_number} was detached.`);
      await load();
    } catch (err) {
      onNotify("Couldn't detach", err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusyNumber(null);
    }
  }

  return {
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
    reload: load,
  };
}
