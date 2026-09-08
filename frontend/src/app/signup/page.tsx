"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Check } from "lucide-react";
import { AuthHero } from "@/components/auth/AuthHero";
import { OrgInviteShare } from "@/components/auth/OrgInviteShare";
import { PasswordInput } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Spinner";
import { joinOrganisation } from "@/lib/api/members";
import { checkEmail } from "@/lib/api/users";
import { signup } from "@/lib/api-client";
import { ApiError } from "@/lib/api/http";
import { saveSession } from "@/lib/auth-storage";
import { markWalkthroughPending } from "@/components/walkthrough";

const authInputClass =
  "w-full box-border rounded-v-sm border border-v-line-strong bg-white px-3.5 py-3.5 text-[15.5px] text-v-fg focus:border-v-accent";

type SignupStep = 1 | 2 | 3;
type OrgMode = "create" | "join";

const PASSWORD_RULES = [
  { id: "length", label: "8+ characters", test: (pw: string) => pw.length >= 8 },
  { id: "upper", label: "One uppercase", test: (pw: string) => /[A-Z]/.test(pw) },
  { id: "number", label: "One number", test: (pw: string) => /\d/.test(pw) },
  { id: "symbol", label: "One symbol", test: (pw: string) => /[^A-Za-z0-9]/.test(pw) },
] as const;

function passwordRulesMet(pw: string): boolean {
  return PASSWORD_RULES.every((rule) => rule.test(pw));
}

function validatePassword(pw: string, confirm: string): string[] {
  const issues: string[] = [];
  if (confirm && pw !== confirm) issues.push("Passwords don't match");
  return issues;
}

function isExistingAccountPasswordError(message: string): boolean {
  const m = message.toLowerCase();
  return (
    (m.includes("password") && m.includes("existing")) ||
    m.includes("invalid password")
  );
}

function finishAuth(
  data: {
    status: string;
    message?: string;
    access_token?: string;
    org_id?: string;
    role?: string;
    is_first_login?: boolean;
  },
  email: string,
  orgName?: string,
) {
  if (data.status === "fail" || !data.access_token || !data.org_id || !data.role) {
    return data.message ?? "Something went wrong. Try again.";
  }
  saveSession({
    accessToken: data.access_token,
    email,
    orgId: data.org_id,
    orgName,
    role: data.role,
  });
  if (data.is_first_login) markWalkthroughPending();
  return null;
}

export default function SignUpPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen w-full items-center justify-center">
          <Spinner />
        </main>
      }
    >
      <SignUpPageInner />
    </Suspense>
  );
}

function SignUpPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const inviteOrgId = searchParams.get("org") ?? "";
  const inviteOrgName = searchParams.get("org_name") ?? "";

  const [step, setStep] = useState<SignupStep>(1);
  const [orgMode, setOrgMode] = useState<OrgMode>(inviteOrgId ? "join" : "create");

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [passwordIssues, setPasswordIssues] = useState<string[]>([]);

  const [organisationName, setOrganisationName] = useState("");
  const [joinOrgId, setJoinOrgId] = useState(inviteOrgId);

  const [submitting, setSubmitting] = useState(false);
  const [checkingEmail, setCheckingEmail] = useState(false);
  const [existingAccount, setExistingAccount] = useState(false);
  const [createdOrg, setCreatedOrg] = useState<{ orgId: string; orgName: string } | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setPasswordIssues(validatePassword(password, confirmPassword));
  }, [password, confirmPassword]);

  useEffect(() => {
    if (inviteOrgId) {
      setJoinOrgId(inviteOrgId);
      setOrgMode("join");
    }
  }, [inviteOrgId]);

  const validEmail = /\S+@\S+\.\S+/.test(email);
  const passwordValid = passwordRulesMet(password);
  const step1Valid =
    fullName.trim().length > 0 &&
    validEmail &&
    passwordValid &&
    password === confirmPassword &&
    confirmPassword.length > 0 &&
    passwordIssues.length === 0;

  const passwordRuleStatus = useMemo(
    () => PASSWORD_RULES.map((rule) => ({ ...rule, met: rule.test(password) })),
    [password],
  );

  const canCreate = organisationName.trim().length > 0;
  const canJoin = joinOrgId.trim().length > 0;

  async function goToStep2() {
    if (!step1Valid) return;
    setError("");
    setCheckingEmail(true);
    try {
      const result = await checkEmail(email.trim());
      setExistingAccount(result.exists);
      setStep(2);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't verify that email. Try again.");
    } finally {
      setCheckingEmail(false);
    }
  }

  function handleExistingAccountPasswordError() {
    setStep(1);
    setError("That password doesn't match your existing account. Re-enter it above, or sign in if you forgot it.");
  }

  async function handleCreateOrg() {
    if (!canCreate || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      const data = await signup(email.trim(), password, organisationName.trim());
      const err = finishAuth(data, email.trim(), organisationName.trim());
      if (err) {
        setError(err);
        setSubmitting(false);
        return;
      }
      setCreatedOrg({ orgId: data.org_id!, orgName: organisationName.trim() });
      setStep(3);
      setSubmitting(false);
    } catch (err) {
      const message = err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Couldn't reach the server. Try again.";
      if (isExistingAccountPasswordError(message)) {
        handleExistingAccountPasswordError();
      } else {
        setError(message);
      }
      setSubmitting(false);
    }
  }

  async function handleJoinOrg() {
    if (!canJoin || submitting) return;
    setSubmitting(true);
    setError("");
    const orgId = joinOrgId.trim();
    try {
      const eligibility = await checkEmail(email.trim(), orgId);
      if (eligibility.already_in_org) {
        setError("This email is already part of this organisation.");
        setSubmitting(false);
        return;
      }
      if (!eligibility.can_join) {
        setError("This email can't join this organisation.");
        setSubmitting(false);
        return;
      }

      const data = await joinOrganisation(email.trim(), password, orgId);
      const err = finishAuth(data, email.trim(), inviteOrgName || undefined);
      if (err) {
        setError(err);
        setSubmitting(false);
        return;
      }
      router.push("/dashboard");
    } catch (err) {
      const message = err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Couldn't complete your join. Try again.";
      if (isExistingAccountPasswordError(message)) {
        handleExistingAccountPasswordError();
      } else {
        setError(message);
      }
      setSubmitting(false);
    }
  }

  return (
    <main className="grid min-h-screen w-full grid-cols-1 lg:grid-cols-[1.04fr_1fr]">
      <AuthHero />

      <div className="flex flex-col justify-center px-6 py-10 sm:px-12 sm:py-12">
        <div className="mx-auto flex w-full max-w-sm flex-col gap-6">
          {step === 3 && createdOrg ? (
            <OrgInviteShare
              orgId={createdOrg.orgId}
              orgName={createdOrg.orgName}
              onContinue={() => router.push("/dashboard")}
            />
          ) : step === 1 ? (
            <>
              <div className="flex flex-col gap-2">
                <h2 className="m-0 text-3xl font-semibold tracking-tight">Create your account</h2>
                <p className="m-0 text-sm font-light leading-relaxed text-v-muted">
                  Start in seconds — no card required.
                </p>
              </div>

              <form
                className="flex flex-col gap-4"
                onSubmit={(e) => {
                  e.preventDefault();
                  goToStep2();
                }}
              >
                <div className="flex flex-col gap-2.5">
                  <label htmlFor="su-name" className="text-[13px] font-medium">
                    Full name
                  </label>
                  <input
                    id="su-name"
                    type="text"
                    autoComplete="name"
                    value={fullName}
                    onChange={(e) => setFullName(e.target.value)}
                    placeholder="Jane Doe"
                    className={authInputClass}
                  />
                </div>

                <div className="flex flex-col gap-2.5">
                  <label htmlFor="su-email" className="text-[13px] font-medium">
                    Email
                  </label>
                  <input
                    id="su-email"
                    type="email"
                    autoComplete="email"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@organisation.org"
                    className={authInputClass}
                  />
                </div>

                <div className="flex flex-col gap-2.5">
                  <label htmlFor="su-password" className="text-[13px] font-medium">
                    Password
                  </label>
                  <PasswordInput
                    id="su-password"
                    autoComplete="new-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Create a password"
                    className={authInputClass}
                  />
                  <ul className="flex flex-wrap gap-x-4 gap-y-1.5" aria-live="polite">
                    {passwordRuleStatus.map((rule) => (
                      <li
                        key={rule.id}
                        className={`flex items-center gap-1 text-[12px] font-medium transition-colors ${
                          rule.met ? "text-v-accent" : "text-v-muted"
                        }`}
                      >
                        {rule.met ? (
                          <Check className="size-3.5 shrink-0" strokeWidth={2.5} aria-hidden />
                        ) : (
                          <span
                            className="inline-block size-3.5 shrink-0 rounded-full border border-v-line-strong"
                            aria-hidden
                          />
                        )}
                        {rule.label}
                      </li>
                    ))}
                  </ul>
                </div>

                <div className="flex flex-col gap-2.5">
                  <label htmlFor="confirm-password" className="text-[13px] font-medium">
                    Confirm password
                  </label>
                  <PasswordInput
                    id="confirm-password"
                    autoComplete="new-password"
                    value={confirmPassword}
                    onChange={(e) => setConfirmPassword(e.target.value)}
                    placeholder="Type it again"
                    className={authInputClass}
                  />
                  {passwordIssues.length > 0 ? (
                    <ul className="flex flex-col gap-0.5">
                      {passwordIssues.map((issue) => (
                        <li key={issue} className="text-[12.5px] text-v-danger">
                          {issue}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </div>

                {error ? <span className="text-[12.5px] text-v-danger">{error}</span> : null}

                <button
                  type="submit"
                  disabled={!step1Valid || checkingEmail}
                  className="mt-0.5 flex w-full cursor-pointer items-center justify-center gap-2.5 rounded-v-sm bg-v-fg px-4.5 py-3.5 text-[15px] font-semibold text-white transition-colors hover:bg-v-accent disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {checkingEmail ? <Spinner /> : null}
                  {checkingEmail ? "Checking…" : "Continue"}
                </button>
              </form>
            </>
          ) : (
            <>
              <div className="flex flex-col gap-2">
                <h2 className="m-0 text-3xl font-semibold tracking-tight">Your organisation</h2>
                <p className="m-0 text-sm font-light leading-relaxed text-v-muted">
                  {inviteOrgId
                    ? `You've been invited to join ${inviteOrgName || "an organisation"}.`
                    : "Agents and call logs live inside an organisation — create one or join with an invite code."}
                </p>
              </div>

              {!inviteOrgId ? (
                <div className="grid grid-cols-2 gap-2 rounded-v-sm border border-v-line bg-v-soft/40 p-1">
                  <button
                    type="button"
                    onClick={() => setOrgMode("create")}
                    className={`cursor-pointer rounded-v-sm px-3 py-2.5 text-[13px] font-medium transition-colors ${
                      orgMode === "create"
                        ? "bg-white text-v-fg shadow-sm"
                        : "text-v-muted hover:text-v-fg"
                    }`}
                  >
                    Create an organisation
                  </button>
                  <button
                    type="button"
                    onClick={() => setOrgMode("join")}
                    className={`cursor-pointer rounded-v-sm px-3 py-2.5 text-[13px] font-medium transition-colors ${
                      orgMode === "join"
                        ? "bg-white text-v-fg shadow-sm"
                        : "text-v-muted hover:text-v-fg"
                    }`}
                  >
                    Join an organisation
                  </button>
                </div>
              ) : null}

              {orgMode === "create" && !inviteOrgId ? (
                <form
                  className="flex flex-col gap-4"
                  onSubmit={(e) => {
                    e.preventDefault();
                    handleCreateOrg();
                  }}
                >
                  {existingAccount ? (
                    <p className="m-0 rounded-v-sm border border-v-line bg-v-soft/50 px-3.5 py-2.5 text-[12.5px] leading-relaxed text-v-muted">
                      You already have a Voicera account with this email. The password you entered
                      in step 1 must match that account to create another organisation.{" "}
                      <Link href="/" className="font-medium text-v-accent hover:text-v-accent-deep">
                        Sign in
                      </Link>{" "}
                      if you forgot it.
                    </p>
                  ) : null}
                  <div className="flex flex-col gap-2.5">
                    <label htmlFor="org-name" className="text-[13px] font-medium">
                      Organisation name
                    </label>
                    <input
                      id="org-name"
                      type="text"
                      autoComplete="organization"
                      value={organisationName}
                      onChange={(e) => setOrganisationName(e.target.value)}
                      placeholder="COSS India"
                      className={authInputClass}
                    />
                  </div>

                  {error ? <span className="text-[12.5px] text-v-danger">{error}</span> : null}

                  <button
                    type="submit"
                    disabled={!canCreate || submitting}
                    className="mt-0.5 flex w-full cursor-pointer items-center justify-center gap-2.5 rounded-v-sm bg-v-fg px-4.5 py-3.5 text-[15px] font-semibold text-white transition-colors hover:bg-v-accent disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {submitting ? <Spinner /> : null}
                    {submitting ? "Creating organisation" : "Create organisation"}
                  </button>
                </form>
              ) : (
                <form
                  className="flex flex-col gap-4"
                  onSubmit={(e) => {
                    e.preventDefault();
                    handleJoinOrg();
                  }}
                >
                  <div className="flex flex-col gap-2.5">
                    <label htmlFor="invite-code" className="text-[13px] font-medium">
                      Invite code
                    </label>
                    <p className="m-0 text-[12.5px] font-light leading-relaxed text-v-muted">
                      Enter the code from your invite link — it&apos;s the organisation ID.
                    </p>
                    <input
                      id="invite-code"
                      type="text"
                      value={joinOrgId}
                      onChange={(e) => setJoinOrgId(e.target.value)}
                      readOnly={Boolean(inviteOrgId)}
                      placeholder="e.g. a1b2c3"
                      className={`${authInputClass} ${inviteOrgId ? "bg-v-soft/50" : ""}`}
                    />
                    {inviteOrgName ? (
                      <p className="m-0 text-[12.5px] font-medium text-v-fg">{inviteOrgName}</p>
                    ) : null}
                  </div>

                  {error ? <span className="text-[12.5px] text-v-danger">{error}</span> : null}

                  <button
                    type="submit"
                    disabled={!canJoin || submitting}
                    className="mt-0.5 flex w-full cursor-pointer items-center justify-center gap-2.5 rounded-v-sm bg-v-fg px-4.5 py-3.5 text-[15px] font-semibold text-white transition-colors hover:bg-v-accent disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {submitting ? <Spinner /> : null}
                    {submitting
                      ? "Joining…"
                      : inviteOrgName
                        ? `Join ${inviteOrgName}`
                        : "Join organisation"}
                  </button>
                </form>
              )}

              <button
                type="button"
                onClick={() => {
                  setStep(1);
                  setError("");
                }}
                className="cursor-pointer text-center text-xs font-medium text-v-muted hover:text-v-accent"
              >
                ← Back to account details
              </button>
            </>
          )}

          {step !== 3 ? (
          <p className="text-center text-xs text-v-muted">
            Already have an account?{" "}
            <Link href="/" className="font-medium text-v-accent hover:text-v-accent-deep">
              Sign in
            </Link>
          </p>
          ) : null}
        </div>
      </div>
    </main>
  );
}
