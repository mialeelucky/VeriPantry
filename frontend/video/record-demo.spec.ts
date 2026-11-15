// A scripted run of the real app, recorded as video with narration (under two minutes).
// Captions are overlays added by this script only; the app itself is unchanged.
//   powershell -File video/make-voice.ps1        (voice clips + durations)
//   npx playwright test -c playwright.video.config.ts
//   node video/mix.mjs ../demo/VeriPantry-demo.mp4

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { expect, test, type Page } from "@playwright/test";

const pause = (page: Page, ms: number) => page.waitForTimeout(ms);

// Each narration line's caption is shown when its voice clip starts; the cue
// times are written out so mix.mjs can place the clips on the video.
const here = dirname(fileURLToPath(import.meta.url));
const lines: { id: string; caption: string }[] = JSON.parse(readFileSync(join(here, "narration.json"), "utf8"));
const outDir = join(here, "..", "video-output");
const durations: Record<string, number> = JSON.parse(
  readFileSync(join(outDir, "voice", "durations.json"), "utf8").replace(/^﻿/, ""),
);
const cues: { id: string; at: number }[] = [];
let t0 = 0;

/** Shows the line's caption and starts its voice; the returned function waits until the voice ends. */
async function say(page: Page, id: string, showCaption = true) {
  const line = lines.find((l) => l.id === id);
  const ms = durations[id];
  if (!line || typeof ms !== "number") throw new Error(`No narration for ${id}`);
  if (showCaption) await caption(page, line.caption);
  cues.push({ id, at: Date.now() - t0 });
  const end = Date.now() + ms + 350;
  return () => pause(page, Math.max(0, end - Date.now()));
}

async function caption(page: Page, text: string) {
  await page.evaluate((t) => {
    let el = document.getElementById("vp-caption");
    if (!el) {
      el = document.createElement("div");
      el.id = "vp-caption";
      Object.assign(el.style, {
        position: "fixed", transform: "translateX(-50%)", zIndex: "9999", width: "max-content",
        background: "rgba(17,17,17,0.9)", color: "#fff", padding: "12px 24px", borderRadius: "14px",
        font: "500 21px/1.35 'Inter Variable', system-ui, sans-serif", textAlign: "center",
        transition: "opacity 200ms", pointerEvents: "none",
      });
      document.body.appendChild(el);
    }
    // On the stage: under the phone column, above the status strip. Elsewhere: centred at the bottom.
    const stage = location.pathname.startsWith("/stage");
    Object.assign(el.style, stage
      ? { left: "604px", bottom: "96px", maxWidth: "1080px" }
      : { left: "50%", bottom: "40px", maxWidth: "1200px" });
    el.textContent = t;
    el.style.opacity = t ? "1" : "0";
  }, text);
}

async function card(page: Page, title: string, sub: string, ms: number) {
  await page.evaluate(
    ([t, s]) => {
      const el = document.createElement("div");
      el.id = "vp-card";
      Object.assign(el.style, {
        position: "fixed", inset: "0", zIndex: "10000", background: "#F7F7F5", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: "14px", font: "400 22px/1.4 'Inter Variable', system-ui, sans-serif", color: "#1A1A1A",
      });
      el.innerHTML = `<div style="width:64px;height:64px;border-radius:16px;background:#EAF3DE;display:flex;align-items:center;justify-content:center">
        <svg viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="#3B6D11" stroke-width="2" stroke-linecap="round"><path d="M6 15c0-5 3.5-8.5 10-9.5-.5 6.5-4 10-9 10"/><path d="M6 18c1.6-3.3 4-5.7 7.2-7.6"/></svg></div>
        <div style="font-size:44px;font-weight:500">${t}</div><div style="color:#5F5F5A;max-width:900px;text-align:center">${s}</div>`;
      document.body.appendChild(el);
    },
    [title, sub],
  );
  await pause(page, ms);
  await page.evaluate(() => document.getElementById("vp-card")?.remove());
}

async function ask(page: Page, text: string) {
  await page.getByRole("textbox", { name: "What you need" }).click();
  await page.keyboard.type(text, { delay: 22 });
}

test("VeriPantry demo", async ({ page }) => {
  t0 = Date.now();
  await page.goto("/stage");
  await expect(page.getByText("What does your kitchen need?")).toBeVisible();
  let done = await say(page, "intro", false);
  await card(page, "VeriPantry", "Purchasing agents a wholesaler can trust, and that buyers stay in control of.", durations.intro + 400);

  // ---- 1. The agent decides on its own, within its authority
  done = await say(page, "ask");
  await ask(page, "We need 1,000 litres of the Arla lactose-free semi-skimmed milk by Monday.");
  await done();
  await page.getByRole("button", { name: "Next" }).click();
  done = await say(page, "confirm");
  await done();
  await page.getByRole("button", { name: "Start" }).click();
  done = await say(page, "working");
  await expect(page.getByText("Step 4 of 5")).toBeVisible({ timeout: 20_000 });
  await done();
  done = await say(page, "plans");
  await done();
  done = await say(page, "auto");
  await done();
  await page.getByRole("button", { name: "See confirmation" }).click();
  await expect(page.getByText("Signature verified")).toBeVisible();
  done = await say(page, "verified");
  await done();

  // ---- 2. Beyond its authority: the request finds the approver
  await page.getByRole("button", { name: "New request" }).click();
  done = await say(page, "event");
  await ask(page, "Big event this week: 3,000 litres of the Arla lactose-free semi-skimmed milk by Monday.");
  await done();
  await page.getByRole("button", { name: "Next" }).click();
  await pause(page, 700);
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.getByText("Step 4 of 5")).toBeVisible({ timeout: 20_000 });
  done = await say(page, "limit");
  const banner = page.getByText("Approval needed · €3,030.00");
  await expect(banner).toBeVisible({ timeout: 10_000 });
  await done();
  done = await say(page, "pushed");
  await done();
  await banner.click();
  await expect(page.getByText("Why you're asked")).toBeVisible();
  done = await say(page, "why");
  await done();
  await page.getByRole("button", { name: "Make a decision" }).click();
  await pause(page, 700);
  await page.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(page.getByText("Approved and ordered")).toBeVisible();
  await expect(page.getByText("Ordered after approval")).toBeVisible({ timeout: 10_000 });
  done = await say(page, "approved");
  await done();
  const txId = (await page.locator("text=/req_\\d+/").first().innerText()).match(/req_\d+/)![0];

  // ---- 3. Every step is auditable
  await page.goto("/sign-in");
  await page.getByRole("button", { name: /Valio Auditor/ }).click();
  await page.waitForURL(/\/audit/);
  await page.goto(`/audit/${txId}`);
  await expect(page.getByText("How this order was decided")).toBeVisible();
  done = await say(page, "story");
  await done();
  await page.getByRole("tab", { name: "Timeline" }).click();
  await page.getByRole("button", { name: "Buyer view" }).click();
  done = await say(page, "timeline");
  await pause(page, 2800);
  await page.getByRole("button", { name: "Valio view" }).click();
  await page.mouse.wheel(0, 400);
  await done();
  await page.getByRole("tab", { name: "Integrity" }).click();
  await expect(page.getByText(/All \d+ steps verified/)).toBeVisible();
  done = await say(page, "chain");
  await done();
  await page.getByRole("button", { name: /Tamper with step/ }).click();
  await expect(page.getByText("Verification failed at step 4")).toBeVisible();
  done = await say(page, "tamper");
  await done();
  await pause(page, 600);
  await caption(page, "");
  await say(page, "outro", false);
  await card(page, "VeriPantry", "Open, signed, auditable: agents decide within their authority, people decide the rest.", durations.outro + 1200);

  writeFileSync(join(outDir, "cues.json"), JSON.stringify(cues, null, 2));
  const seconds = (Date.now() - t0) / 1000;
  console.log(`Recorded ${seconds.toFixed(1)} s`);
  expect(seconds).toBeLessThan(120);
});
