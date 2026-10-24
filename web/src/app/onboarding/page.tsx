"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api, setToken, token, type ProfilePatch } from "@/lib/api/client";
import { generatePlan, type Preferences } from "@/lib/plan";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { RowButton } from "@/components/ui/Row";
import { ProfileFields } from "@/components/intake/ProfileFields";
import { TrainingFields } from "@/components/intake/TrainingFields";

/**
 * Sign in, then four questions, then a plan.
 *
 * PRD §12 names onboarding friction as a real cost and it is not resolved lightly: every
 * question here either feeds the engine (goal, experience, sessions, length) or is
 * collected deliberately ahead of its consumer (D29). Nothing is asked twice and
 * everything has a default, so a user who taps straight through still gets a plan.
 */
type Step = "email" | "sent" | "profile" | "training" | "context" | "generating";

const INTAKE: Step[] = ["profile", "training", "context"];

type Archetype = { slug: string; name: string; equipment: string[] };

const DEFAULTS: Preferences = {
  goal: "hypertrophy",
  experience: "intermediate",
  daysPerWeek: 3,
  sessionMinutes: 60,
};

export default function Onboarding() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [linkToken, setLinkToken] = useState("");
  const [showPaste, setShowPaste] = useState(false);
  const [draft, setDraft] = useState<ProfilePatch>({});
  const [archetypes, setArchetypes] = useState<Archetype[] | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const consumed = useRef(false);

  const signIn = useCallback(async (value: string) => {
    setBusy(true);
    setError(null);
    try {
      const { access_token } = await api.verify(value);
      setToken(access_token);
      setStep("profile");
    } catch {
      setError("That link has expired or has already been used. Ask for another.");
      setStep("sent");
      setShowPaste(true);
    } finally {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    // A verify link opened on this device carries the token in the query string. It
    // always did -- it just never got used, which is why this screen used to ask people
    // to copy a token out of an email and paste it back in.
    const fromLink = new URLSearchParams(window.location.search).get("token");
    if (fromLink && !consumed.current) {
      consumed.current = true;
      setStep("sent");
      void signIn(fromLink);
      return;
    }
    if (token()) setStep("profile");
  }, [signIn]);

  useEffect(() => {
    if (step !== "context" || archetypes !== null) return;
    void api
      .archetypes()
      .then(setArchetypes)
      .catch(() => setArchetypes([]));
  }, [step, archetypes]);

  async function send() {
    setBusy(true);
    setError(null);
    try {
      await api.requestLink(email);
      setStep("sent");
    } catch (e) {
      setError(
        e instanceof ApiError
          ? "That address was not accepted. Check it and try again."
          : "Could not reach Loadout. Check your connection.",
      );
    } finally {
      setBusy(false);
    }
  }

  /** Saved per step, so leaving halfway keeps the answers already given. */
  async function saveAnd(next: Step) {
    setBusy(true);
    setError(null);
    try {
      await api.saveProfile(draft);
      setStep(next);
    } catch {
      setError("Could not save that. Check your connection and try again.");
    } finally {
      setBusy(false);
    }
  }

  async function build() {
    if (chosen === null || archetypes === null) return;
    setStep("generating");
    setError(null);
    try {
      const preset = archetypes.find((a) => a.slug === chosen)!;
      const context = await api.createContext({
        label: preset.name,
        archetype_slug: preset.slug,
        equipment_added: [],
        equipment_removed: [],
        is_default: true,
        loads: {},
      });
      await generatePlan(context.id, {
        goal: draft.goal ?? DEFAULTS.goal,
        experience: draft.experience ?? DEFAULTS.experience,
        daysPerWeek: draft.days_per_week ?? DEFAULTS.daysPerWeek,
        sessionMinutes: draft.session_minutes ?? DEFAULTS.sessionMinutes,
      });
      router.push("/plan");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not build a plan.");
      setStep("context");
    }
  }

  const patch = (next: ProfilePatch) => setDraft((prev) => ({ ...prev, ...next }));

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col px-5 pb-10">
      <header className="pt-12 pb-8">
        <p className="text-[0.9375rem] font-semibold tracking-[-0.01em] text-ink">
          Loadout
        </p>
        {INTAKE.includes(step) && <Progress step={step} />}
      </header>

      {step === "email" && (
        <Section
          title="Training that fits the equipment you actually have."
          body="No app-store gym required. Tell us what you can reach and we build the week around it."
        >
          <Field
            label="Email"
            type="email"
            inputMode="email"
            autoComplete="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            hint="We send a sign-in link. There is no password to forget."
          />
          <Button
            variant="primary"
            full
            loading={busy}
            disabled={!email.includes("@")}
            onClick={send}
          >
            Send me a link
          </Button>
        </Section>
      )}

      {step === "sent" && (
        <Section
          title={busy ? "Signing you in…" : "Check your mail"}
          body={
            busy
              ? "One moment."
              : `We sent a link to ${email || "your address"}. Open it on this device and you are in.`
          }
        >
          {!busy && !showPaste && (
            <Button variant="ghost" full onClick={() => setShowPaste(true)}>
              Paste the token instead
            </Button>
          )}
          {!busy && showPaste && (
            <>
              <Field
                label="Sign-in token"
                placeholder="Paste it here"
                value={linkToken}
                onChange={(e) => setLinkToken(e.target.value)}
              />
              <Button
                variant="primary"
                full
                disabled={linkToken.length === 0}
                onClick={() => signIn(linkToken)}
              >
                Sign in
              </Button>
            </>
          )}
        </Section>
      )}

      {step === "profile" && (
        <Section
          title="About you"
          body="Stored on your account, and used as we teach the engine to read it. Skip anything you would rather not answer."
        >
          <ProfileFields value={draft} onChange={patch} />
          <div className="flex gap-2">
            <Button full onClick={() => setStep("training")}>
              Skip
            </Button>
            <Button variant="primary" full loading={busy} onClick={() => saveAnd("training")}>
              Continue
            </Button>
          </div>
        </Section>
      )}

      {step === "training" && (
        <Section
          title="How you train"
          body="These four go straight into the generator. You can change any of them later."
        >
          <TrainingFields value={draft} onChange={patch} />
          <div className="flex gap-2">
            <Button full onClick={() => setStep("profile")}>
              Back
            </Button>
            <Button variant="primary" full loading={busy} onClick={() => saveAnd("context")}>
              Continue
            </Button>
          </div>
        </Section>
      )}

      {step === "context" && (
        <Section
          title="Where do you train?"
          body="Pick the closest. You can correct the exact kit afterwards, and add other places later."
        >
          {archetypes === null ? (
            <p className="text-[0.9375rem] text-ink-faint">Loading setups…</p>
          ) : (
            <div className="space-y-2">
              {archetypes.map((preset) => (
                <RowButton
                  key={preset.slug}
                  title={preset.name}
                  detail={`${preset.equipment.length} pieces of kit`}
                  selected={chosen === preset.slug}
                  onClick={() => setChosen(preset.slug)}
                />
              ))}
            </div>
          )}
          <div className="flex gap-2">
            <Button full onClick={() => setStep("training")}>
              Back
            </Button>
            <Button variant="primary" full disabled={chosen === null} onClick={build}>
              Build my plan
            </Button>
          </div>
        </Section>
      )}

      {step === "generating" && (
        <Section
          title="Building your week"
          body="Picking exercises your kit can express, then balancing volume across the week."
        >
          <div className="space-y-2" aria-hidden="true">
            {[0, 1, 2].map((i) => (
              <div
                key={i}
                className="h-14 animate-pulse rounded-card bg-surface"
                style={{ animationDelay: `${i * 120}ms` }}
              />
            ))}
          </div>
        </Section>
      )}

      {error && (
        <p role="alert" className="mt-6 text-[0.875rem] text-danger">
          {error}
        </p>
      )}
    </main>
  );
}

function Section({
  title,
  body,
  children,
}: {
  title: string;
  body: string;
  children: React.ReactNode;
}) {
  return (
    <section className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-[1.5rem] leading-snug font-semibold tracking-[-0.02em] text-ink">
          {title}
        </h1>
        <p className="text-[0.9375rem] leading-relaxed text-ink-faint">{body}</p>
      </div>
      {children}
    </section>
  );
}

/** Three steps, so the end is visible from the start. */
function Progress({ step }: { step: Step }) {
  const index = INTAKE.indexOf(step);
  return (
    <ol className="mt-4 flex gap-1.5" aria-label={`Step ${index + 1} of ${INTAKE.length}`}>
      {INTAKE.map((name, i) => (
        <li
          key={name}
          className={`h-1 flex-1 rounded-full transition-colors duration-150 ${
            i <= index ? "bg-accent" : "bg-line"
          }`}
        />
      ))}
    </ol>
  );
}
