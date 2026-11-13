#!/usr/bin/env python3
"""Remove the demo scenario's records — and only those.

InvenTree: purchase orders for the demo supplier (including ones an agent
created during a demo run), stock in the demo location, BOM lines and supplier
parts of demo parts, the demo parts (tag "makerops-demo" AND in the demo
category), the demo supplier, location, and category.
FreeScout: conversations with the demo customer in the "MakerOps Demo"
mailbox. The mailbox itself is kept (it was created by hand).

Records are only deleted when they carry the demo tag or live in a demo-only
container (demo category/location/supplier), so real data is never touched.

Usage:  python3 demo/reset.py [--dry-run]
"""

import sys

from _api import (CATEGORY, CATEGORY_MARKER, DEMO_TAG, LOCATION, SUPPLIER, demo_conversations,
                  find_mailbox, freescout, inventree, load_env, results)

DRY = "--dry-run" in sys.argv


def _delete(api, path, label):
    print(f"  - {label}" + (" (dry run)" if DRY else ""))
    if not DRY:
        api.delete(path)


def _tagged(api, detail_path: str) -> bool:
    """True if the record at detail_path carries the demo tag.

    InvenTree 1.5 quirks: `tags` is only returned by DETAIL endpoints and only
    with ?tags=true (on LIST endpoints the same param acts as a filter and
    returns nothing), and tag filters are silently ignored. So each candidate
    is confirmed individually. Stock items are the exception: InvenTree drops
    tags on stock creation, so stock is identified by demo location + demo part.
    """
    return DEMO_TAG in (api.get(detail_path, tags="true").get("tags") or [])


def reset_inventree(inv):
    print("InvenTree:")
    supplier = next((c for c in results(inv.get("/api/company/", name=SUPPLIER))
                     if c["name"] == SUPPLIER and _tagged(inv, f"/api/company/{c['pk']}/")), None)
    cat = next((c for c in results(inv.get("/api/part/category/", search=CATEGORY))
                if c["name"] == CATEGORY and c.get("description") == CATEGORY_MARKER), None)
    loc = next((s for s in results(inv.get("/api/stock/location/", name=LOCATION))
                if s["name"] == LOCATION and _tagged(inv, f"/api/stock/location/{s['pk']}/")), None)

    if supplier:
        for po in results(inv.get("/api/order/po/", supplier=supplier["pk"])):
            if po["supplier"] != supplier["pk"]:
                continue
            # Issued (placed) orders must be cancelled before InvenTree allows deletion.
            if po.get("status_text", "").lower() not in ("pending", "cancelled") and not DRY:
                inv.post(f"/api/order/po/{po['pk']}/cancel/", {})
            _delete(inv, f"/api/order/po/{po['pk']}/", f"purchase order {po['reference']}")

    parts = []
    if cat:
        parts = [p for p in results(inv.get("/api/part/", category=cat["pk"]))
                 if p["category"] == cat["pk"] and _tagged(inv, f"/api/part/{p['pk']}/")]

    if loc:
        demo_part_ids = {p["pk"] for p in parts}
        for item in results(inv.get("/api/stock/", location=loc["pk"])):
            if item["location"] == loc["pk"] and item["part"] in demo_part_ids:
                _delete(inv, f"/api/stock/{item['pk']}/",
                        f"stock item {item['pk']} ({item.get('quantity')} x part {item['part']})")

    for part in parts:
        for line in results(inv.get("/api/bom/", part=part["pk"])):
            if line["part"] != part["pk"]:  # filters can be ignored; re-check
                continue
            _delete(inv, f"/api/bom/{line['pk']}/", f"BOM line {line['pk']} of {part['IPN']}")
    demo_part_ids = {p["pk"] for p in parts}
    if supplier:  # by supplier: filtering by a non-purchaseable part is a 400
        for sp in results(inv.get("/api/company/part/", supplier=supplier["pk"])):
            if (sp["supplier"] == supplier["pk"] and sp["part"] in demo_part_ids
                    and _tagged(inv, f"/api/company/part/{sp['pk']}/")):
                _delete(inv, f"/api/company/part/{sp['pk']}/", f"supplier part {sp['SKU']}")
    # A demo part referenced by anything outside the demo (used in a non-demo
    # assembly, stocked elsewhere) is kept: deleting it would cascade into that.
    # No `limit`: these list endpoints return everything, unpaginated.
    all_bom = results(inv.get("/api/bom/"))
    all_supplier_parts = results(inv.get("/api/company/part/"))
    kept_parts = []
    for part in parts:
        outside_bom = [b for b in all_bom if b["sub_part"] == part["pk"]
                       and b["part"] not in demo_part_ids]
        outside_stock = [s for s in results(inv.get("/api/stock/", part=part["pk"]))
                         if s["part"] == part["pk"]
                         and (loc is None or s["location"] != loc["pk"])]
        other_suppliers = [sp for sp in all_supplier_parts if sp["part"] == part["pk"]
                           and (supplier is None or sp["supplier"] != supplier["pk"])]
        if outside_bom or outside_stock or other_suppliers:
            kept_parts.append(part)
            print(f"  ! part {part['IPN']} kept: {len(outside_bom)} non-demo BOM line(s), "
                  f"{len(outside_stock)} stock item(s) outside the demo, "
                  f"{len(other_suppliers)} other supplier part(s)")
    for part in [p for p in parts if p not in kept_parts]:
        if not DRY:
            inv.patch(f"/api/part/{part['pk']}/", {"active": False})  # required before delete
        _delete(inv, f"/api/part/{part['pk']}/", f"part {part['IPN']}")

    if supplier:
        leftover = [sp for sp in results(inv.get("/api/company/part/", supplier=supplier["pk"]))
                    if sp["supplier"] == supplier["pk"]] if not DRY else []
        if leftover or kept_parts:
            why = (f"{len(leftover)} non-demo supplier part(s)" if leftover else
                   "a demo part was kept above (re-run reset after resolving it)")
            print(f"  ! supplier {SUPPLIER!r} kept: {why}")
        else:
            _delete(inv, f"/api/company/{supplier['pk']}/", f"supplier {SUPPLIER!r}")
    leftover_stock = [x for x in results(inv.get("/api/stock/", location=loc["pk"]))
                      if x["location"] == loc["pk"]
                      and (DRY is False or x["part"] not in demo_part_ids)] if loc else []
    sub_locations = [x for x in results(inv.get("/api/stock/location/", parent=loc["pk"]))
                     if x.get("parent") == loc["pk"]] if loc else []
    if loc and (leftover_stock or sub_locations):
        print(f"  ! location {LOCATION!r} kept: {len(leftover_stock)} non-demo stock item(s), "
              f"{len(sub_locations)} sub-location(s) (would be moved or re-parented)")
    elif loc:
        # Never cascade: demo stock was already deleted item by item above, so
        # any stock or sub-location still here is not ours and blocks deletion.
        print(f"  - location {LOCATION!r}" + (" (dry run)" if DRY else ""))
        if not DRY:
            inv.delete(f"/api/stock/location/{loc['pk']}/",
                       {"delete_stock_items": False, "delete_sub_locations": False})
    if cat:
        remaining = [p for p in results(inv.get("/api/part/", category=cat["pk"]))
                     if p["category"] == cat["pk"]]
        children = [c for c in results(inv.get("/api/part/category/", parent=cat["pk"]))
                    if c.get("parent") == cat["pk"]]
        if (remaining or children) and not DRY:
            print(f"  ! category {CATEGORY!r} kept: {len(remaining)} part(s) and "
                  f"{len(children)} sub-categor(ies) in it (would be deleted or re-parented)")
        else:
            print(f"  - category {CATEGORY!r}" + (" (dry run)" if DRY else ""))
            if not DRY:  # never cascade into parts or sub-categories
                inv.delete(f"/api/part/category/{cat['pk']}/",
                           {"delete_parts": False, "delete_child_categories": False})


def reset_freescout(fs):
    print("\nFreeScout:")
    box = find_mailbox(fs)
    if box is None:
        print("  (no 'MakerOps Demo' mailbox — nothing to remove)")
        return
    for conv in demo_conversations(fs, box["id"]):
        _delete(fs, f"/api/conversations/{conv['id']}",
                f"conversation {conv['id']} {conv.get('subject')!r}")


def main():
    env = load_env()
    reset_inventree(inventree(env))
    reset_freescout(freescout(env))
    print("\nDone." if not DRY else "\nDry run — nothing was deleted.")


if __name__ == "__main__":
    main()
