import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["src/utils/weaponHelpers.test.ts"],
    environment: "jsdom",
    coverage: {
      provider: "v8",
      reporter: ["text", "text-summary"],
      include: ["src/utils/weaponHelpers.ts"],
      thresholds: {
        lines: 35,
        functions: 40,
        statements: 35,
        branches: 60,
      },
    },
  },
});
