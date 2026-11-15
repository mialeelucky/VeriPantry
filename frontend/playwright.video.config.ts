import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

// Records the demo video (video/record-demo.spec.ts). Not part of the test suite.
export default defineConfig({
  ...base,
  testDir: "video",
  timeout: 180_000,
  outputDir: "video-output/run",
  use: {
    ...base.use,
    viewport: { width: 1600, height: 900 },
    video: { mode: "on", size: { width: 1600, height: 900 } },
    trace: "off",
  },
});
