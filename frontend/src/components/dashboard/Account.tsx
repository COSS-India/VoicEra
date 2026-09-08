"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { useAuth } from "@/components/AuthProvider";
import { getMe, getUserOrganisations, switchOrganisation } from "@/lib/api/users";
import { saveSession } from "@/lib/auth-storage";
import type { OrganisationSummary, UserProfile } from "@/lib/api-types";

function roleLabel(role: string): string {
  return role
    .split("_")
    .map((w) => w[0]!.toUpperCase() + w.slice(1))
    .join(" ");
}

function initials(email: string): string {
  return email.slice(0, 2).toUpperCase();
}

function formatDate(iso?: string): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
}

export function Account({
  onNotify,
}: {
  onNotify: (title: string, note: string) => void;
}) {
  const { session } = useAuth();
  const [profile, setProfile] = useState<UserProfile | null>(null);
  const [orgs, setOrgs] = useState<OrganisationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [switchingOrgId, setSwitchingOrgId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getMe(), getUserOrganisations()])
      .then(([me, organisations]) => {
        if (cancelled) return;
        setProfile(me);
        setOrgs(organisations);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Couldn't load your account.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function handleSwitchOrg(orgId: string) {
    if (orgId === profile?.org_id) return;
    setSwitchingOrgId(orgId);
    try {
      const result = await switchOrganisation(orgId);
      if (!result.access_token || !result.org_id || !result.role) {
        throw new Error(result.message || "Couldn't switch organisation.");
      }
      saveSession({
        accessToken: result.access_token,
        email: session?.email ?? profile?.email ?? "",
        orgId: result.org_id,
        orgName: result.organisations.find((o) => o.org_id === result.org_id)?.name,
        role: result.role,
      });
      // Hard reload (not router.push): AuthProvider only reads the session once on
      // mount, so switching orgs needs a full reload to pick up the new token/org_id.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/dashboard");
    } catch (err) {
      onNotify("Couldn't switch", err instanceof Error ? err.message : "Something went wrong.");
      setSwitchingOrgId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex min-h-[30vh] items-center justify-center gap-2 text-sm text-v-muted">
        <Spinner /> Loading your account…
      </div>
    );
  }

  if (error || !profile) {
    return (
      <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
        {error || "Couldn't load your account."}
      </div>
    );
  }

  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <div className="flex items-center gap-4">
        <span className="flex h-16 w-16 items-center justify-center rounded-full bg-v-accent-deep text-xl font-semibold text-white">
          {initials(profile.email)}
        </span>
        <span className="flex flex-col gap-1">
          <span className="text-2xl font-semibold tracking-tight">{profile.email}</span>
          <span className="text-sm text-v-muted">
            {profile.organisation_name ?? profile.org_id} · {roleLabel(profile.role)}
          </span>
        </span>
      </div>

      <div className="flex flex-col rounded-v-md border border-v-line bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-v-line px-5 py-4">
          <span className="text-[15px] font-semibold">Profile</span>
        </div>
        <dl className="grid grid-cols-1 gap-4 p-5 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <dt className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">Email</dt>
            <dd className="text-sm font-medium">{profile.email}</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">Role</dt>
            <dd className="text-sm font-medium">{roleLabel(profile.role)}</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">Organisation</dt>
            <dd className="text-sm font-medium">{profile.organisation_name ?? profile.org_id}</dd>
          </div>
          <div className="flex flex-col gap-1">
            <dt className="font-mono text-[10px] uppercase tracking-[.1em] text-v-muted">Member since</dt>
            <dd className="text-sm font-medium">{formatDate(profile.created_at)}</dd>
          </div>
        </dl>
      </div>

      <div className="flex flex-col rounded-v-md border border-v-line bg-white">
        <div className="flex items-center justify-between gap-3 border-b border-v-line px-5 py-4">
          <span className="text-[15px] font-semibold">Organisations</span>
        </div>
        {orgs.map((o) => (
          <div
            key={o.org_id}
            className="flex flex-wrap items-center justify-between gap-3 border-b border-v-line px-5 py-3.5 last:border-0"
          >
            <span className="flex flex-col gap-0.5">
              <span className="text-[13.5px] font-medium">{o.name}</span>
              <span className="text-xs font-light text-v-muted">{roleLabel(o.role)}</span>
            </span>
            {o.org_id === profile.org_id ? (
              <span className="rounded-full border border-v-accent/30 bg-v-pale px-3 py-1 font-mono text-[10px] uppercase tracking-[.1em] text-v-accent-deep">
                Active
              </span>
            ) : (
              <Button
                size="sm"
                variant="outline"
                disabled={switchingOrgId === o.org_id}
                onClick={() => handleSwitchOrg(o.org_id)}
              >
                {switchingOrgId === o.org_id ? (
                  <>
                    <Spinner /> Switching…
                  </>
                ) : (
                  "Switch"
                )}
              </Button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
