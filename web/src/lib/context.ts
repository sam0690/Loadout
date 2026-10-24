import { api, type ContextOut } from "./api/client";

/**
 * Which place the user is training in right now.
 *
 * PRD §12 left this open — prompt every session, or infer it? — and leaned toward
 * "last-used with a one-tap switch", which is what this is (D28). Asking at every
 * session start is friction on the one screen that has to be fast; geofencing needs
 * permissions this app would rather not request.
 */
const KEY = "loadout.context";

export function activeContextId(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(KEY);
}

export function setActiveContextId(id: string): void {
  window.localStorage.setItem(KEY, id);
}

/**
 * The context to generate against: last used if it still exists, otherwise the
 * account's default, otherwise the first one. Never guesses silently — the caller
 * shows which one it landed on.
 */
export async function resolveContext(): Promise<ContextOut | null> {
  const contexts = await api.listContexts();
  if (contexts.length === 0) return null;
  const remembered = activeContextId();
  return (
    contexts.find((c) => c.id === remembered) ??
    contexts.find((c) => c.is_default) ??
    contexts[0]!
  );
}
