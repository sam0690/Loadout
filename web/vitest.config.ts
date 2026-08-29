import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  test: {
    environment: "node",
    setupFiles: ["./src/lib/__tests__/setup.ts"],
    // e2e/ is Playwright's, and it drives a real browser against a running stack.
    exclude: ["**/node_modules/**", "e2e/**"],
  },
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
});
