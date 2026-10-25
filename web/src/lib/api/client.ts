import type { components, paths } from "./schema";

/**
 * Thin typed fetch over the generated schema.
 *
 * Everything here derives from `schema.ts`, which is generated from FastAPI's OpenAPI
 * output — CLAUDE.md forbids hand-writing these types, so if a route changes shape this
 * file stops compiling rather than failing at runtime.
 */

export type Batch = components["schemas"]["Batch"];
export type Accepted = components["schemas"]["Accepted"];
export type ContextOut = components["schemas"]["ContextOut"];
export type ContextIn = components["schemas"]["ContextIn"];
export type PlanOut = components["schemas"]["PlanOut"];
export type JobStatus = components["schemas"]["JobStatus"];
export type PlanRequest = components["schemas"]["PlanRequest"];
export type Goal = components["schemas"]["Goal"];
export type Experience = components["schemas"]["Experience"];
/** What the server returns: bodyweight arrives as a decimal string, not a float. */
export type Profile = components["schemas"]["Profile-Output"];
/** What we send: a written key means "set this", an absent key means "leave it". */
export type ProfilePatch = components["schemas"]["Profile-Input"];
export type Me = components["schemas"]["Me"];

export type PlanPayload = {
  /**
   * Muscles the active context's equipment cannot train at all (D30).
   *
   * Optional because plans already cached in localStorage predate the field. Absent is
   * not the same as empty: absent means "this plan was generated before the engine could
   * tell us", empty means "your kit covers everything".
   */
  unreachable?: string[];
  sessions: {
    day: string;
    items: {
      exercise_id: string;
      slug: string;
      movement_pattern: string;
      primary_muscle: string;
      sets: number;
      target_reps: number;
      target_rir: number;
      load: string | null;
      /** Absent on plans cached before it shipped; treat as "only if it has a load". */
      loadable?: boolean;
      substitutes: { exercise_id: string; slug: string; equipment: string[] }[];
    }[];
  }[];
};

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Session token. Held in localStorage because there is no revocation anyway (D23) —
 * a cookie would imply a server-side session this design does not have. */
export function token(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem("loadout.token");
}

/**
 * The signed-in account's id, read from the session token's `sub`. Not verified -- the
 * server does that on every request; this only decides whose events this device shows
 * and sends.
 */
export function currentUserId(): string | null {
  const t = token();
  if (t === null) return null;
  try {
    const body = t.split(".")[1]!.replace(/-/g, "+").replace(/_/g, "/");
    const sub: unknown = JSON.parse(atob(body)).sub;
    return typeof sub === "string" ? sub : null;
  } catch {
    return null;
  }
}

export function setToken(value: string): void {
  window.localStorage.setItem("loadout.token", value);
}

/**
 * Forget this device's account: the token and everything cached under it.
 *
 * One list, so a sign-out and an expired session cannot drift apart -- a key left
 * behind is the next account seeing the last one's plan.
 */
export function signOut(): void {
  for (const key of ["loadout.token", "loadout.plan", "loadout.profile", "loadout.me", "loadout.context"]) {
    window.localStorage.removeItem(key);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const auth = token();
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "content-type": "application/json",
      ...(auth ? { authorization: `Bearer ${auth}` } : {}),
      ...init?.headers,
    },
  });
  // A token the server refuses is a dead session (re-seeded database, rotated secret).
  // Falling back to the cached plan, as for a network failure, showed the last account's
  // week with no way to tell -- so start over at sign-in instead. A 401 can only come
  // from a server that answered, so this never fires offline.
  if (res.status === 401 && auth !== null) {
    signOut();
    window.location.replace("/onboarding");
  }
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  // Password sign-in (D31). The magic-link endpoints still exist server-side.
  signup: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),

  me: () => request<Me>("/auth/me"),

  profile: () => request<Profile>("/auth/profile"),

  // Merges: only the keys present are written, so intake can save a screen at a time.
  saveProfile: (body: ProfilePatch) =>
    request<Profile>("/auth/profile", { method: "PUT", body: JSON.stringify(body) }),

  listContexts: () => request<ContextOut[]>("/contexts"),

  archetypes: () =>
    request<{ slug: string; name: string; equipment: string[] }[]>(
      "/contexts/archetypes",
    ),

  createContext: (body: ContextIn) =>
    request<ContextOut>("/contexts", { method: "POST", body: JSON.stringify(body) }),

  deleteContext: (id: string) =>
    request<void>(`/contexts/${id}`, { method: "DELETE" }),

  requestPlan: (body: PlanRequest) =>
    request<{ job_id: string }>("/plans", { method: "POST", body: JSON.stringify(body) }),

  job: (id: string) => request<JobStatus>(`/jobs/${id}`),

  currentPlan: () => request<PlanOut>("/plans/current"),

  listEvents: () => request<components["schemas"]["StoredEvent"][]>("/events"),

  postEvents: (events: unknown[]) =>
    request<Accepted>("/events", {
      method: "POST",
      body: JSON.stringify({ events }),
    }),
};

export type ApiPaths = paths;
