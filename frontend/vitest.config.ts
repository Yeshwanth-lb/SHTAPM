import { defineConfig } from "vitest/config";

// P0 minimal Vitest config. jsdom + React Testing Library are added in P5.
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
