# Demo video: "Order for 20 enclosures"

A 2–3 minute screen recording of the lead scenario, plus an optional
30-second segment on the self-improvement loop. Each shot lists what to show
on screen and the narration to read over it. Times are targets, not limits.

## Before recording

Prerequisites: this script refers to two files that land separately, the
architecture diagram (`assets/architecture.svg`, T5) and the eval results
table (`evals/RESULTS.md`, written by the T4 baseline run). Record after
both are on `main`.

- [ ] Fresh demo data: `python3 demo/reset.py && python3 demo/seed.py`
- [ ] No pending approvals left over: `/approvals` shows an empty queue.
- [ ] Model: use the model with the best score in `evals/RESULTS.md` for the
      Ops Assistant preset (it defaults to `qwen3.5:9b`). Stop `trellis` first
      if that's a 35b model.
- [ ] Do one unrecorded rehearsal of the prompt below. If the agent takes a
      wrong turn, reset and seed again before the real take.
- [ ] Open tabs, in order: Open WebUI (Ops Assistant chat), FreeScout
      (MakerOps Demo mailbox), InvenTree (Enclosure EN-100), `/approvals`.
- [ ] Browser zoom ~125% so text is readable at 1080p. Hide bookmarks and
      notifications.

The prompt (paste it, don't type it on camera):

> We got an email from Juniper Labs ordering 20 EN-100 enclosures. Check
> whether we can build them, order whatever we're short on from our supplier,
> and draft a reply to the customer. Don't send anything without my approval.

## Shot list

| # | Time | On screen | Narration |
| --- | --- | --- | --- |
| 1 | 0:00–0:15 | The architecture diagram (`assets/architecture.svg`), slow zoom on the red approval path | "This is MakerOps: local AI agents running a small manufacturing shop's real tools: inventory, email, docs. Everything runs on one machine. The rule is simple: agents can read and draft freely, but anything with a business effect waits for a human." |
| 2 | 0:15–0:30 | FreeScout, MakerOps Demo mailbox: open the email "Order for 20 EN-100 enclosures" from Jordan at Juniper Labs | "A customer wants 20 enclosures. Normally I'd check stock, work out what's missing, raise a purchase order and write back. Let's hand that to the agent." |
| 3 | 0:30–0:45 | Open WebUI, Ops Assistant preset; paste the prompt and send | "I ask in plain English, and I tell it not to send anything without me." |
| 4 | 0:45–1:10 | The tool calls expanding in the chat: `inventree_get_bom` and its result | "It reads the bill of materials against live stock in InvenTree. Twenty units need 20 lids and 80 screws; we have 8 lids and 50 screws. So we're short 12 lids and 30 screws, and everything else is covered." |
| 5 | 1:10–1:30 | Chat: `inventree_create_purchase_order` result, a Pending PO with two lines | "It drafts a purchase order with our supplier for exactly the shortfall. Creating a draft is safe, so it just happens, and I'm notified." |
| 6 | 1:30–1:45 | Chat: `inventree_issue_purchase_order` returns `PENDING APPROVAL #<id>`; the agent's reply says it's waiting for approval | "Actually placing the order spends money, so the tool server holds it. The agent can't approve its own request, and it tells me it's waiting rather than retrying." |
| 7 | 1:45–2:00 | Chat: `freescout_reply` saved as a draft; agent's final summary | "It drafts the customer reply too: realistic numbers, nothing promised that we can't build, and saved as a draft for me to send." |
| 8 | 2:00–2:20 | `/approvals`: the pending "issue purchase order" request with its details; click **Approve** | "Here's my approval queue. I can see exactly what will happen before it happens. I approve." |
| 9 | 2:20–2:35 | InvenTree: the PO now shows **Placed**, lines lids ×12 and screws ×30 | "The order is placed in InvenTree, for the right parts and quantities." |
| 10 | 2:35–2:50 | FreeScout: the draft reply in the conversation | "And the reply is waiting in the help desk for me to review and send." |
| 11 | 2:50–3:00 | `evals/RESULTS.md` table | "This exact scenario is one of 29 tasks in an evaluation I run across four local models, scoring tool choice, approval behaviour and the final result, so I know how reliable it is, not just that it worked once." |

## Optional: self-improvement loop (≈30 s)

| # | On screen | Narration |
| --- | --- | --- |
| A | `/approvals`: a pending `propose_code_change` with its diff | "The stack can also propose changes to its own code. Every change is a diff that waits for my approval." |
| B | After **Approve**: the redeploy result on `/approvals` (healthy, or reverted) | "When I approve, the redeploy service writes the file, restarts the container and watches its health check. If it doesn't come back healthy, the change is reverted automatically and I'm told." |

To show a revert on camera, prepare a deliberately broken change in a
rehearsal environment. Never approve a broken change against the stack you
use for real work.

## Retakes

- If the agent asks how many to order or which supplier, that's acceptable
  behaviour. Answer briefly on camera, or reset and retake.
- If a step fails, reset (`demo/reset.py && demo/seed.py`) and reject any
  leftover approvals before the next take.
- Shots 1, 2 and 8–11 don't depend on the model and can be recorded
  separately and cut in.
