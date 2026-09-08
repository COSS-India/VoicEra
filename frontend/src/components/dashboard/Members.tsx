"use client";

import { useMemo, useState } from "react";
import { motion, type Variants } from "framer-motion";
import { Check, Copy, MoreVertical, Search, Trash2, User, UserPlus, Users } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { Dialog, DialogHeader } from "@/components/ui/Dialog";
import { InviteLinkCopy } from "@/components/auth/OrgInviteShare";
import { useAuth } from "@/components/AuthProvider";
import { useMembers } from "@/hooks/useMembers";
import type { MemberListItem } from "@/lib/api-types";

type RoleFilter = "all" | "super_admin" | "admin" | "member";

/** Highest-rank first — the same order the role hierarchy is described in everywhere
 * else (super admin > admin > member), so the cards read most-senior-first. */
const ROLE_RANK: Record<string, number> = { super_admin: 0, admin: 1, member: 2 };

const cardVariants: Variants = {
  hidden: { opacity: 0, y: 14 },
  visible: (i: number) => ({
    opacity: 1,
    y: 0,
    transition: { delay: i * 0.05, duration: 0.3, ease: [0.4, 0, 0.2, 1] as const },
  }),
};

function roleLabel(role: string): string {
  return role
    .split("_")
    .map((w) => w[0]!.toUpperCase() + w.slice(1))
    .join(" ");
}

function roleTone(role: string) {
  if (role === "super_admin") return "accent" as const;
  if (role === "admin") return "live" as const;
  return "neutral" as const;
}

/** Generates a shareable /signup?org= link and lets the admin copy it. */
function AddMemberModal({
  orgId,
  orgName,
  onClose,
}: {
  orgId: string;
  orgName?: string;
  onClose: () => void;
}) {
  return (
    <Dialog open onClose={onClose} widthClassName="max-w-lg">
      <DialogHeader
        title="Invite a member"
        subtitle="Share this link — anyone who opens it can join."
        onClose={onClose}
      />
      <div className="flex flex-col gap-3 p-5">
        <InviteLinkCopy orgId={orgId} orgName={orgName} />
        <p className="text-xs font-light leading-relaxed text-v-muted">
          They&apos;ll set their own password on that page and join {orgName ?? "your organisation"} as a member.
        </p>
        <div className="flex justify-end pt-2">
          <Button size="sm" onClick={onClose}>
            Done
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

interface MemberCardProps {
  member: MemberListItem;
  index: number;
  isSelf: boolean;
  canManage: boolean;
  busy: boolean;
  onPromote: () => Promise<void> | void;
  onRemove: () => Promise<void> | void;
}

function MemberCard({ member, index, isSelf, canManage, busy, onPromote, onRemove }: MemberCardProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirmPromoteOpen, setConfirmPromoteOpen] = useState(false);
  const [confirmRemoveOpen, setConfirmRemoveOpen] = useState(false);

  const canPromote = canManage && !isSelf && member.role === "member";
  const canRemove = canManage && !isSelf && member.role !== "super_admin";
  const showMenu = canPromote || canRemove;

  async function handleConfirmPromote() {
    setConfirmPromoteOpen(false);
    await onPromote();
  }

  async function handleConfirmRemove() {
    setConfirmRemoveOpen(false);
    await onRemove();
  }

  return (
    <motion.div
      custom={index}
      variants={cardVariants}
      initial="hidden"
      animate="visible"
      whileHover={{ y: -3, boxShadow: "0 8px 24px rgba(11,11,12,0.08)" }}
      transition={{ type: "spring", stiffness: 400, damping: 25 }}
      className="relative flex flex-col items-center gap-3 rounded-v-md border border-v-line bg-white p-4.5 text-center"
    >
      {showMenu ? (
        <div className="absolute right-2.5 top-2.5">
          <button
            type="button"
            onClick={() => setMenuOpen((v) => !v)}
            disabled={busy}
            aria-label="Member actions"
            className="flex size-8 items-center justify-center rounded-v-sm border border-v-line bg-white text-v-muted transition-colors hover:text-v-fg disabled:cursor-wait"
          >
            {busy ? <Spinner light={false} /> : <MoreVertical className="size-4" strokeWidth={1.75} />}
          </button>

          {menuOpen ? (
            <div className="absolute right-0 top-[calc(100%+6px)] z-20 w-48 overflow-hidden rounded-v-sm border border-v-line bg-white p-1 text-left shadow-[0_18px_50px_rgba(11,11,12,.16)]">
              {canPromote ? (
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    setConfirmPromoteOpen(true);
                  }}
                  className="w-full cursor-pointer rounded-v-sm px-2.5 py-2 text-left text-[13px] hover:bg-v-soft"
                >
                  Promote to admin
                </button>
              ) : null}
              {canPromote && canRemove ? <div className="my-1 border-t border-v-line" /> : null}
              {canRemove ? (
                <button
                  type="button"
                  onClick={() => {
                    setMenuOpen(false);
                    setConfirmRemoveOpen(true);
                  }}
                  className="flex w-full cursor-pointer items-center gap-1.5 rounded-v-sm px-2.5 py-2 text-left text-[13px] text-v-danger hover:bg-v-soft"
                >
                  <Trash2 className="size-3.5" strokeWidth={1.75} />
                  Remove member
                </button>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}

      <span className="flex size-14 items-center justify-center rounded-full border border-v-line bg-v-soft">
        <User className="size-6 text-v-muted" strokeWidth={1.5} />
      </span>

      {member.role !== "member" || isSelf ? (
        <div className="flex flex-wrap items-center justify-center gap-1.5">
          {member.role !== "member" ? <Badge tone={roleTone(member.role)}>{roleLabel(member.role)}</Badge> : null}
          {isSelf ? (
            <span className="rounded-full bg-v-soft px-2.5 py-0.5 text-[11px] text-v-muted">You</span>
          ) : null}
        </div>
      ) : null}

      <p className="w-full truncate text-[15px] font-semibold leading-none text-v-fg" title={member.email}>
        {member.email}
      </p>

      <div className="my-0.5 w-full border-t border-v-line" />

      <p className="text-xs font-light text-v-muted">
        {member.created_at ? `Joined ${new Date(member.created_at).toLocaleDateString()}` : "—"}
      </p>

      {confirmPromoteOpen ? (
        <Dialog open onClose={() => setConfirmPromoteOpen(false)} widthClassName="max-w-sm">
          <DialogHeader title="Promote to admin?" onClose={() => setConfirmPromoteOpen(false)} />
          <div className="flex flex-col gap-4 p-5 text-left">
            <p className="text-sm font-light text-v-muted">
              <span className="font-medium text-v-fg">{member.email}</span> will be able to manage
              integrations, agents, and invite new members.
            </p>
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setConfirmPromoteOpen(false)} disabled={busy}>
                Cancel
              </Button>
              <Button size="sm" onClick={handleConfirmPromote} disabled={busy}>
                {busy ? (
                  <>
                    <Spinner /> Promoting…
                  </>
                ) : (
                  "Promote"
                )}
              </Button>
            </div>
          </div>
        </Dialog>
      ) : null}

      {confirmRemoveOpen ? (
        <Dialog open onClose={() => setConfirmRemoveOpen(false)} widthClassName="max-w-sm">
          <DialogHeader title="Remove member?" onClose={() => setConfirmRemoveOpen(false)} />
          <div className="flex flex-col gap-4 p-5 text-left">
            <p className="text-sm font-light text-v-muted">
              <span className="font-medium text-v-fg">{member.email}</span> will lose access to this
              organisation immediately. This can&apos;t be undone.
            </p>
            <div className="flex justify-end gap-2">
              <Button size="sm" variant="ghost" onClick={() => setConfirmRemoveOpen(false)} disabled={busy}>
                Cancel
              </Button>
              <Button size="sm" variant="danger-outline" onClick={handleConfirmRemove} disabled={busy}>
                {busy ? (
                  <>
                    <Spinner light={false} /> Removing…
                  </>
                ) : (
                  <>
                    <Trash2 className="size-3.5" strokeWidth={1.75} /> Remove
                  </>
                )}
              </Button>
            </div>
          </div>
        </Dialog>
      ) : null}
    </motion.div>
  );
}

export function Members({ onNotify }: { onNotify: (title: string, note: string) => void }) {
  const { session } = useAuth();
  const { members, loading, loadError, busyEmail, promote, remove } = useMembers(session?.orgId, onNotify);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("all");
  const [inviteOpen, setInviteOpen] = useState(false);

  const canInvite = session?.role === "admin" || session?.role === "super_admin";
  const canManage = session?.role === "super_admin";

  const counts = useMemo(
    () => ({
      all: members.length,
      super_admin: members.filter((m) => m.role === "super_admin").length,
      admin: members.filter((m) => m.role === "admin").length,
      member: members.filter((m) => m.role === "member").length,
    }),
    [members],
  );

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const result = members.filter((m) => {
      if (roleFilter !== "all" && m.role !== roleFilter) return false;
      if (!q) return true;
      return m.email.toLowerCase().includes(q);
    });
    return [...result].sort((a, b) => (ROLE_RANK[a.role] ?? 99) - (ROLE_RANK[b.role] ?? 99));
  }, [members, query, roleFilter]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-1.5 border-b border-v-line pb-6">
        <h1 className="text-3xl font-semibold tracking-tight">Members</h1>
        <p className="max-w-[62ch] text-sm font-light leading-relaxed text-v-muted">
          Manage your organisation&apos;s team members
        </p>
      </div>

      {loadError ? (
        <div className="rounded-v-md border border-v-danger-line bg-v-danger-pale px-4 py-3 text-sm text-v-danger">
          {loadError}
        </div>
      ) : null}

      {!loading ? (
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <div className="relative min-w-0 flex-1 sm:max-w-sm">
              <Search
                className="pointer-events-none absolute left-3.5 top-1/2 size-4 -translate-y-1/2 text-v-muted"
                strokeWidth={1.75}
              />
              <input
                type="search"
                placeholder="Search by email…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                aria-label="Search members"
                className="w-full rounded-v-sm border border-v-line bg-v-soft/80 py-2.5 pl-10 pr-3.5 text-[14px] transition-colors placeholder:text-v-muted focus:border-v-accent focus:bg-white focus:outline-none"
              />
            </div>

            <div className="flex items-center gap-2 rounded-full bg-v-soft/70 px-3.5 py-1.5">
              <Users className="size-4 text-v-muted" strokeWidth={1.75} />
              <span className="text-sm font-medium text-v-muted-2">
                {filtered.length === members.length
                  ? `${members.length} ${members.length === 1 ? "member" : "members"}`
                  : `${filtered.length} of ${members.length}`}
              </span>
            </div>

            <div className="flex-1" />

            {canInvite ? (
              <Button onClick={() => setInviteOpen(true)}>
                <UserPlus className="size-4" strokeWidth={1.75} />
                Add member
              </Button>
            ) : null}
          </div>

          <div className="flex overflow-hidden self-start rounded-full border border-v-line bg-white text-xs font-medium">
            {(
              [
                ["all", `All · ${counts.all}`],
                ["super_admin", `Super Admin · ${counts.super_admin}`],
                ["admin", `Admin · ${counts.admin}`],
                ["member", `Member · ${counts.member}`],
              ] as [RoleFilter, string][]
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setRoleFilter(key)}
                className={`cursor-pointer whitespace-nowrap px-3.5 py-2 transition-colors ${
                  roleFilter === key ? "bg-v-fg text-white" : "text-v-muted-2 hover:bg-v-track"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-v-muted">
          <Spinner light={false} /> Loading members…
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-v-md border border-dashed border-v-line bg-white p-12 text-center">
          <div className="rounded-full bg-v-soft p-3">
            <Search className="size-5 text-v-muted" strokeWidth={1.75} />
          </div>
          <span className="text-sm font-semibold">
            {query || roleFilter !== "all" ? "Nothing matches" : "No members yet"}
          </span>
          <span className="text-xs font-light text-v-muted">Try another search or filter.</span>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((m, index) => (
            <MemberCard
              key={m.email}
              member={m}
              index={index}
              isSelf={m.email === session?.email}
              canManage={canManage}
              busy={busyEmail === m.email}
              onPromote={() => promote(m)}
              onRemove={() => remove(m)}
            />
          ))}
        </div>
      )}

      {inviteOpen && session?.orgId ? (
        <AddMemberModal orgId={session.orgId} orgName={session.orgName} onClose={() => setInviteOpen(false)} />
      ) : null}
    </div>
  );
}
