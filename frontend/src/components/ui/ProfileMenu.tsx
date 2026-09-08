"use client";

import { useEffect, useRef, useState } from "react";
import { Check, ChevronRight, ChevronUp } from "lucide-react";
import { Spinner } from "@/components/ui/Spinner";
import { getUserOrganisations, switchOrganisation } from "@/lib/api/users";
import { saveSession } from "@/lib/auth-storage";
import type { OrganisationSummary } from "@/lib/api-types";

interface ProfileMenuProps {
  name: string;
  email: string;
  org: string;
  orgId: string;
  role: string;
  expanded: boolean;
  onAccount: () => void;
  onMembers: () => void;
  onSignOut?: () => void;
}

function initials(name: string) {
  return name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function ProfileMenu({
  name,
  email,
  org,
  orgId,
  role,
  expanded,
  onAccount,
  onMembers,
  onSignOut,
}: ProfileMenuProps) {
  const [open, setOpen] = useState(false);
  const [orgPickerOpen, setOrgPickerOpen] = useState(false);
  const [organisations, setOrganisations] = useState<OrganisationSummary[]>([]);
  const [switchingOrgId, setSwitchingOrgId] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const canSwitchOrgs = organisations.length >= 2;

  useEffect(() => {
    if (!open) return;
    function onDocMouseDown(e: MouseEvent) {
      if (!menuRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDocMouseDown);
    return () => document.removeEventListener("mousedown", onDocMouseDown);
  }, [open]);

  useEffect(() => {
    if (!open) {
      setOrgPickerOpen(false);
      return;
    }
    let cancelled = false;
    getUserOrganisations()
      .then((orgs) => {
        if (!cancelled) setOrganisations(orgs);
      })
      .catch(() => {
        /* org switcher stays hidden */
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  async function handleSwitchOrg(targetOrgId: string) {
    if (targetOrgId === orgId || switchingOrgId) return;
    setSwitchingOrgId(targetOrgId);
    try {
      const result = await switchOrganisation(targetOrgId);
      if (!result.access_token || !result.org_id || !result.role) {
        throw new Error(result.message || "Couldn't switch organisation.");
      }
      saveSession({
        accessToken: result.access_token,
        email,
        orgId: result.org_id,
        orgName: result.organisations.find((o) => o.org_id === result.org_id)?.name,
        role: result.role,
      });
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/dashboard");
    } catch {
      setSwitchingOrgId(null);
    }
  }

  const orgCell = (
    <>
      <span className="font-mono text-[9.5px] uppercase tracking-[.14em] text-v-muted">Organisation</span>
      <span className="flex min-w-0 items-center gap-1">
        <span className="truncate text-[13.5px] font-medium">{org}</span>
        {canSwitchOrgs ? (
          <ChevronRight
            className={`size-3.5 shrink-0 text-v-muted transition-transform ${orgPickerOpen ? "rotate-90" : ""}`}
            strokeWidth={2}
          />
        ) : null}
      </span>
    </>
  );

  return (
    <div ref={menuRef} className="relative">
      <button
        type="button"
        data-tour="sidebar-profile"
        onClick={() => setOpen((v) => !v)}
        title={name}
        className="flex w-full cursor-pointer items-center gap-2.5 rounded-v-lg border border-v-line bg-v-surface-sunk px-2.5 py-2 text-left transition-colors duration-[120ms] hover:bg-v-soft"
      >
        <span className="flex size-[30px] shrink-0 items-center justify-center rounded-v-md bg-v-accent text-[11px] font-semibold text-white">
          {initials(name)}
        </span>
        {expanded ? (
          <span className="flex min-w-0 flex-1 items-center gap-2">
            <span className="flex min-w-0 flex-col gap-0.5 text-left">
              <span className="truncate text-[12.5px] font-semibold text-v-fg">{name}</span>
              <span className="truncate font-mono text-[10.5px] text-v-dim">
                {org} · {role}
              </span>
            </span>
            <ChevronUp
              className={`ml-auto h-3.5 w-3.5 shrink-0 text-v-muted transition-transform ${open ? "rotate-180" : ""}`}
              strokeWidth={2}
            />
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="animate-v-pop absolute bottom-[calc(100%+8px)] left-0 z-[70] w-[236px] max-w-[calc(100vw-32px)] overflow-hidden rounded-v-lg border border-v-line bg-white shadow-[0_18px_50px_rgba(11,11,12,.16)]">
          <div className="flex items-center gap-3 border-b border-v-line p-4">
            <span className="flex size-10 items-center justify-center rounded-v-md bg-v-accent text-sm font-semibold text-white">
              {initials(name)}
            </span>
            <span className="flex min-w-0 flex-col gap-0.5">
              <span className="text-[14.5px] font-semibold">{name}</span>
              <span className="truncate text-xs text-v-muted">{email}</span>
            </span>
          </div>

          {orgPickerOpen && canSwitchOrgs ? (
            <div className="border-b border-v-line">
              <div className="flex items-center justify-between border-b border-v-line px-4 py-2.5">
                <span className="font-mono text-[9.5px] uppercase tracking-[.14em] text-v-muted">
                  Switch organisation
                </span>
                <button
                  type="button"
                  onClick={() => setOrgPickerOpen(false)}
                  className="cursor-pointer text-[11px] font-medium text-v-muted hover:text-v-fg"
                >
                  Back
                </button>
              </div>
              <div className="flex max-h-44 flex-col overflow-y-auto p-1.5">
                {organisations.map((o) => {
                  const active = o.org_id === orgId;
                  const busy = switchingOrgId === o.org_id;
                  return (
                    <button
                      key={o.org_id}
                      type="button"
                      disabled={active || Boolean(switchingOrgId)}
                      onClick={() => handleSwitchOrg(o.org_id)}
                      className="flex cursor-pointer items-center justify-between gap-2 rounded-v-sm px-2.5 py-2 text-left transition-colors duration-[120ms] hover:bg-v-soft disabled:cursor-default disabled:opacity-60"
                    >
                      <span className="flex min-w-0 flex-col gap-0.5">
                        <span className="truncate text-[13.5px] font-medium">{o.name}</span>
                        <span className="text-[11px] text-v-muted">{o.role}</span>
                      </span>
                      {busy ? (
                        <Spinner light={false} />
                      ) : active ? (
                        <Check className="size-3.5 shrink-0 text-v-accent" strokeWidth={2.2} />
                      ) : null}
                    </button>
                  );
                })}
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-2 border-b border-v-line">
              {canSwitchOrgs ? (
                <button
                  type="button"
                  onClick={() => setOrgPickerOpen(true)}
                  className="flex cursor-pointer flex-col gap-0.5 border-r border-v-line px-4 py-3 text-left transition-colors duration-[120ms] hover:bg-v-soft"
                >
                  {orgCell}
                </button>
              ) : (
                <span className="flex flex-col gap-0.5 border-r border-v-line px-4 py-3">{orgCell}</span>
              )}
              <span className="flex flex-col gap-0.5 px-4 py-3">
                <span className="font-mono text-[9.5px] uppercase tracking-[.14em] text-v-muted">Role</span>
                <span className="text-[13.5px] font-medium">{role}</span>
              </span>
            </div>
          )}

          <div className="flex flex-col p-1.5">
            <button
              onClick={() => {
                onAccount();
                setOpen(false);
              }}
              className="cursor-pointer rounded-v-sm px-2.5 py-2 text-left text-[13.5px] hover:bg-v-track"
            >
              Account &amp; profile
            </button>
            <button
              onClick={() => {
                onMembers();
                setOpen(false);
              }}
              className="cursor-pointer rounded-v-sm px-2.5 py-2 text-left text-[13.5px] hover:bg-v-track"
            >
              Members &amp; invites
            </button>
          </div>
          <div className="border-t border-v-line p-1.5">
            <button
              onClick={() => {
                onSignOut?.();
                setOpen(false);
              }}
              className="w-full cursor-pointer rounded-v-sm px-2.5 py-2 text-left text-[13.5px] text-v-danger hover:bg-v-danger-pale"
            >
              Sign out
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
