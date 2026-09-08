"use client";

import { Suspense, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Spinner } from "@/components/ui/Spinner";

function AddMemberRedirect() {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const params = new URLSearchParams();
    const org = searchParams.get("org");
    const orgName = searchParams.get("org_name");
    if (org) params.set("org", org);
    if (orgName) params.set("org_name", orgName);
    const qs = params.toString();
    router.replace(qs ? `/signup?${qs}` : "/signup");
  }, [router, searchParams]);

  return (
    <main className="flex min-h-screen w-full items-center justify-center">
      <Spinner />
    </main>
  );
}

/** Legacy invite links redirect to the two-step signup flow with org prefilled. */
export default function AddMemberPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen w-full items-center justify-center">
          <Spinner />
        </main>
      }
    >
      <AddMemberRedirect />
    </Suspense>
  );
}
