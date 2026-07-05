"""InvenTree (inventory management) tools. API: /api/ with token auth."""

from fastmcp import FastMCP

from . import config, policy
from .client import fmt, make_client, request_json

mcp = FastMCP(
    "inventree",
    instructions="Inventory (InvenTree): look up parts and stock, adjust stock levels.")
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


policy.register_executor("inventree", "inventree_create_part", _do_create_part)
policy.register_executor("inventree", "inventree_adjust_stock", _do_adjust_stock)


@mcp.tool
def inventree_create_part(name: str, description: str,
                          category_id: int | None = None) -> str:
    """WRITE ACTION — creates a new part in the inventory system. Only call
    when the user asked for it. The user is notified with a summary."""
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
    approval before executing. Always include notes explaining why."""
    if action not in ("add", "remove", "count"):
        return "ERROR: action must be one of add, remove, count."
    return policy.apply_policy(
        domain="inventree", tool="inventree_adjust_stock", action_kind="effect",
        summary=(f"Stock {action}: item {stock_item_id}, quantity {quantity}"
                 + (f" — {notes}" if notes else "")),
        params={"stock_item_id": stock_item_id, "quantity": quantity,
                "action": action, "notes": notes},
        changes=[f"{action} {quantity} on stock item {stock_item_id}"])
