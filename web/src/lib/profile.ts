import { api, type Profile } from "./api/client";

/**
 * The profile, cached on the device.
 *
 * The plan screen has to render with no network — that is the whole architecture — so
 * anything it shows has to survive a cold start in a basement. Same pattern as the plan
 * itself: serve what is on the device immediately, refresh in the background when there
 * is a network to refresh from.
 */
const KEY = "loadout.profile";

export function cachedProfile(): Profile | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Profile;
  } catch {
    return null;
  }
}

export function cacheProfile(profile: Profile): void {
  window.localStorage.setItem(KEY, JSON.stringify(profile));
}

/** Cache first, then network. Resolves twice-ish: callers re-render on the fresh one. */
export async function refreshProfile(): Promise<Profile | null> {
  try {
    const fresh = await api.profile();
    cacheProfile(fresh);
    return fresh;
  } catch {
    return cachedProfile();
  }
}
