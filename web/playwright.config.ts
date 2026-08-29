import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  // One worker: the test drives a shared API and a shared database.
  workers: 1,
  use: { baseURL: "http://localhost:3000", trace: "off" },
});
