import { expect, test, type Page } from "@playwright/test";

const AGENT = "http://127.0.0.1:8100";

async function runScenario(page: Page, title: string): Promise<string> {
  await page.goto("/buy");
  await page.getByRole("button", { name: title }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("heading", { name: "Is this right?" })).toBeVisible();
  await page.getByRole("button", { name: "Start" }).click();
  await expect(page.getByText("Step 4 of 5")).toBeVisible({ timeout: 20_000 }); // after the progress replay
  const id = decodeURIComponent(page.url().split("/buy/")[1]);
  expect(id).toMatch(/^req_/);
  return id;
}

async function signIn(page: Page, name: string) {
  await page.goto("/sign-in");
  await page.getByRole("button", { name: new RegExp(name) }).click();
  await page.waitForURL(/\/(approvals|audit)/);
}

async function agentTx(page: Page, id: string) {
  return (await page.request.get(`${AGENT}/agent/transactions/${id}`)).json();
}

test("lactose-free milk is ordered by the agent, with a verified offer and audit trail", async ({ page }) => {
  const id = await runScenario(page, "Lactose-free milk for Monday");
  await expect(page.getByText("Available exactly as you asked.")).toBeVisible();
  await expect(page.getByText("Ordered by your agent")).toBeVisible();
  await page.getByRole("button", { name: "See confirmation" }).click();
  await expect(page.getByRole("heading", { name: "Ordered" })).toBeVisible();
  await expect(page.getByText("Signature verified")).toBeVisible();
  await expect(page.getByText("Verified", { exact: true })).toBeVisible();
  expect((await agentTx(page, id)).order.total).toBe("1010.00");
});

test("Arla short: Best is ordered by the agent, Third keeps the requested product", async ({ page }) => {
  await runScenario(page, "Arla, but stock is short");
  await expect(page.getByText("Three ways to get it")).toBeVisible();
  await expect(page.getByText("Ordered by your agent")).toBeVisible();
  await expect(page.getByText(/keeps the requested product for 384 L \(38 %\)/)).toBeVisible();
  await expect(page.getByText("Needs Head Chef")).toBeVisible(); // the skimmed Second
});

test("3,000 L goes to the Head Chef, who approves on a second device", async ({ page, browser }) => {
  const id = await runScenario(page, "Arla, 3,000 litres for an event");
  await expect(page.getByText("Waiting for Head Chef")).toBeVisible();
  const approvalId = (await agentTx(page, id)).approval.approvalId;

  const phone = await (await browser.newContext({ viewport: { width: 390, height: 844 } })).newPage();
  await signIn(phone, "Head Chef");
  await phone.goto(`/approvals/${approvalId}`);
  await expect(phone.getByText("Why you're asked")).toBeVisible();
  await expect(phone.getByText(/exceeds the autonomous limit of €2,000.00/)).toBeVisible();
  await phone.getByRole("button", { name: "Make a decision" }).click();
  await phone.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(phone.getByRole("heading", { name: "Approved and ordered" })).toBeVisible();

  // The chef's screen follows within seconds (it polls the agent).
  await expect(page.getByText("Ordered after approval")).toBeVisible({ timeout: 10_000 });
  expect((await agentTx(page, id)).status).toBe("ORDERED");
});

test("6,000 L needs the finance lead: the Head Chef cannot open it", async ({ page, browser }) => {
  const id = await runScenario(page, "6,000 litres for the whole chain");
  await expect(page.getByText("Waiting for Finance Lead")).toBeVisible();
  expect((await agentTx(page, id)).approval.requiredRole).toBe("admin");

  const phone = await (await browser.newContext()).newPage();
  await signIn(phone, "Head Chef");
  await expect(phone.getByText("Needs Finance Lead").first()).toBeVisible();
  await expect(phone.getByText("Not your role").first()).toBeVisible();
});

test("milk allergy: no milk is ever offered", async ({ page }) => {
  const id = await runScenario(page, "A guest with a milk allergy");
  await expect(page.getByText(/sign-off/)).toBeVisible();
  const tx = await agentTx(page, id);
  const items = tx.lines[0].plans.flatMap((p: any) => p.items);
  expect(items.length).toBeGreaterThan(0);
  for (const item of items) expect(item.allergens.AM).toBe("free_from");
});

test("audit: the chain verifies, and the tamper demo shows where it breaks", async ({ page }) => {
  const id = await runScenario(page, "Lactose-free milk for Monday");
  await signIn(page, "Valio Auditor");
  await page.goto(`/audit/${id}`);
  await expect(page.getByText("How this order was decided")).toBeVisible();
  await page.getByRole("tab", { name: "Integrity" }).click();
  await expect(page.getByText(/All \d+ steps verified/)).toBeVisible();
  await page.getByRole("button", { name: /Tamper with step/ }).click();
  await expect(page.getByText("Verification failed at step 4")).toBeVisible();
  await expect(page.getByText(/in-memory copy/)).toBeVisible();
  await page.getByRole("button", { name: "Restore original" }).click();
  await expect(page.getByText(/All \d+ steps verified/)).toBeVisible();
});
