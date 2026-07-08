"""Outline (knowledge base / wiki) tools. API: https://www.getoutline.com/developers"""

from fastmcp import FastMCP

from . import config, policy
from .client import fmt, make_client, request_json

mcp = FastMCP(
    "outline",
    instructions="Company wiki (Outline): search, read, create, and update documents.")
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
    """Read a wiki document by id. Returns its title, collection/parent
    location, and full markdown text."""
    ok, data = _post("/api/documents.info", {"id": document_id})
    if not ok:
        return data
    doc = data.get("data", {})
    return (f"# {doc.get('title')}\n(id: {doc.get('id')}, "
            f"collection: {doc.get('collectionId')}, "
            f"parent: {doc.get('parentDocumentId') or '(top-level)'}, "
            f"updated: {doc.get('updatedAt')})\n\n{doc.get('text', '')}")


@mcp.tool
def outline_list_documents(collection_id: str, parent_document_id: str = "") -> str:
    """List documents one level of a collection's hierarchy: pass
    parent_document_id="" for the top level, or a document id to list its
    direct children. Use this to find where a new document should nest
    before creating it, or to check existing structure."""
    payload = {"collectionId": collection_id}
    payload["parentDocumentId"] = parent_document_id or None
    ok, data = _post("/api/documents.list", payload)
    if not ok:
        return data
    docs = data.get("data", [])
    if not docs:
        level = "top level" if not parent_document_id else f"children of {parent_document_id}"
        return f"No documents at the {level} of collection {collection_id}."
    return "\n".join(f"- {d.get('title')} (id: {d.get('id')})" for d in docs)


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
    payload = {"collectionId": params["collection_id"], "title": params["title"],
              "text": params["text"], "publish": params.get("publish", True)}
    if params.get("parent_document_id"):
        payload["parentDocumentId"] = params["parent_document_id"]
    ok, data = _post("/api/documents.create", payload)
    if not ok:
        return data
    doc = data.get("data", {})
    return (f"OBJECT_ID={doc.get('id')}\n"
            f"Created wiki document '{doc.get('title')}' (id: {doc.get('id')}): "
            f"{config.OUTLINE_PUBLIC_URL}{doc.get('url', '')}")


def _do_create_collection(params: dict) -> str:
    ok, data = _post("/api/collections.create", {
        "name": params["name"], "description": params.get("description", "")})
    if not ok:
        return data
    col = data.get("data", {})
    return (f"OBJECT_ID={col.get('id')}\n"
            f"Created collection '{col.get('name')}' (id: {col.get('id')}): "
            f"{config.OUTLINE_PUBLIC_URL}{col.get('url', '')}")


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
    return (f"Updated wiki document '{doc.get('title')}' (id: {doc.get('id')}): "
            f"{config.OUTLINE_PUBLIC_URL}{doc.get('url', '')}")


policy.register_executor("outline", "outline_create_document", _do_create_document)
policy.register_executor("outline", "outline_update_document", _do_update_document)
policy.register_executor("outline", "outline_create_collection", _do_create_collection)


@mcp.tool
def outline_create_document(collection_id: str, title: str, text: str,
                            publish: bool = True,
                            parent_document_id: str = "") -> str:
    """WRITE ACTION — creates a new wiki document. parent_document_id: nest
    this document under an existing one instead of placing it at the top
    level of the collection — check outline_list_documents first to find
    the right parent or confirm one doesn't already exist. Only call when
    the user asked for content to be written. The user is notified with a
    summary."""
    return policy.apply_policy(
        domain="outline", tool="outline_create_document", action_kind="create",
        summary=f"Create wiki document '{title}' in collection {collection_id}",
        params={"collection_id": collection_id, "title": title, "text": text,
                "publish": publish, "parent_document_id": parent_document_id},
        changes=[f"New document '{title}' ({len(text)} chars)"],
        created_object_id_from_result=True)


@mcp.tool
def outline_create_collection(name: str, description: str = "") -> str:
    """WRITE ACTION — creates a new top-level wiki collection. Check
    outline_list_collections first to confirm one doesn't already exist
    under a similar name. The user is notified with a summary."""
    return policy.apply_policy(
        domain="outline", tool="outline_create_collection", action_kind="create",
        summary=f"Create wiki collection '{name}'",
        params={"name": name, "description": description},
        changes=[f"New collection '{name}'"],
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
