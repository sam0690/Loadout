import { expect, test } from "@playwright/test";
import { execSync } from "node:child_process";

/**
 * The occupied-machine flow (PRD §6), which the PRD calls the one worth demoing.
 *
 * The whole claim is that it works with no network: the alternatives travel with the
 * plan, so tapping "in use" resolves locally and the swap is recorded as an event with
 * reason "unavailable_now" — a different signal from disliking an exercise.
 */

const API = process.env.API_URL ?? "http://localhost:8001";
const EMAIL = `swap-${Date.now()}@example.com`;

test("an occupied machine is swapped with no network", async ({
  page,
  context,
  request,
}) => {
  await request.post(`${API}/auth/request`, { data: { email: EMAIL } });
  const token = execSync(
    `grep -o 'token=[A-Za-z0-9_-]*' ${process.env.API_LOG} | tail -1`,
  )
    .toString()
    .trim()
    .replace("token=", "");
  const verified = await request.post(`${API}/auth/verify`, { data: { token } });
  const { access_token } = (await verified.json()) as { access_token: string };

  // A context and a real plan, so the substitutes come from the seeded graph rather
  // than from a fixture.
  const created = await request.post(`${API}/contexts`, {
    headers: { authorization: `Bearer ${access_token}` },
    data: {
      label: "gym",
      archetype_slug: "commercial_chain",
      equipment_added: [],
      equipment_removed: [],
      is_default: true,
      loads: {},
    },
  });
  const ctx = (await created.json()) as { id: string };

  const monday = "2026-08-31";
  const enqueued = await request.post(`${API}/plans`, {
    headers: { authorization: `Bearer ${access_token}` },
    data: {
      training_context_id: ctx.id,
      days: [monday],
      time_budget_minutes: 60,
      experience: "intermediate",
      goal: "hypertrophy",
    },
  });
  const { job_id } = (await enqueued.json()) as { job_id: string };
  await expect
    .poll(
      async () => {
        const job = await request.get(`${API}/jobs/${job_id}`, {
          headers: { authorization: `Bearer ${access_token}` },
        });
        return ((await job.json()) as { status: string }).status;
      },
      { timeout: 30_000 },
    )
    .toBe("finished");

  const planned = await request.get(`${API}/plans/current`, {
    headers: { authorization: `Bearer ${access_token}` },
  });
  const plan = (await planned.json()) as {
    payload: {
      sessions: {
        items: {
          exercise_id: string;
          slug: string;
          substitutes: { exercise_id: string; slug: string }[];
        }[];
      }[];
    };
  };
  const occupied = plan.payload.sessions
    .flatMap((s) => s.items)
    .find((i) => i.substitutes.length > 0);
  expect(occupied, "the plan should offer at least one fallback").toBeTruthy();

  await page.goto("/");
  await page.evaluate(
    ([t, p]) => {
      window.localStorage.setItem("loadout.token", t!);
      window.localStorage.setItem("loadout.plan", p!);
    },
    [access_token, JSON.stringify(plan.payload)] as const,
  );
  await page.goto("/plan");
  await page.waitForLoadState("networkidle");
  await page.goto(`/log/${occupied!.exercise_id}`);
  await expect(page.getByRole("heading")).toBeVisible();

  // --- someone is on the machine, and there is no signal down here ---------------
  await context.setOffline(true);

  await page.getByRole("button", { name: "In use — swap" }).click();
  const alternative = occupied!.substitutes[0]!;
  await page
    .getByRole("button", { name: alternative.slug.replaceAll("_", " "), exact: false })
    .first()
    .click();

  // Routed to the substitute, with no request having been made.
  await expect(page).toHaveURL(new RegExp(alternative.exercise_id));

  const swap = await page.evaluate(async () => {
    const open = indexedDB.open("loadout");
    const db = await new Promise<IDBDatabase>((resolve) => {
      open.onsuccess = () => resolve(open.result);
    });
    const all = db.transaction("events").objectStore("events").getAll();
    const rows = await new Promise<
      { type: string; payload: Record<string, string>; synced_at: string | null }[]
    >((resolve) => {
      all.onsuccess = () => resolve(all.result);
    });
    return rows.find((r) => r.type === "exercise_swapped");
  });

  expect(swap, "the swap is recorded even with no network").toBeTruthy();
  // The reason matters: "unavailable_now" means the gym was busy, which must not be
  // read as the user disliking the exercise.
  expect(swap!.payload.reason).toBe("unavailable_now");
  expect(swap!.payload.to_exercise_id).toBe(alternative.exercise_id);
  expect(swap!.synced_at).toBeNull();

  // --- and it reaches the server when the signal comes back ----------------------
  await context.setOffline(false);
  await page.evaluate(() => window.dispatchEvent(new Event("online")));
  await expect
    .poll(
      async () =>
        page.evaluate(async () => {
          const open = indexedDB.open("loadout");
          const db = await new Promise<IDBDatabase>((resolve) => {
            open.onsuccess = () => resolve(open.result);
          });
          const all = db.transaction("events").objectStore("events").getAll();
          const rows = await new Promise<{ type: string; synced_at: string | null }[]>(
            (resolve) => {
              all.onsuccess = () => resolve(all.result);
            },
          );
          return rows.filter((r) => r.type === "exercise_swapped" && r.synced_at !== null)
            .length;
        }),
      { timeout: 20_000 },
    )
    .toBe(1);
});
