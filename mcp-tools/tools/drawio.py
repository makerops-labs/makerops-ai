"""draw.io tools. The service is stateless, so the tool generates diagram XML
links: the XML is validated, deflate+base64 encoded, and returned as an edit
URL. A copy of the .drawio file is kept under /data for retrieval."""

import base64
import re
import time
import zlib
import xml.etree.ElementTree as ET
from urllib.parse import quote

from fastmcp import FastMCP

from . import config

mcp = FastMCP("drawio")
required_env = None  # stateless, no token

_DIAGRAMS_DIR = config.DATA_DIR / "diagrams"


@mcp.tool
def drawio_create_diagram_link(xml: str, title: str = "diagram") -> str:
    """Turn draw.io diagram XML (an <mxfile> or <mxGraphModel> document) into a
    link that opens the diagram in the local draw.io editor. Also saves a
    .drawio file under the tool server's data directory. Use this to present
    flowcharts, architecture diagrams, or org charts you have designed."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        return f"ERROR: the diagram XML does not parse: {exc}"
    if root.tag not in ("mxfile", "mxGraphModel"):
        return ("ERROR: root element must be <mxfile> or <mxGraphModel>, "
                f"got <{root.tag}>.")

    # draw.io URL fragment: urlencode(base64(rawdeflate(xml)))
    deflater = zlib.compressobj(9, zlib.DEFLATED, -15)
    compressed = deflater.compress(xml.encode("utf-8")) + deflater.flush()
    encoded = quote(base64.b64encode(compressed).decode("ascii"), safe="")

    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "-", title).strip("-") or "diagram"
    filename = f"{safe_title}-{int(time.time())}.drawio"
    try:
        _DIAGRAMS_DIR.mkdir(parents=True, exist_ok=True)
        (_DIAGRAMS_DIR / filename).write_text(xml)
        saved = f"\nSaved as {filename} in the mcp-tools data directory."
    except OSError:
        saved = ""

    return (f"Diagram '{title}' ready.\n"
            f"Open in editor: {config.DRAWIO_PUBLIC_URL}/#R{encoded}{saved}")
