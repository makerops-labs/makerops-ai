"""Web domain: internet search via the local SearXNG instance and a
content-type-aware URL fetcher that can review (not execute) any file type.
"""

import tempfile
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastmcp import FastMCP

from . import config
from .client import DEFAULT_TIMEOUT

mcp = FastMCP(
    "web",
    instructions="Private web search (SearXNG) and content-type-aware page/document fetching.")
required_env = None  # always mounted

_TEXT_TYPES = ("application/json", "application/xml", "application/javascript",
               "application/x-yaml", "application/toml", "application/csv")
_DOC_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/epub+zip": ".epub",
    "application/msword": ".doc",
    "application/vnd.ms-excel": ".xls",
}


@mcp.tool
def web_search(query: str, category: str = "general", max_results: int = 5) -> str:
    """Search the internet (via the local SearXNG metasearch engine).
    Returns a list of results with title, URL, and snippet. Categories:
    general, news, it, science, images, files."""
    try:
        resp = httpx.get(f"{config.SEARXNG_URL}/search",
                         params={"q": query, "format": "json",
                                 "categories": category},
                         timeout=DEFAULT_TIMEOUT)
    except httpx.ConnectError:
        return ("ERROR: connection to SearXNG refused — is searxng started? "
                f"(tried {config.SEARXNG_URL})")
    except httpx.HTTPError as exc:
        return f"ERROR: search request failed: {exc}"
    if resp.status_code == 403:
        return ("ERROR: SearXNG returned 403 — the json format is not enabled in "
                "its settings.yml (search.formats must include json).")
    if resp.status_code >= 400:
        return f"ERROR: SearXNG returned {resp.status_code}."

    results = resp.json().get("results", [])[:max(1, min(max_results, 20))]
    if not results:
        return f"No results for: {query}"
    lines = []
    for i, r in enumerate(results, 1):
        snippet = (r.get("content") or "").strip()
        lines.append(f"{i}. {r.get('title', '(untitled)')}\n   {r.get('url', '')}"
                     + (f"\n   {snippet}" if snippet else ""))
    return "\n".join(lines)


def _detect_kind(content_type: str, url_path: str, head: bytes) -> tuple[str, str]:
    """Return (kind, extension) where kind ∈ html|text|document|image|binary."""
    ct = (content_type or "").split(";")[0].strip().lower()
    suffix = Path(urlparse(url_path).path).suffix.lower()

    # Never execute — flag executables by magic bytes regardless of headers.
    if head[:4] == b"\x7fELF" or head[:2] == b"MZ":
        return "binary", suffix or ".bin"
    if ct in ("text/html", "application/xhtml+xml") or head.lstrip()[:5].lower() in (b"<!doc", b"<html"):
        return "html", ".html"
    if ct in _DOC_EXTENSIONS:
        return "document", _DOC_EXTENSIONS[ct]
    if head[:4] == b"%PDF":
        return "document", ".pdf"
    if suffix in (".pdf", ".docx", ".xlsx", ".pptx", ".epub", ".doc", ".xls"):
        return "document", suffix
    if ct.startswith("image/"):
        return "image", suffix or "." + ct.split("/")[1]
    if ct.startswith("text/") or ct in _TEXT_TYPES or ct.endswith("+json") or ct.endswith("+xml"):
        return "text", suffix or ".txt"
    # Heuristic: mostly printable bytes → treat as text.
    sample = head[:1024]
    if sample and sum(b in (9, 10, 13) or 32 <= b < 127 for b in sample) / len(sample) > 0.9:
        return "text", suffix or ".txt"
    return "binary", suffix or ".bin"


def _html_to_markdown(html: str) -> str:
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return markdownify(str(soup), heading_style="ATX", strip=["img"])


@mcp.tool
def fetch_url(url: str, max_chars: int = 8000) -> str:
    """Fetch a URL and return its content as reviewable text. Handles web pages
    (converted to markdown), JSON/XML/CSV/source code (as-is), and documents
    like PDF/docx/xlsx/pptx (text extracted). Images and executables are never
    rendered or run — only their metadata is reported."""
    try:
        with httpx.stream("GET", url, timeout=httpx.Timeout(30.0, connect=10.0),
                          follow_redirects=True,
                          headers={"User-Agent": "makerops-mcp-tools/0.1"}) as resp:
            if resp.status_code >= 400:
                return f"ERROR: {url} returned HTTP {resp.status_code}."
            content_type = resp.headers.get("content-type", "")
            declared_len = resp.headers.get("content-length")
            chunks, total = [], 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > config.FETCH_MAX_DOWNLOAD_BYTES:
                    return (f"ERROR: download exceeds the "
                            f"{config.FETCH_MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB "
                            f"limit (declared size: {declared_len or 'unknown'}).")
                chunks.append(chunk)
            body = b"".join(chunks)
    except httpx.ConnectError as exc:
        return f"ERROR: could not connect to {url}: {exc}"
    except httpx.HTTPError as exc:
        return f"ERROR: fetching {url} failed: {exc}"

    kind, ext = _detect_kind(content_type, url, body[:4096])
    note = ""

    if kind == "html":
        text = _html_to_markdown(body.decode(resp.encoding or "utf-8", errors="replace"))
    elif kind == "text":
        text = body.decode(resp.encoding or "utf-8", errors="replace")
    elif kind == "document":
        text, note = _extract_document(body, ext)
    elif kind == "image":
        return _image_metadata(url, body, content_type)
    else:
        is_exe = body[:4] == b"\x7fELF" or body[:2] == b"MZ"
        return (f"BINARY FILE (not reviewed as text, never executed): {url}\n"
                f"- declared type: {content_type or 'unknown'}\n"
                f"- detected: {'executable' if is_exe else 'unknown binary'}\n"
                f"- size: {len(body)} bytes")

    if text.startswith("ERROR:"):
        return text
    text = "\n".join(line.rstrip() for line in text.splitlines())
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... [truncated at {max_chars} chars; re-fetch with a larger max_chars for more]"
    return (note + text) if note else text


def _extract_document(body: bytes, ext: str) -> tuple[str, str]:
    from markitdown import MarkItDown

    with tempfile.NamedTemporaryFile(suffix=ext, dir=str(config.DATA_DIR),
                                     delete=True) as tmp:
        tmp.write(body)
        tmp.flush()
        try:
            result = MarkItDown().convert(tmp.name)
        except Exception as exc:
            return f"ERROR: could not extract text from {ext} document: {exc}", ""
    return result.text_content or "(document contained no extractable text)", \
        f"[extracted from {ext} document, {len(body)} bytes]\n\n"


def _image_metadata(url: str, body: bytes, content_type: str) -> str:
    dims = "unknown"
    try:
        import io

        from PIL import Image
        with Image.open(io.BytesIO(body)) as img:
            dims = f"{img.width}x{img.height} ({img.format})"
    except Exception:
        pass
    return (f"IMAGE FILE (metadata only, content not analyzed): {url}\n"
            f"- type: {content_type or 'unknown'}\n"
            f"- dimensions: {dims}\n"
            f"- size: {len(body)} bytes")
