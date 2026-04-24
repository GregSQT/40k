import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: [
      "src/utils/activationClickTarget.test.ts",
      "src/utils/weaponHelpers.test.ts",
      "src/utils/gameHelpers.test.ts",
      "src/utils/replayParser.test.ts",
    ],
    environment: "node",
    coverage: {
      provider: "v8",
      reporter: ["text", "text-summary"],
      include: [
        "src/utils/activationClickTarget.ts",
        "src/utils/weaponHelpers.ts",
        "src/utils/gameHelpers.ts",
        "src/utils/replayParser.ts",
      ],
      thresholds: {
        lines: 25,
        functions: 25,
        statements: 25,
        branches: 20,
      },
    },
  },
});
