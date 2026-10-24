"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, signOut, type ContextOut, type Profile, type ProfilePatch } from "@/lib/api/client";
import { activeContextId, setActiveContextId } from "@/lib/context";
import { AppShell, PageHeader } from "@/components/AppShell";
import { Button } from "@/components/ui/Button";
import { RowButton } from "@/components/ui/Row";
import { EmptyState } from "@/components/ui/EmptyState";
import { Skeleton } from "@/components/ui/Skeleton";
import { useToast } from "@/components/ui/Toast";
import { ProfileFields } from "@/components/intake/ProfileFields";
import { TrainingFields } from "@/components/intake/TrainingFields";
import { SettingsIcon } from "@/components/ui/icons";
import { BodyMetrics } from "@/components/BodyMetrics";
import { bmiFromProfile } from "@/lib/bmi";
import { cacheProfile } from "@/lib/profile";
import { readUnits } from "@/lib/units";

type Archetype = { slug: string; name: string; equipment: string[] };

/**
 * Everything the app knows about you, in one place.
 *
 * The contexts section exists because CLAUDE.md constraint 5 is that equipment belongs
 * to a training context and a user has several — home, work gym, hotel. The API has had
 * full CRUD for them since 2.2b; until now the app created exactly one during onboarding
 * and gave you no way to reach it again.
 */
export default function Settings() {
  const router = useRouter();
  const toast = useToast();

  const [me, setMe] = useState<{ email: string } | null>(null);
  const [draft, setDraft] = useState<ProfilePatch | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [contexts, setContexts] = useState<ContextOut[] | null>(null);
  const [active, setActive] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [archetypes, setArchetypes] = useState<Archetype[] | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);

  const loadContexts = useCallback(async () => {
    const all = await api.listContexts().catch(() => []);
    setContexts(all);
    const remembered = activeContextId();
    const chosen =
      all.find((c) => c.id === remembered) ?? all.find((c) => c.is_default) ?? all[0];
    setActive(chosen?.id ?? null);
  }, []);

  useEffect(() => {
    void api.me().then(setMe).catch(() => setMe(null));
    void api
      .profile()
      .then((p: Profile) => setDraft(p as ProfilePatch))
      .catch(() => setDraft({}));
    void loadContexts();
  }, [loadContexts]);

  const patch = (next: ProfilePatch) => {
    setDraft((prev) => ({ ...prev, ...next }));
    setDirty(true);
  };

  async function save() {
    if (!draft) return;
    setSaving(true);
    try {
      cacheProfile(await api.saveProfile(draft));
      setDirty(false);
      toast("Saved. Regenerate your plan to apply it.");
    } catch {
      toast("Could not save. Check your connection.", "error");
    } finally {
      setSaving(false);
    }
  }

  function switchTo(context: ContextOut) {
    setActive(context.id);
    setActiveContextId(context.id);
    toast(`Training at ${context.label}`);
  }

  async function addPlace(preset: Archetype) {
    try {
      const created = await api.createContext({
        label: preset.name,
        archetype_slug: preset.slug,
        equipment_added: [],
        equipment_removed: [],
        is_default: false,
        loads: {},
      });
      setAdding(false);
      await loadContexts();
      switchTo(created);
    } catch {
      toast("Could not add that place.", "error");
    }
  }

  async function remove(context: ContextOut) {
    try {
      await api.deleteContext(context.id);
      setConfirming(null);
      await loadContexts();
      toast(`Removed ${context.label}`);
    } catch {
      toast("Could not remove that place.", "error");
    }
  }

  function leave() {
    signOut();
    router.replace("/onboarding");
  }

  async function openAdd() {
    setAdding(true);
    if (archetypes === null) {
      setArchetypes(await api.archetypes().catch(() => []));
    }
  }

  const measurements = draft ? bmiFromProfile(draft) : null;

  return (
    <AppShell width="max-w-2xl">
      <PageHeader
        title="Settings"
        meta={me?.email}
        action={
          dirty ? (
            <Button variant="primary" compact loading={saving} onClick={save}>
              Save
            </Button>
          ) : undefined
        }
      />

      <Section
        title="Where you train"
        note="Plans are built from the kit at the place you pick. Switching here changes what the next plan can use."
      >
        {contexts === null && <Skeleton className="h-14" />}

        {contexts?.length === 0 && (
          <EmptyState
            icon={<SettingsIcon />}
            title="No places yet"
            body="Add the gym, garage or spare room you train in and Loadout builds around whatever is actually there."
            action={<Button variant="primary" onClick={openAdd}>Add a place</Button>}
          />
        )}

        {contexts && contexts.length > 0 && (
          <div className="space-y-2">
            {contexts.map((context) => (
              <div key={context.id}>
                <div className="flex items-center gap-2">
                  <RowButton
                    className="flex-1"
                    title={context.label}
                    detail={`${context.equipment.length} pieces of kit${context.is_default ? " · default" : ""}`}
                    selected={context.id === active}
                    onClick={() => switchTo(context)}
                  />
                  {contexts.length > 1 && (
                    <Button
                      variant="ghost"
                      compact
                      aria-label={`Remove ${context.label}`}
                      onClick={() => setConfirming(context.id)}
                    >
                      Remove
                    </Button>
                  )}
                </div>

                {/* Confirmation inline rather than in a dialog, like everywhere else in
                    this app. Deleting a place is not undoable and takes its loads with
                    it, so it does not happen on one tap. */}
                {confirming === context.id && (
                  <div className="mt-2 flex items-center gap-2 rounded-card border border-danger/30 bg-danger-quiet/40 px-4 py-3">
                    <p className="flex-1 text-[0.875rem] text-ink">
                      Remove {context.label} and the loads recorded for it?
                    </p>
                    <Button variant="ghost" compact onClick={() => setConfirming(null)}>
                      Keep
                    </Button>
                    <Button variant="danger" compact onClick={() => remove(context)}>
                      Remove
                    </Button>
                  </div>
                )}
              </div>
            ))}

            {!adding && (
              <Button full onClick={openAdd}>
                Add a place
              </Button>
            )}
          </div>
        )}

        {adding && (
          <div className="mt-2 space-y-2">
            {archetypes === null && <Skeleton className="h-14" />}
            {archetypes?.map((preset) => (
              <RowButton
                key={preset.slug}
                title={preset.name}
                detail={`${preset.equipment.length} pieces of kit`}
                onClick={() => addPlace(preset)}
              />
            ))}
            <Button full variant="ghost" onClick={() => setAdding(false)}>
              Cancel
            </Button>
          </div>
        )}
      </Section>

      <Section
        title="How you train"
        note="These four go straight into the generator. Regenerate your plan after changing them."
      >
        {draft === null ? (
          <Skeleton className="h-40" />
        ) : (
          <TrainingFields value={draft} onChange={patch} />
        )}
      </Section>

      <Section
        title="About you"
        note="Stored on your account. Nothing here changes your plan yet — bodyweight is next, so press-ups and pull-ups can carry a load."
      >
        {draft === null ? (
          <Skeleton className="h-40" />
        ) : (
          <>
            <ProfileFields value={draft} onChange={patch} />
            {measurements && (
              <BodyMetrics
                bmi={measurements}
                bodyweightKg={draft.bodyweight_kg == null ? null : Number(draft.bodyweight_kg)}
                units={readUnits()}
                className="mt-5"
              />
            )}
          </>
        )}
      </Section>

      <Section title="Account">
        <Button onClick={leave}>Sign out</Button>
      </Section>
    </AppShell>
  );
}

function Section({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-10">
      <h2 className="text-[0.8125rem] tracking-[0.08em] uppercase text-ink-faint">
        {title}
      </h2>
      {note && (
        <p className="mt-1.5 mb-4 text-[0.875rem] leading-relaxed text-ink-faint">
          {note}
        </p>
      )}
      <div className={note ? "" : "mt-4"}>{children}</div>
    </section>
  );
}
