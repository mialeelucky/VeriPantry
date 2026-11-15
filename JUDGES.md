# VeriPantry: guide for judges

VeriPantry is the gateway a wholesaler (Valio Aimo) puts in front of its systems
so that buyers' purchasing agents can search, get prices, order and ask a human
for approval, safely and with a full audit trail. This guide gets the working
prototype running on your computer in a few minutes and shows what to try.

Video walkthrough (1:42): see the link in our submission.

## 1. Start it (one command)

You need **Python 3.11+** and **Node.js 20.19+ or 22.12+**. No API key or account.

```bash
git clone https://github.com/mialeelucky/VeriPantry.git
cd VeriPantry
```

| System | Command |
|---|---|
| Windows | `py run_demo.py` |
| macOS / Linux | `python3 run_demo.py` |

The first run installs the packages (2–3 minutes). Later runs start in seconds.
The script starts three local services (gateway, buyer agent, web app) and opens
<http://localhost:5173/stage>. Press **Ctrl+C** in the terminal to stop everything.

To start again from an empty order history: `py run_demo.py --reset`
(`python3 run_demo.py --reset` on macOS/Linux).

> The demo runs on **recorded** Valio Aimo stock and price data (taken on
> 15 Nov 2026, deliveries on Monday 16 Nov), with the gateway's clock set to
> that moment. That is why times in the app show 15 Nov, and why every run
> gives the same results.

## 2. What you see

The start page (`/stage`) shows two people side by side:

- **Left: the chef** talking to their purchasing agent, in five steps:
  Ask, Confirm, Working, Choose, Done.
- **Right: the Head Chef's phone**, where approval requests arrive as notifications.
- **Bottom strip:** the current transaction and its signed audit receipt.

## 3. Try these scenarios

Click a button under **"Try a scenario"**, then **Next**, then **Start**.

| Scenario | What it shows | Result |
|---|---|---|
| **Lactose-free milk for Monday** | Simple order within the agent's authority | Ordered automatically, €1,010 |
| **Arla, but stock is short** | The requested Arla product is short. Three ranked plans (Best / Second / Third) with reasons | Best (€1,010) ordered automatically |
| **Arla, 3,000 litres for an event** | €3,030 is above the agent's €2,000 limit | Request pushed to the Head Chef's phone. Click it, then **Make a decision**, then **Approve** |
| **6,000 litres for the whole chain** | €6,060 is above the Head Chef's €5,000 limit | Needs the **Finance Lead** (see section 4) |
| **A guest with a milk allergy** | Allergen hard filter: only products explicitly free from milk pass, so only plant-based drinks are offered | Plans above €2,000 go to the Head Chef |

The authority levels: up to **€2,000** the agent orders by itself; up to
**€5,000** the Head Chef decides; above that, the Finance Lead.

## 4. Switch person

Open <http://localhost:5173/sign-in> and pick a demo person (no password in the demo):

| Person | Works for | Can |
|---|---|---|
| **Head Chef** | the buyer (Hotel 123) | approve up to €5,000, see the buyer's audit view |
| **Finance Lead** | the buyer | approve any amount |
| **Valio Auditor** | Valio Aimo | see every transaction in Valio's full audit view, run the tamper test |

Approvals are under **Approvals** (`/approvals`) for the Head Chef and Finance Lead.

## 5. Audit and PDF report

1. Sign in as **Valio Auditor**. You land on the audit list (`/audit`).
2. Open any transaction. There are three tabs:
   - **Story:** how the order was decided, in a few plain sentences.
   - **Timeline:** every logged step. Switch between **Buyer view** (Valio's
     internal data is hidden) and **Valio view**.
   - **Integrity:** each step is hash-chained and sealed with Valio Aimo's key.
     Click **Tamper with step…** to change one step in memory and see exactly
     where verification breaks. **Restore original** undoes it. The stored
     record is never changed.
3. Click **Export PDF** (top right) to download the audit report for that transaction.

Signed in as Head Chef or Finance Lead, you see the same pages for your own
organisation's orders, in the buyer view.

## 6. Typing your own request

The demo's buyer agent is a **rule-based stand-in, not an LLM**. It reliably
understands the scenario sentences and simple requests about **milk and cream**,
for example:

- `500 litres of lactose-free milk for Friday`
- `We need 200 litres of whole milk tomorrow`
- `2,000 litres of Valio skimmed milk by Monday` (over €2,000, so it asks the Head Chef)
- `100 litres of whipping cream by Monday`

It recognises quantities (litres, kg, pieces), weekdays / "tomorrow" / dates,
lactose-free, gluten-free and vegan claims, milk / gluten / egg / nut allergies,
and the brands Arla and Valio. Other products (e.g. sugar, chocolate) are not
recognised. The Confirm step then asks you to fill in what is missing. The
gateway, guardrails and audit trail are the same whichever agent calls them;
an LLM agent would only replace this understanding step.

## 7. If something goes wrong

- **"Port already in use":** the demo (or something else) is already running on
  port 8000, 8100 or 5173. Stop it and run the command again.
- **`python` opens the Microsoft Store (Windows):** use `py run_demo.py`.
- Logs are in `backend/var/logs/`.

## 8. Where to read more

| Document | About |
|---|---|
| [`docs/trust-protocol.md`](docs/trust-protocol.md) | How agents prove who they are and what they may do, and what data they may see |
| [`docs/fulfilment-and-substitution.md`](docs/fulfilment-and-substitution.md) | How plans are found and ranked (Best / Second / Third) |
| [`docs/guardrails.md`](docs/guardrails.md) | What the agent may decide alone, and what goes to a person |
| [`docs/audit-log.md`](docs/audit-log.md) | The hash-chained, signed audit log and its reports |
| [`docs/frontend.md`](docs/frontend.md) | The web app |
