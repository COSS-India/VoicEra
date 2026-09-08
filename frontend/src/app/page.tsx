"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "framer-motion";
import { AuthHero } from "@/components/auth/AuthHero";
import { PasswordInput } from "@/components/ui/Field";
import { Spinner } from "@/components/ui/Spinner";
import { login } from "@/lib/api-client";
import { saveSession } from "@/lib/auth-storage";
import { markWalkthroughPending } from "@/components/walkthrough";

export default function SignInPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [signingIn, setSigningIn] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    if (!email || !password) return;
    setSigningIn(true);
    setError("");
    try {
      const data = await login(email.trim(), password);
      if (data.status === "fail" || !data.access_token) {
        setError(data.message ?? "Invalid email or password.");
        setSigningIn(false);
        return;
      }
      saveSession({
        accessToken: data.access_token,
        email,
        orgId: data.org_id,
        role: data.role,
      });
      if (data.is_first_login) markWalkthroughPending();
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't reach the server. Try again.");
      setSigningIn(false);
    }
  }

  return (
    <main className="grid min-h-screen w-full grid-cols-1 lg:grid-cols-[1.04fr_1fr]">
      <AuthHero />

      <div className="flex flex-col justify-center px-6 py-10 sm:px-12 sm:py-12">
        <motion.div
          initial={{ opacity: 0, y: 14 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.45, ease: [0.4, 0, 0.2, 1] }}
          className="mx-auto flex w-full max-w-sm flex-col gap-6"
        >
          <div className="flex flex-col gap-2">
            <h2 className="m-0 text-3xl font-semibold tracking-tight">Sign in</h2>
            <p className="m-0 text-sm font-light leading-relaxed text-v-muted">
              Welcome back — sign in to your VoicEra workspace.
            </p>
          </div>

          <form
            className="flex flex-col gap-4"
            onSubmit={(e) => {
              e.preventDefault();
              submit();
            }}
          >
            <div className="flex flex-col gap-2.5">
              <label htmlFor="email" className="text-[13px] font-medium">
                Email
              </label>
              <input
                id="email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@organisation.org"
                className="w-full box-border rounded-v-sm border border-v-line-strong bg-blue px-3.5 py-3.5 text-[15.5px] text-v-fg focus:border-v-accent"
              />
            </div>

            <div className="flex flex-col gap-2.5">
              <label htmlFor="password" className="text-[13px] font-medium">
                Password
              </label>
              <PasswordInput
                id="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full box-border rounded-v-sm border border-v-line-strong bg-white px-3.5 py-3.5 text-[15.5px] text-v-fg focus:border-v-accent"
              />
            </div>

            <AnimatePresence>
              {error ? (
                <motion.span
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.2 }}
                  className="text-[12.5px] text-v-danger"
                >
                  {error}
                </motion.span>
              ) : null}
            </AnimatePresence>

            <button
              type="submit"
              disabled={!email || !password || signingIn}
              className="mt-0.5 flex w-full cursor-pointer items-center justify-center gap-2.5 rounded-v-sm bg-v-fg px-4.5 py-3.5 text-[15px] font-semibold text-white transition-colors hover:bg-v-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              {signingIn ? <Spinner /> : null}
              {signingIn ? "Signing in" : "Sign in"}
            </button>
          </form>

          <p className="text-center text-xs text-v-muted">
            Don&rsquo;t have an account?{" "}
            <Link href="/signup" className="font-medium text-v-accent hover:text-v-accent-deep">
              Sign up
            </Link>
          </p>
        </motion.div>
      </div>
    </main>
  );
}
