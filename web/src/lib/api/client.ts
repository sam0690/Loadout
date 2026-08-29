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

export type PlanPayload = {
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
      substitutes: string[];
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

export function setToken(value: string): void {
  window.localStorage.setItem("loadout.token", value);
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
  if (!res.ok) throw new ApiError(res.status, await res.text());
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  requestLink: (email: string) =>
    request<{ detail: string }>("/auth/request", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  verify: (linkToken: string) =>
    request<{ access_token: string }>("/auth/verify", {
      method: "POST",
      body: JSON.stringify({ token: linkToken }),
    }),

  me: () => request<{ id: string; email: string }>("/auth/me"),

  listContexts: () => request<ContextOut[]>("/contexts"),

  createContext: (body: ContextIn) =>
    request<ContextOut>("/contexts", { method: "POST", body: JSON.stringify(body) }),

  requestPlan: (body: PlanRequest) =>
    request<{ job_id: string }>("/plans", { method: "POST", body: JSON.stringify(body) }),

  job: (id: string) => request<JobStatus>(`/jobs/${id}`),

  currentPlan: () => request<PlanOut>("/plans/current"),

  postEvents: (events: unknown[]) =>
    request<Accepted>("/events", {
      method: "POST",
      body: JSON.stringify({ events }),
    }),
};

export type ApiPaths = paths;
