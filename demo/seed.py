#!/usr/bin/env python3
"""Seed the D1 demo scenario into running InvenTree + FreeScout. Idempotent.

Creates (only if missing):
  InvenTree  category "MakerOps Demo", location "Demo Shop Shelf",
             assembly "Enclosure EN-100" with a 5-line BOM, component stock that
             falls short for 20 units (lids and screws), supplier "Demo Supply
             Co." with supplier parts for exactly the short components.
  FreeScout  an inbound customer email in the "MakerOps Demo" mailbox asking
             for 20 enclosures.

Every InvenTree record carries the tag "makerops-demo" (categories, which
can't be tagged, are matched by name). reset.py removes exactly these records.

Usage:  python3 demo/seed.py            (run again any time; it never duplicates)
"""

from _api import (CATEGORY, CATEGORY_MARKER, CUSTOMER_EMAIL, DEMO_TAG, LOCATION, SUBJECT, SUPPLIER,
                  demo_conversations, find_mailbox, find_one, freescout, inventree,
                  load_env, results)

ORDER_QTY = 20

ASSEMBLY = {"IPN": "DEMO-EN-100", "name": "Enclosure EN-100",
            "description": "[demo] Sensor enclosure, ABS shell + lid, IP54"}

# IPN, name, description, per-assembly qty, stock on hand, supplier SKU or None
COMPONENTS = [
    ("DEMO-SH-01", "Enclosure shell 120x80x40", "[demo] ABS shell, black", 1, 25, None),
    ("DEMO-LID-01", "Enclosure lid 120x80", "[demo] ABS lid with gasket groove", 1, 8, "DSC-LID-120"),
    ("DEMO-GSK-01", "Silicone gasket 120x80", "[demo] 2 mm silicone gasket", 1, 20, None),
    ("DEMO-INS-M3", "M3 heat-set insert", "[demo] Brass insert, M3 x 4 mm", 4, 100, None),
    ("DEMO-SCR-M3", "M3x8 screw", "[demo] Stainless pan-head screw", 4, 50, "DSC-M3X8-SS"),
]

CUSTOMER_MESSAGE = (
    "Hi,\n\nWe'd like to order 20 of your EN-100 sensor enclosures for a pilot "
    "deployment. Can you confirm whether you have them in stock, and if not, "
    "when you could ship all 20?\n\nThanks,\nJordan Reyes\nJuniper Labs")


def ensure(api, list_path, match: dict, create_body: dict, label: str):
    existing = find_one(api, list_path, **match)
    if existing:
        print(f"  = {label} (exists, pk {existing.get('pk')})")
        return existing
    created = api.post(list_path, create_body)
    if isinstance(created, list):  # e.g. /api/stock/ returns the created item(s)
        created = created[0]
    print(f"  + {label} (created, pk {created.get('pk')})")
    return created


def seed_inventree(inv):
    print("InvenTree:")
    tags = [DEMO_TAG]
    cat = next((c for c in results(inv.get("/api/part/category/", search=CATEGORY))
                if c["name"] == CATEGORY), None)
    if cat and cat.get("description") != CATEGORY_MARKER:
        raise SystemExit(f"  A category named {CATEGORY!r} already exists and was not created "
                         f"by this script — refusing to put demo data in it. Rename it, or "
                         f"change CATEGORY in demo/_api.py.")
    if cat:
        print(f"  = category {CATEGORY!r} (exists, pk {cat['pk']})")
    else:
        cat = inv.post("/api/part/category/", {
            "name": CATEGORY, "description": CATEGORY_MARKER})
        print(f"  + category {CATEGORY!r} (created, pk {cat['pk']})")

    loc = next((s for s in results(inv.get("/api/stock/location/", name=LOCATION))
                if s["name"] == LOCATION), None)
    if loc:
        print(f"  = location {LOCATION!r} (exists, pk {loc['pk']})")
    else:
        loc = inv.post("/api/stock/location/", {"name": LOCATION, "tags": tags,
                                                "description": "[demo] stock for the demo scenario"})
        print(f"  + location {LOCATION!r} (created, pk {loc['pk']})")

    assembly = ensure(inv, "/api/part/", {"IPN": ASSEMBLY["IPN"]}, {
        **ASSEMBLY, "category": cat["pk"], "assembly": True, "component": False,
        "purchaseable": False, "salable": True, "tags": tags}, ASSEMBLY["name"])

    supplier = next((c for c in results(inv.get("/api/company/", name=SUPPLIER))
                     if c["name"] == SUPPLIER), None)
    if supplier:
        print(f"  = supplier {SUPPLIER!r} (exists, pk {supplier['pk']})")
    else:
        supplier = inv.post("/api/company/", {
            "name": SUPPLIER, "description": "[demo] fictional supplier", "currency": "USD",
            "is_supplier": True, "is_customer": False, "is_manufacturer": False,
            "tags": tags})
        print(f"  + supplier {SUPPLIER!r} (created, pk {supplier['pk']})")

    for ipn, name, desc, per, on_hand, sku in COMPONENTS:
        part = ensure(inv, "/api/part/", {"IPN": ipn}, {
            "IPN": ipn, "name": name, "description": desc, "category": cat["pk"],
            "component": True, "purchaseable": True, "assembly": False,
            "tags": tags}, name)
        ensure(inv, "/api/bom/", {"part": assembly["pk"], "sub_part": part["pk"]}, {
            "part": assembly["pk"], "sub_part": part["pk"], "quantity": per},
            f"BOM line {per} x {ipn}")
        ensure(inv, "/api/stock/", {"part": part["pk"], "location": loc["pk"]}, {
            "part": part["pk"], "quantity": on_hand, "location": loc["pk"],
            "notes": "[demo] seeded stock", "tags": tags},
            f"stock {on_hand} x {ipn}")
        if sku:
            ensure(inv, "/api/company/part/", {"part": part["pk"], "supplier": supplier["pk"]}, {
                "part": part["pk"], "supplier": supplier["pk"], "SKU": sku,
                "description": f"[demo] {name}", "tags": tags},
                f"supplier part {sku}")

    print(f"\n  Shortfall for {ORDER_QTY} x {ASSEMBLY['IPN']}:")
    for ipn, _, _, per, on_hand, sku in COMPONENTS:
        need = per * ORDER_QTY
        short = max(0, need - on_hand)
        flag = f"SHORT {short}" + (f" (buy {sku} from {SUPPLIER})" if sku else "") if short else "ok"
        print(f"    {ipn:<12} need {need:>3}, have {on_hand:>3} → {flag}")


def seed_freescout(fs):
    print("\nFreeScout:")
    box = find_mailbox(fs)
    if box is None:
        raise SystemExit(
            "  No 'MakerOps Demo' mailbox. FreeScout's API can't create mailboxes — "
            "create one named 'MakerOps Demo' in the FreeScout UI (Manage → Mailboxes), "
            "then re-run. See demo/README.md.")
    existing = [c for c in demo_conversations(fs, box["id"]) if c.get("subject") == SUBJECT]
    if existing:
        print(f"  = customer email {SUBJECT!r} (exists, conversation {existing[0]['id']})")
        return
    conv = fs.post("/api/conversations", {
        "type": "email", "mailboxId": box["id"], "subject": SUBJECT,
        "customer": {"email": CUSTOMER_EMAIL, "firstName": "Jordan", "lastName": "Reyes"},
        "imported": True,  # store only: FreeScout sends no email for imported threads
        "status": "active",
        "threads": [{"type": "customer", "text": CUSTOMER_MESSAGE,
                     "customer": {"email": CUSTOMER_EMAIL}}],
    })
    print(f"  + customer email {SUBJECT!r} (created, conversation {conv.get('id')})")


def main():
    env = load_env()
    seed_inventree(inventree(env))
    seed_freescout(freescout(env))
    print("\nDone. Remove everything with: python3 demo/reset.py")


if __name__ == "__main__":
    main()
