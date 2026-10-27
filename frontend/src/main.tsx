import React from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { applyVisualPrefs, FpsGuard } from "./lib/visualPrefs";

// TRD §02.9: deployment motion/transparency defaults, then shed effects if the
// page cannot hold 50 fps. Visual only -- the data path is never touched.
applyVisualPrefs();
new FpsGuard().start();

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}
