"""Outline (knowledge base / wiki) tools. API: https://www.getoutline.com/developers"""

from fastmcp import FastMCP

from . import config, policy
from .client import fmt, make_client, request_json

mcp = FastMCP("outline")
required_env = "OUTLINE_API_TOKEN"

_client = make_client(config.OUTLINE_URL,
                      headers={"Authorization": f"Bearer {config.OUTLINE_API_TOKEN}"})


def _post(path: str, payload: dict):
    return request_json(_client, "POST", path, service="Outline",
                        token_hint="OUTLINE_API_TOKEN", json=payload)


@mcp.tool
def outline_search_documents(query: str, max_results: int = 5) -> str:
    """Search the Outline wiki for documents matching a query. Returns titles,
    document ids, and matching context snippets."""
    ok, data = _post("/api/documents.search", {"query": query,
                                               "limit": max(1, min(max_results, 20))})
    if not ok:
        return data
    items = data.get("data", [])
    if not items:
        return f"No wiki documents match: {query}"
    lines = []
    for item in items:
        doc = item.get("document", {})
        ctx = (item.get("context") or "").replace("\n", " ")[:200]
        lines.append(f"- {doc.get('title')} (id: {doc.get('id')})\n  {ctx}")
    return "\n".join(lines)


@mcp.tool
def outline_get_document(document_id: str) -> str:
    """Read a wiki document by id. Returns its title and full markdown text."""
    ok, data = _post("/api/documents.info", {"id": document_id})
    if not ok:
        return data
    doc = data.get("data", {})
    return f"# {doc.get('title')}\n(id: {doc.get('id')}, updated: {doc.get('updatedAt')})\n\n{doc.get('text', '')}"


@mcp.tool
def outline_list_collections() -> str:
    """List the wiki's collections (top-level document groupings) with their ids."""
    ok, data = _post("/api/collections.list", {"limit": 50})
    if not ok:
        return data
    cols = data.get("data", [])
    if not cols:
        return "No collections found."
    return "\n".join(f"- {c.get('name')} (id: {c.get('id')})" for c in cols)


# ── Writes ─────────────────────────────────────────────────────────────────────

def _do_create_document(params: dict) -> str:
    ok, data = _post("/api/documents.create", {
        "collectionId": params["collection_id"], "title": params["title"],
        "text": params["text"], "publish": params.get("publish", True)})
    if not ok:
        return data
    doc = data.get("data", {})
    return (f"OBJECT_ID={doc.get('id')}\n"
            f"Created wiki document '{doc.get('title')}' (id: {doc.get('id')}).")


def _do_update_document(params: dict) -> str:
    payload = {"id": params["document_id"]}
    if params.get("title") is not None:
        payload["title"] = params["title"]
    if params.get("text") is not None:
        payload["text"] = params["text"]
        payload["append"] = bool(params.get("append", False))
    ok, data = _post("/api/documents.update", payload)
    if not ok:
        return data
    doc = data.get("data", {})
    return f"Updated wiki document '{doc.get('title')}' (id: {doc.get('id')})."


policy.register_executor("outline", "outline_create_document", _do_create_document)
policy.register_executor("outline", "outline_update_document", _do_update_document)


@mcp.tool
def outline_create_document(collection_id: str, title: str, text: str,
                            publish: bool = True) -> str:
    """WRITE ACTION — creates a new wiki document. Only call when the user asked
    for content to be written. The user is notified with a summary."""
    return policy.apply_policy(
        domain="outline", tool="outline_create_document", action_kind="create",
        summary=f"Create wiki document '{title}' in collection {collection_id}",
        params={"collection_id": collection_id, "title": title, "text": text,
                "publish": publish},
        changes=[f"New document '{title}' ({len(text)} chars)"],
        created_object_id_from_result=True)


@mcp.tool
def outline_update_document(document_id: str, changes_summary: list[str],
                            title: str | None = None, text: str | None = None,
                            append: bool = False) -> str:
    """WRITE ACTION — modifies an existing wiki document. changes_summary must
    itemize every intended change (e.g. ["add Q3 pricing table", "fix SMTP
    host"]). Overwrites of user-authored documents are held for the user's
    approval with a diff; use append=True to add to the end instead of
    replacing the text."""
    ok, data = _post("/api/documents.info", {"id": document_id})
    if not ok:
        return data
    current = data.get("data", {})
    proposed = ((current.get("text") or "") + "\n" + text) if (append and text) \
        else (text if text is not None else current.get("text") or "")
    diff = policy.make_diff(current.get("text") or "", proposed,
                            current.get("title") or document_id)
    return policy.apply_policy(
        domain="outline", tool="outline_update_document", action_kind="update",
        target_id=document_id,
        summary=f"Update wiki document '{current.get('title')}' (id: {document_id})",
        params={"document_id": document_id, "title": title, "text": text,
                "append": append},
        changes=list(changes_summary), diff=diff)
