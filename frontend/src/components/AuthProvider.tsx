"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { getMe } from "@/lib/api-client";
import { clearSession, getSession, saveSession, type AuthSession } from "@/lib/auth-storage";

interface AuthContextValue {
  session: AuthSession | null;
  loading: boolean;
  signOut: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  session: null,
  loading: true,
  signOut: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const router = useRouter();
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stored = getSession();
    if (!stored) {
      setLoading(false);
      router.replace("/");
      return;
    }

    getMe()
      .then((me) => {
        const orgName =
          me.organisation_name ??
          me.organisations?.find((o) => o.org_id === stored.orgId)?.name;
        const merged: AuthSession = orgName ? { ...stored, orgName } : stored;
        saveSession(merged);
        setSession(merged);
      })
      .catch(() => {
        clearSession();
        router.replace("/");
      })
      .finally(() => setLoading(false));
  }, [router]);

  function signOut() {
    clearSession();
    setSession(null);
    router.replace("/");
  }

  if (loading) {
    return (
      <div className="flex min-h-[50vh] items-center justify-center text-sm text-v-muted">
        Loading workspace…
      </div>
    );
  }

  if (!session) return null;

  return (
    <AuthContext.Provider value={{ session, loading, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
