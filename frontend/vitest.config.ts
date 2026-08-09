import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// P0 M3.5: jsdom + React Testing Library for hook/component tests.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
  },
});
