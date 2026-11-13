"""InvenTree (inventory management) tools. API: /api/ with token auth."""

import re

from fastmcp import FastMCP

from . import config, policy
from .client import fmt, make_client, request_json

mcp = FastMCP(
    "inventree",
    instructions=("Inventory (InvenTree): look up parts, stock and bills of materials, "
                  "adjust stock levels, and raise purchase orders for shortfalls."))
required_env = "INVENTREE_API_TOKEN"

_client = make_client(config.INVENTREE_URL,
                      headers={"Authorization": f"Token {config.INVENTREE_API_TOKEN}"})


def _req(method: str, path: str, **kwargs):
    return request_json(_client, method, path, service="InvenTree",
                        token_hint="INVENTREE_API_TOKEN", **kwargs)


@mcp.tool
def inventree_search_parts(query: str, max_results: int = 10) -> str:
    """Search inventory parts by name/description/keywords. Returns part ids,
    names, and total stock."""
    ok, data = _req("GET", "/api/part/", params={"search": query,
                                                 "limit": max(1, min(max_results, 50))})
    if not ok:
        return data
    parts = data.get("results", data) if isinstance(data, dict) else data
    if not parts:
        return f"No parts match: {query}"
    return "\n".join(
        f"- [{p.get('pk')}] {p.get('full_name') or p.get('name')} — "
        f"stock: {p.get('total_in_stock', p.get('in_stock', '?'))} — {p.get('description', '')[:80]}"
        for p in parts)


@mcp.tool
def inventree_get_part(part_id: int) -> str:
    """Get full detail for one part: description, category, stock, units, IPN."""
    ok, data = _req("GET", f"/api/part/{part_id}/")
    if not ok:
        return data
    keys = ("pk", "full_name", "description", "category_name", "IPN", "units",
            "total_in_stock", "unallocated_stock", "ordering", "building",
            "assembly", "purchaseable", "salable", "active", "notes")
    return fmt({k: data.get(k) for k in keys if k in data})


@mcp.tool
def inventree_list_stock(part_id: int | None = None,
                         location_id: int | None = None,
                         max_results: int = 20) -> str:
    """List stock items, optionally filtered by part id and/or location id."""
    params: dict = {"limit": max(1, min(max_results, 100))}
    if part_id is not None:
        params["part"] = part_id
    if location_id is not None:
        params["location"] = location_id
    ok, data = _req("GET", "/api/stock/", params=params)
    if not ok:
        return data
    items = data.get("results", data) if isinstance(data, dict) else data
    if not items:
        return "No stock items found for that filter."
    return "\n".join(
        f"- stock item {s.get('pk')}: part {s.get('part')} — qty {s.get('quantity')} "
        f"@ location {s.get('location')} (status: {s.get('status_text', s.get('status'))})"
        for s in items)


def _items(data):
    return data.get("results", data) if isinstance(data, dict) else data


@mcp.tool
def inventree_get_bom(part_id: int, build_quantity: float = 1) -> str:
    """Bill of materials for an assembly, with stock check. For each component:
    quantity per assembly, total needed for build_quantity assemblies, stock
    available (unallocated), and any shortfall. Short components list their
    suppliers (supplier id + SKU) so a purchase order can be raised.
    Use this to answer "can we build/ship N of X?" before ordering parts."""
    if build_quantity <= 0:
        return "ERROR: build_quantity must be positive."
    # No `limit`: without it InvenTree returns the complete, unpaginated list.
    ok, data = _req("GET", "/api/bom/", params={"part": part_id, "sub_part_detail": "true"})
    if not ok:
        return data
    # Re-check the filter: some InvenTree list endpoints ignore unknown params.
    lines = [b for b in _items(data) if b.get("part") == part_id]
    if not lines:
        return (f"Part {part_id} has no bill of materials (is it an assembly? "
                f"check with inventree_get_part).")
    out, short_count = [], 0
    for b in lines:
        sub = b.get("sub_part_detail") or {}
        ok, part = _req("GET", f"/api/part/{b['sub_part']}/")
        if not ok:
            return part
        per = float(b.get("quantity") or 0)
        need = per * build_quantity
        have = float(part.get("unallocated_stock") or 0)
        short = max(0.0, need - have)
        label = f"[{b['sub_part']}] {sub.get('full_name') or sub.get('name')}"
        line = (f"- {label}: {per:g} per assembly, need {need:g}, "
                f"available {have:g}")
        if short:
            short_count += 1
            line += f" — SHORT {short:g}"
            ok, sps = _req("GET", "/api/company/part/", params={"part": b["sub_part"]})
            suppliers = [sp for sp in _items(sps) if sp.get("part") == b["sub_part"]] if ok else []
            line += ("; suppliers: " + ", ".join(
                f"supplier {sp.get('supplier')} SKU {sp.get('SKU')}" for sp in suppliers)
                if suppliers else "; no supplier on file")
        else:
            line += " — ok"
        out.append(line)
    head = (f"BOM for part {part_id}, building {build_quantity:g}: {len(lines)} components, "
            + (f"{short_count} short." if short_count else "all in stock."))
    return "\n".join([head, *out])


# ── Writes ─────────────────────────────────────────────────────────────────────

def _do_create_part(params: dict) -> str:
    payload = {"name": params["name"], "description": params["description"]}
    if params.get("category_id") is not None:
        payload["category"] = params["category_id"]
    ok, data = _req("POST", "/api/part/", json=payload)
    if not ok:
        return data
    return (f"OBJECT_ID={data.get('pk')}\n"
            f"Created part '{data.get('full_name') or data.get('name')}' "
            f"(id: {data.get('pk')}).")


def _do_adjust_stock(params: dict) -> str:
    endpoint = {"add": "/api/stock/add/", "remove": "/api/stock/remove/",
                "count": "/api/stock/count/"}[params["action"]]
    payload = {"items": [{"pk": params["stock_item_id"],
                          "quantity": str(params["quantity"])}],
               "notes": params.get("notes", "")}
    ok, data = _req("POST", endpoint, json=payload)
    if not ok:
        return data
    return (f"Stock {params['action']} applied to item {params['stock_item_id']} "
            f"(quantity {params['quantity']}).")


def _next_po_reference() -> tuple[bool, str]:
    """Next reference for the default PO-{ref:04d} pattern."""
    ok, data = _req("GET", "/api/order/po/", params={"limit": 1000})
    if not ok:
        return False, data
    nums = [int(m.group(1)) for po in _items(data)
            if (m := re.fullmatch(r"PO-(\d+)", str(po.get("reference", ""))))]
    return True, f"PO-{(max(nums) + 1) if nums else 1:04d}"


def _supplier_parts(supplier_id: int) -> tuple[bool, dict | str]:
    """part id → supplier-part id for one supplier."""
    ok, data = _req("GET", "/api/company/part/", params={"supplier": supplier_id, "limit": 1000})
    if not ok:
        return False, data
    return True, {sp["part"]: sp["pk"] for sp in _items(data)
                  if sp.get("supplier") == supplier_id}


def _do_create_purchase_order(params: dict) -> str:
    ok, sp_map = _supplier_parts(params["supplier_id"])
    if not ok:
        return sp_map
    missing = [ln["part_id"] for ln in params["lines"] if ln["part_id"] not in sp_map]
    if missing:  # validate everything before creating anything
        return (f"ERROR: supplier {params['supplier_id']} has no supplier part for "
                f"part id(s) {missing}. Check suppliers with inventree_get_bom.")
    ok, reference = _next_po_reference()
    if not ok:
        return reference
    ok, po = _req("POST", "/api/order/po/", json={
        "supplier": params["supplier_id"], "reference": reference,
        "description": params.get("description", "")})
    if not ok:
        return po
    for ln in params["lines"]:
        ok, data = _req("POST", "/api/order/po-line/", json={
            "order": po["pk"], "part": sp_map[ln["part_id"]], "quantity": ln["quantity"]})
        if not ok:
            # Roll back: a half-built order is worse than none. A Pending PO
            # can be deleted outright.
            rolled_back, _ = _req("DELETE", f"/api/order/po/{po['pk']}/")
            state = ("the draft was rolled back (deleted)" if rolled_back else
                     f"rollback FAILED — draft {reference} (id {po['pk']}) still exists; "
                     f"tell the user")
            return (f"ERROR: adding a line for part {ln['part_id']} to {reference} "
                    f"failed: {data}. {state}.")
    return (f"OBJECT_ID={po['pk']}\n"
            f"Created purchase order {reference} (id: {po['pk']}) with "
            f"{len(params['lines'])} line(s), status Pending. It has NOT been sent to "
            f"the supplier — placing it needs inventree_issue_purchase_order.")


def _do_issue_purchase_order(params: dict) -> str:
    ok, data = _req("POST", f"/api/order/po/{params['order_id']}/issue/", json={})
    if not ok:
        return data
    return f"Purchase order {params['order_id']} issued (placed with the supplier)."


policy.register_executor("inventree", "inventree_create_purchase_order",
                         _do_create_purchase_order)
policy.register_executor("inventree", "inventree_issue_purchase_order",
                         _do_issue_purchase_order)
policy.register_executor("inventree", "inventree_create_part", _do_create_part)
policy.register_executor("inventree", "inventree_adjust_stock", _do_adjust_stock)


@mcp.tool
def inventree_create_part(name: str, description: str,
                          category_id: int | None = None) -> str:
    """WRITE ACTION — creates a new part in the inventory system. Only call
    when the user asked for it. The user is notified with a summary.
    Preconditions: the user asked for the part; category_id (if given) exists.
    Effects: a new part record in live business inventory; user notified.
    Failure modes: 'ERROR: ...' when the InvenTree API rejects the call
    (e.g. unknown category, duplicate constraints)."""
    return policy.apply_policy(
        domain="inventree", tool="inventree_create_part", action_kind="create",
        summary=f"Create inventory part '{name}'",
        params={"name": name, "description": description, "category_id": category_id},
        changes=[f"New part '{name}': {description[:100]}"],
        created_object_id_from_result=True)


@mcp.tool
def inventree_adjust_stock(stock_item_id: int, quantity: float, action: str,
                           notes: str = "") -> str:
    """WRITE ACTION — adjusts live stock levels ('add', 'remove', or 'count').
    This modifies business inventory data, so it is held for the user's
    approval before executing. Always include notes explaining why.
    Preconditions: stock_item_id exists; notes state the reason for the
    adjustment.
    Effects: after approval, live stock quantity changes (business data).
    Failure modes: 'ERROR: ...' on invalid action; otherwise PENDING
    APPROVAL #id (report, never retry); API errors surface in the approval
    outcome."""
    if action not in ("add", "remove", "count"):
        return "ERROR: action must be one of add, remove, count."
    return policy.apply_policy(
        domain="inventree", tool="inventree_adjust_stock", action_kind="effect",
        summary=(f"Stock {action}: item {stock_item_id}, quantity {quantity}"
                 + (f" — {notes}" if notes else "")),
        params={"stock_item_id": stock_item_id, "quantity": quantity,
                "action": action, "notes": notes},
        changes=[f"{action} {quantity} on stock item {stock_item_id}"])


@mcp.tool
def inventree_create_purchase_order(supplier_id: int, lines: list[dict],
                                    description: str = "") -> str:
    """WRITE ACTION — creates a DRAFT purchase order (status Pending) for one
    supplier. lines is a list of {"part_id": <int>, "quantity": <number>}
    using internal part ids (as shown by inventree_get_bom). The draft is NOT
    sent to the supplier; placing it is a separate, approval-gated step
    (inventree_issue_purchase_order). The user is notified with a summary.
    Preconditions: the supplier has a supplier part for every part_id (see the
    suppliers listed for short lines in inventree_get_bom); quantities > 0.
    Effects: a new Pending purchase order with one line per part.
    Failure modes: 'ERROR: ...' if lines are malformed or a part has no
    supplier part for this supplier (validated first; nothing is created). If
    the API rejects a line after the order was created, the draft is deleted
    again and the ERROR says so (or says the rollback failed and which draft
    remains)."""
    try:
        clean = [{"part_id": int(ln["part_id"]), "quantity": float(ln["quantity"])}
                 for ln in lines]
    except (KeyError, TypeError, ValueError):
        return 'ERROR: lines must be a list of {"part_id": int, "quantity": number}.'
    if not clean or any(ln["quantity"] <= 0 for ln in clean):
        return "ERROR: give at least one line, each with a positive quantity."
    return policy.apply_policy(
        domain="inventree", tool="inventree_create_purchase_order", action_kind="create",
        summary=f"Draft purchase order for supplier {supplier_id} ({len(clean)} line(s))",
        params={"supplier_id": supplier_id, "lines": clean, "description": description},
        changes=[f"part {ln['part_id']} x {ln['quantity']:g}" for ln in clean],
        created_object_id_from_result=True)


@mcp.tool
def inventree_issue_purchase_order(order_id: int) -> str:
    """WRITE ACTION — issues (places) a Pending purchase order with its
    supplier: a business commitment to spend money, so it is held for the
    user's approval before executing.
    Preconditions: order_id is a Pending purchase order (e.g. one you created
    with inventree_create_purchase_order) and the user wants it placed.
    Effects: after approval, the order's status becomes Placed.
    Failure modes: 'ERROR: ...' if the order can't be read; otherwise PENDING
    APPROVAL #id (report it to the user, never retry); API errors surface in
    the approval outcome."""
    ok, po = _req("GET", f"/api/order/po/{order_id}/", params={"supplier_detail": "true"})
    if not ok:
        return po
    supplier = (po.get("supplier_detail") or {}).get("name") or f"supplier {po.get('supplier')}"
    return policy.apply_policy(
        domain="inventree", tool="inventree_issue_purchase_order", action_kind="effect",
        summary=f"Place purchase order {po.get('reference')} with {supplier}",
        params={"order_id": order_id},
        target_id=str(order_id),
        changes=[f"{po.get('reference')}: {po.get('line_items', '?')} line(s), "
                 f"status {po.get('status_text', '?')} → Placed"])
