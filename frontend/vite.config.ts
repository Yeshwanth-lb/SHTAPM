import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// SHTAPM frontend — P0 M3.5. React plugin enabled for the minimal live-telemetry
// proof. Aurora/Tailwind, path aliases, and WS proxy are P5.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
});
