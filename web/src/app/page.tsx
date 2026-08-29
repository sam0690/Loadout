"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { token } from "@/lib/api/client";

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(token() ? "/plan" : "/onboarding");
  }, [router]);
  return <main className="p-6 text-white/40">…</main>;
}
