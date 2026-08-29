import { expect, test } from "@playwright/test";

/**
 * 2.3's acceptance, against the real stack: a full session logged with the network
 * offline, flushing correctly on reconnect.
 *
 * `context.setOffline(true)` is what the DevTools network throttle does — every request
 * from the page fails at the transport, exactly as it would in a gym basement.
 */

const API = process.env.API_URL ?? "http://localhost:8001";
const EMAIL = `e2e-${Date.now()}@example.com`;

async function signIn(request: import("@playwright/test").APIRequestContext) {
  await request.post(`${API}/auth/request`, { data: { email: EMAIL } });
  // The link is delivered to the API's log (D23), which is where a real user's mail
  // client would be. Read the token the same way.
  const { stdout } = await import("node:child_process").then((cp) =>
    new Promise<{ stdout: string }>((resolve) => {
      cp.exec(
        "grep -o 'token=[A-Za-z0-9_-]*' " +
          process.env.API_LOG! +
          " | tail -1",
        (_e, stdout) => resolve({ stdout }),
      );
    }),
  );
  const token = stdout.trim().replace("token=", "");
  const verified = await request.post(`${API}/auth/verify`, { data: { token } });
  const body = (await verified.json()) as { access_token: string };
  return body.access_token;
}

test("a full session logs offline and flushes on reconnect", async ({
  page,
  context,
  request,
}) => {
  const accessToken = await signIn(request);

  // A plan on the device, which is what the logger renders from. Shipped with the plan
  // rather than fetched, because the swap has to work with no signal (§6).
  const plan = {
    sessions: [
      {
        day: "2026-08-31",
        items: [
          {
            exercise_id: "ff9a6f91-62e1-5b57-852c-a2921d81e924",
            slug: "bodyweight_squat",
            movement_pattern: "squat",
            primary_muscle: "quads",
            sets: 3,
            target_reps: 10,
            target_rir: 2,
            load: null,
            substitutes: [],
          },
        ],
      },
    ],
  };

  await page.goto("/");
  await page.evaluate(
    ([token, planJson]) => {
      window.localStorage.setItem("loadout.token", token!);
      window.localStorage.setItem("loadout.plan", planJson!);
    },
    [accessToken, JSON.stringify(plan)] as const,
  );

  // Walk the route a user actually walks: the plan first, then into an exercise. This
  // matters offline as well as narratively -- the shell cache only holds what has been
  // visited, so a page reached only by deep link has no chunks to fall back to.
  await page.goto("/plan");
  await page.waitForLoadState("networkidle");
  await page.goto("/log/ff9a6f91-62e1-5b57-852c-a2921d81e924");
  await expect(page.getByRole("heading")).toContainText("bodyweight squat");

  // --- the signal dies ----------------------------------------------------------
  await context.setOffline(true);
  await expect(page.getByRole("heading")).toContainText("bodyweight squat");

  for (let i = 1; i <= 3; i++) {
    await page.getByRole("button", { name: `Log set ${i}` }).click();
  }

  // The sets are on screen with no network at all.
  await expect(page.getByRole("button", { name: "Log set 4" })).toBeVisible();

  const queuedOffline = await page.evaluate(async () => {
    const open = indexedDB.open("loadout");
    const db = await new Promise<IDBDatabase>((resolve) => {
      open.onsuccess = () => resolve(open.result);
    });
    const store = db.transaction("events").objectStore("events");
    const all = store.getAll();
    return new Promise<unknown[]>((resolve) => {
      all.onsuccess = () => resolve(all.result as unknown[]);
    });
  });
  expect(queuedOffline).toHaveLength(3);

  // --- a reload while still offline must not lose them --------------------------
  await page.reload();
  const afterReload = await page.evaluate(async () => {
    const open = indexedDB.open("loadout");
    const db = await new Promise<IDBDatabase>((resolve) => {
      open.onsuccess = () => resolve(open.result);
    });
    const store = db.transaction("events").objectStore("events");
    const all = store.getAll();
    return new Promise<{ id: string; synced_at: string | null }[]>((resolve) => {
      all.onsuccess = () => resolve(all.result as { id: string; synced_at: string | null }[]);
    });
  });
  expect(afterReload).toHaveLength(3);
  expect(afterReload.every((e) => e.synced_at === null)).toBe(true);
  const offlineIds = afterReload.map((e) => e.id).sort();

  // --- reconnect ----------------------------------------------------------------
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
          const store = db.transaction("events").objectStore("events");
          const all = store.getAll();
          const rows = await new Promise<{ synced_at: string | null }[]>((resolve) => {
            all.onsuccess = () => resolve(all.result as { synced_at: string | null }[]);
          });
          return rows.filter((r) => r.synced_at !== null).length;
        }),
      { timeout: 20_000 },
    )
    .toBe(3);

  // --- and the server actually has them, under the right user -------------------
  const events = await request.get(`${API}/auth/me`, {
    headers: { authorization: `Bearer ${accessToken}` },
  });
  expect(events.ok()).toBe(true);

  // The ids that flushed are the ids generated on the device (constraint 3).
  const syncedIds = await page.evaluate(async () => {
    const open = indexedDB.open("loadout");
    const db = await new Promise<IDBDatabase>((resolve) => {
      open.onsuccess = () => resolve(open.result);
    });
    const store = db.transaction("events").objectStore("events");
    const all = store.getAll();
    const rows = await new Promise<{ id: string; synced_at: string | null }[]>((resolve) => {
      all.onsuccess = () => resolve(all.result as { id: string; synced_at: string | null }[]);
    });
    return rows.filter((r) => r.synced_at !== null).map((r) => r.id).sort();
  });
  expect(syncedIds).toEqual(offlineIds);
});
