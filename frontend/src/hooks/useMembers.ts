"use client";

import { useCallback, useEffect, useState } from "react";
import { assignAdmin, listMembers, removeMember } from "@/lib/api/members";
import type { MemberListItem } from "@/lib/api-types";

export function useMembers(orgId: string | undefined, onNotify: (title: string, note: string) => void) {
  const [members, setMembers] = useState<MemberListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [busyEmail, setBusyEmail] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!orgId) return;
    setLoadError("");
    try {
      const res = await listMembers(orgId);
      setMembers(res.members);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : "Couldn't load members.");
    } finally {
      setLoading(false);
    }
  }, [orgId]);

  useEffect(() => {
    load();
  }, [load]);

  async function promote(m: MemberListItem) {
    setBusyEmail(m.email);
    try {
      await assignAdmin(m.email);
      onNotify("Promoted", `${m.email} is now an admin.`);
      await load();
    } catch (err) {
      onNotify("Couldn't promote", err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusyEmail(null);
    }
  }

  async function remove(m: MemberListItem) {
    setBusyEmail(m.email);
    try {
      await removeMember(m.email);
      onNotify("Removed", `${m.email} was removed.`);
      await load();
    } catch (err) {
      onNotify("Couldn't remove", err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusyEmail(null);
    }
  }

  return { members, loading, loadError, busyEmail, promote, remove, reload: load };
}
