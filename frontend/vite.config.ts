import { defineConfig } from "vite";

// SHTAPM frontend — P0 minimal Vite config. The React plugin, Aurora/Tailwind
// setup, path aliases, and WS/proxy config are added in P5.
export default defineConfig({
  server: { port: 5173 },
});
