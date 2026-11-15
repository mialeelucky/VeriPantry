import { defineConfig } from "@playwright/test";

// End-to-end tests for the demo scenarios (frontend.md §11). They run against the
// gateway in demo mode on recorded supplier data, the stub agent and the dev server.
const py = "..\\backend\\.venv\\Scripts\\python.exe";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:5173",
    channel: "msedge", // the installed Microsoft Edge: no browser download needed
    viewport: { width: 1280, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: [
    { command: `${py} -m uvicorn app.demo:app --app-dir ../backend --port 8000`, url: "http://127.0.0.1:8000/health", reuseExistingServer: true, timeout: 120_000 },
    { command: `${py} -m uvicorn stub_agent.app:app --app-dir ../agent --port 8100`, url: "http://127.0.0.1:8100/agent/scenarios", reuseExistingServer: true, timeout: 60_000 },
    { command: "npx vite --port 5173", url: "http://localhost:5173", reuseExistingServer: true, timeout: 60_000 },
  ],
});
