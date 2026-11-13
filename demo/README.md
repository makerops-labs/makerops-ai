# Demo data: "Order for 20 enclosures"

Seed data for the lead scenario. A customer emails asking for 20 EN-100
sensor enclosures. The agent checks the bill of materials against stock,
finds two short components, drafts a purchase order for them, asks a human to
approve placing it, and drafts the customer reply.

```
customer email (FreeScout)
  → inventree_get_bom(EN-100, 20)          read: lids short 12, screws short 30
  → inventree_create_purchase_order(...)    notify: Pending PO-NNNN, not sent
  → inventree_issue_purchase_order(...)     GATE: PENDING APPROVAL → human at /approvals
  → freescout_reply(..., draft=True)        notify: draft reply, a human sends it
```

## What `seed.py` creates

| App | Records |
| --- | --- |
| InvenTree | category **MakerOps Demo**, location **Demo Shop Shelf**, assembly **Enclosure EN-100** (`DEMO-EN-100`) with a 5-line BOM, component stock, supplier **Demo Supply Co.** with supplier parts for the two short components |
| FreeScout | an inbound customer email, "Order for 20 EN-100 enclosures", in the **MakerOps Demo** mailbox (stored only; no email is sent) |

Stock is chosen so that building 20 leaves exactly two shortfalls:

| Component | Per unit | Need (20) | On hand | Result |
| --- | ---: | ---: | ---: | --- |
| `DEMO-SH-01` shell | 1 | 20 | 25 | ok |
| `DEMO-LID-01` lid | 1 | 20 | 8 | **short 12** (supplier SKU `DSC-LID-120`) |
| `DEMO-GSK-01` gasket | 1 | 20 | 20 | ok (exactly enough) |
| `DEMO-INS-M3` insert | 4 | 80 | 100 | ok |
| `DEMO-SCR-M3` screw | 4 | 80 | 50 | **short 30** (supplier SKU `DSC-M3X8-SS`) |

## Setup (once)

1. InvenTree and FreeScout from makerops-core are running.
2. **FreeScout mailbox:** FreeScout's API can't create mailboxes. In the
   FreeScout UI, go to Manage → Mailboxes → New Mailbox and name it exactly
   `MakerOps Demo` (any address, e.g. `sales@makerops-demo.example`; no mail
   fetching needed).
3. `cp demo/.env.example demo/.env` and fill in:
   - `INVENTREE_API_TOKEN`: InvenTree → user menu → Settings → Security →
     API Tokens → Add.
   - `FREESCOUT_API_KEY`: the same key mcp-tools uses (`mcp-tools/.env`).

## Usage

Python 3.10+, standard library only (nothing to install).

```bash
python3 demo/seed.py              # create the scenario (safe to re-run)
python3 demo/reset.py --dry-run   # list what would be removed
python3 demo/reset.py             # remove demo records only
```

**Idempotent.** Every record is looked up before it is created, so re-running
`seed.py` creates nothing new. Lookups re-check every field on the client side,
because some InvenTree list endpoints silently ignore filters.

**Reset removes only demo data, and never cascades.**

What counts as demo data:
- InvenTree records tagged `makerops-demo` (reset confirms the tag on each
  record).
- The category whose description is the demo marker. Categories can't be
  tagged, and `seed.py` refuses to use a same-named category it didn't create.
- Stock that is in the demo location *and* belongs to a demo part (InvenTree
  drops tags on stock items).
- Purchase orders for the demo supplier, including ones an agent created
  during a run. Placed orders are cancelled first.
- In FreeScout, conversations re-checked client-side to have the demo customer
  in the demo mailbox. The mailbox itself stays.

Anything that would cascade into non-demo data is kept and reported with `!`:
- a demo part used in a non-demo assembly's BOM, or stocked outside the demo
  location;
- a supplier that still has non-demo supplier parts;
- a demo part that another supplier also supplies;
- a location or category that still contains anything (InvenTree would
  re-parent children or delete contents).

`--dry-run` lists what reset would try to remove. It can't predict every
"kept" decision for containers, because those depend on deletions it doesn't
perform.

Verified against InvenTree 1.5.2 and the FreeScout in makerops-core:
- seed twice → no duplicates;
- reset → zero demo records;
- reset with two non-demo parts present (one inside the demo category) → both
  untouched and the category kept;
- reset with a non-demo assembly using a demo screw, demo-part stock on a
  non-demo shelf, and a sub-category under the demo category → all three
  untouched, and the screw part and category kept with explanations;
- reset with a non-demo part stocked on the demo shelf → that stock and the
  shelf kept;
- reset after an agent placed a PO → PO cancelled and removed.

The scripts back off and retry when InvenTree rate-limits (HTTP 429).
