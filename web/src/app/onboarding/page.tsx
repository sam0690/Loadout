"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api, setToken, token, type ProfilePatch } from "@/lib/api/client";
import { generatePlan, type Preferences } from "@/lib/plan";
import { Button } from "@/components/ui/Button";
import { Field } from "@/components/ui/Field";
import { RowButton } from "@/components/ui/Row";
import { SegmentedControl } from "@/components/ui/SegmentedControl";
import { ProfileFields } from "@/components/intake/ProfileFields";
import { TrainingFields } from "@/components/intake/TrainingFields";

/**
 * Sign in or sign up with a password (D31), then four questions, then a plan.
 *
 * PRD §12 names onboarding friction as a real cost and it is not resolved lightly: every
 * question here either feeds the engine (goal, experience, sessions, length) or is
 * collected deliberately ahead of its consumer (D29). Nothing is asked twice and
 * everything has a default, so a user who taps straight through still gets a plan.
 */
type Step = "account" | "profile" | "training" | "context" | "generating";
type Mode = "signin" | "signup";

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
  const [step, setStep] = useState<Step>("account");
  const [mode, setMode] = useState<Mode>("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [draft, setDraft] = useState<ProfilePatch>({});
  const [archetypes, setArchetypes] = useState<Archetype[] | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Where a signed-in account belongs. Having a place means intake was finished once,
   * so signing in again -- a new phone, a cleared browser -- goes to Today instead of
   * walking the questions a second time and building a duplicate place.
   */
  const resume = useCallback(async () => {
    const places = await api.listContexts().catch(() => []);
    if (places.length > 0) router.replace("/today");
    else setStep("profile");
  }, [router]);

  useEffect(() => {
    if (token()) void resume();
  }, [resume]);

  useEffect(() => {
    if (step !== "context" || archetypes !== null) return;
    void api
      .archetypes()
      .then(setArchetypes)
      .catch(() => setArchetypes([]));
  }, [step, archetypes]);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const { access_token } =
        mode === "signin" ? await api.login(email, password) : await api.signup(email, password);
      setToken(access_token);
      await resume();
    } catch (e) {
      setError(
        !(e instanceof ApiError)
          ? "Could not reach Loadout. Check your connection."
          : e.status === 401
            ? "Wrong email or password."
            : e.status === 409
              ? "There is already an account with that email. Sign in instead."
              : "Check the email, and use at least 8 characters for the password.",
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
      router.push("/today");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not build a plan.");
      setStep("context");
    }
  }

  const patch = (next: ProfilePatch) => setDraft((prev) => ({ ...prev, ...next }));

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col px-5 pb-10">
      <header className="pt-12 pb-8">
        <p className="font-display text-[1.5rem] font-extrabold tracking-[0.02em] text-ink uppercase">
          Loadout
        </p>
        {INTAKE.includes(step) && <Progress step={step} />}
      </header>

      {step === "account" && (
        <Section
          title="Training that fits the equipment you actually have."
          body="No app-store gym required. Tell us what you can reach and we build the week around it."
        >
          <SegmentedControl
            label="Account"
            value={mode}
            options={[
              { value: "signin", label: "Sign in" },
              { value: "signup", label: "Create account" },
            ]}
            onChange={(next) => {
              setMode(next);
              setError(null);
            }}
          />
          {/* A form, so Enter submits and password managers recognise the pair. */}
          <form
            className="space-y-4"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            {mode === "signup" && (
              // Rides on the first intake save rather than on signup: it is profile, not
              // credentials, and the account must exist before the profile can be written.
              <Field
                label="Name (optional)"
                autoComplete="name"
                maxLength={40}
                value={draft.display_name ?? ""}
                onChange={(e) =>
                  setDraft((d) => ({ ...d, display_name: e.target.value.trim() ? e.target.value : null }))
                }
              />
            )}
            <Field
              label="Email"
              type="email"
              inputMode="email"
              autoComplete="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            <Field
              label="Password"
              type="password"
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              hint={mode === "signup" ? "At least 8 characters." : undefined}
            />
            <Button
              type="submit"
              variant="primary"
              full
              loading={busy}
              disabled={!email.includes("@") || password.length < 8}
            >
              {mode === "signin" ? "Sign in" : "Create account"}
            </Button>
          </form>
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
        <h1 className="text-[2rem] leading-[1.05] text-ink">
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
    <div className="mt-5">
      <p className="label mb-2">
        Step {index + 1} of {INTAKE.length}
      </p>
      <ol className="flex gap-1.5" aria-hidden="true">
        {INTAKE.map((name, i) => (
          <li
            key={name}
            className={`h-1.5 flex-1 rounded-full transition-colors duration-300 ${
              i <= index ? "bg-accent" : "bg-raised"
            }`}
          />
        ))}
      </ol>
    </div>
  );
}
