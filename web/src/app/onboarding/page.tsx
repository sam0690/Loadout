"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api, setToken } from "@/lib/api/client";

/**
 * Two questions and nothing else.
 *
 * PRD §12 names onboarding friction as a real cost, so this asks for an email and a
 * rough equipment set, then generates. Everything else -- the rack, the bar weight, the
 * archetype amendments -- has a working default and can be corrected later (D21).
 */
const PRESETS: { label: string; equipment: string[] }[] = [
  { label: "Nothing at all", equipment: [] },
  { label: "Dumbbells", equipment: ["dumbbells"] },
  { label: "Dumbbells + bench + pull-up bar", equipment: ["dumbbells", "flat_bench", "pull_up_bar"] },
  { label: "Barbell home gym", equipment: ["barbell", "plates", "adjustable_bench", "pull_up_bar", "dumbbells"] },
  { label: "Commercial gym", equipment: ["barbell", "plates", "dumbbells", "cable_stack", "adjustable_bench", "pull_up_bar", "leg_press", "lat_pulldown"] },
];

export default function Onboarding() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [linkToken, setLinkToken] = useState("");
  const [authed, setAuthed] = useState(false);
  const [chosen, setChosen] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // A verify link opened on this device carries the token in the query string.
    const fromLink = new URLSearchParams(window.location.search).get("token");
    if (fromLink) setLinkToken(fromLink);
  }, []);

  async function send() {
    setError(null);
    try {
      await api.requestLink(email);
      setSent(true);
    } catch (e) {
      setError(e instanceof ApiError ? "Could not send a link." : String(e));
    }
  }

  async function verify() {
    setError(null);
    try {
      const { access_token } = await api.verify(linkToken);
      setToken(access_token);
      setAuthed(true);
    } catch {
      setError("That link has expired or has already been used.");
    }
  }

  async function finish() {
    if (chosen === null) return;
    setError(null);
    try {
      const preset = PRESETS[chosen]!;
      await api.createContext({
        label: preset.label,
        equipment_added: preset.equipment,
        equipment_removed: [],
        is_default: true,
        loads: {},
      });
      router.push("/plan");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  return (
    <main className="space-y-6 p-6">
      <h1 className="text-3xl font-semibold">Loadout</h1>

      {!authed && (
        <section className="space-y-3">
          <p className="text-white/60">
            Training that fits the equipment you actually have.
          </p>
          <input
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-2xl bg-white/10 px-4 py-4 text-lg outline-none"
          />
          <button
            onClick={send}
            className="w-full rounded-2xl bg-emerald-500 font-semibold text-black"
          >
            {sent ? "Sent — check your mail" : "Send me a link"}
          </button>

          {sent && (
            <div className="space-y-3 pt-2">
              <input
                placeholder="Paste the link's token"
                value={linkToken}
                onChange={(e) => setLinkToken(e.target.value)}
                className="w-full rounded-2xl bg-white/10 px-4 py-4 outline-none"
              />
              <button
                onClick={verify}
                className="w-full rounded-2xl border border-white/15"
              >
                Sign in
              </button>
            </div>
          )}
        </section>
      )}

      {authed && (
        <section className="space-y-3">
          <h2 className="text-lg">What do you have?</h2>
          {PRESETS.map((preset, i) => (
            <button
              key={preset.label}
              onClick={() => setChosen(i)}
              className={`w-full rounded-2xl px-4 text-left ${
                chosen === i ? "bg-emerald-500 text-black" : "bg-white/10"
              }`}
            >
              {preset.label}
            </button>
          ))}
          <button
            onClick={finish}
            disabled={chosen === null}
            className="w-full rounded-2xl bg-emerald-500 font-semibold text-black disabled:opacity-30"
          >
            Build my plan
          </button>
        </section>
      )}

      {error && <p className="text-sm text-red-400">{error}</p>}
    </main>
  );
}
