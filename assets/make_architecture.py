"""Generate assets/architecture.drawio and assets/architecture.svg from one spec.

Both files come from the same node and edge list, so the editable draw.io
source and the SVG that GitHub renders can't drift apart. After editing the
spec below, run from the repo root:

    python3 assets/make_architecture.py
"""

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent
W, H = 1180, 750

# Neutral boxes; the human approval point is the only warm colour.
COLORS = {
    "ui": ("#e8f0fe", "#4a6fb5"),
    "core": ("#eef7ee", "#3f8f4f"),
    "infra": ("#f3f3f3", "#777777"),
    "app": ("#fff8e6", "#b38600"),
    "human": ("#fde8e4", "#c0392b"),
    "group": ("#ffffff", "#9aa5b1"),
}

# id: (x, y, w, h, kind, title, subtitle; "\n" splits subtitle lines)
GROUPS = {
    "g_mcp": (420, 170, 360, 400, "group", "mcp-tools :8099", "one MCP endpoint per domain"),
    "g_apps": (850, 170, 300, 400, "group", "Business apps", "makerops-core, self-hosted"),
}
NODES = {
    "you": (30, 420, 150, 70, "human", "You", "chat + approve"),
    "owui": (230, 190, 160, 70, "ui", "Open WebUI :8080", "chat presets"),
    "smol": (230, 300, 160, 80, "ui", "smolagents :8090", "agents + job queue"),
    "tools": (440, 225, 320, 64, "core", "Tool domains", "inventree, freescout, outline, plane, n8n, web ..."),
    "policy": (440, 320, 320, 66, "core", "Write policy", "read: run | additive: run + notify | delete/effect: hold"),
    "approvals": (440, 420, 320, 70, "human", "/approvals  (human gate)", "PENDING APPROVAL #id: approve or reject"),
    "audit": (440, 515, 320, 36, "infra", "Audit log + approval expiry", ""),
    "inventree": (870, 225, 260, 52, "app", "InvenTree", "parts, stock, BOMs, purchase orders"),
    "freescout": (870, 290, 260, 52, "app", "FreeScout", "customer email, draft replies"),
    "outline": (870, 355, 260, 52, "app", "Outline / Plane", "docs, projects"),
    "n8n": (870, 420, 260, 52, "app", "n8n / trigger.dev", "workflows, scheduled jobs"),
    "comfy": (870, 485, 260, 52, "app", "ComfyUI", "image generation"),
    "searx": (565, 70, 150, 60, "infra", "SearXNG :8098", "private web search"),
    "sandbox": (735, 70, 170, 60, "infra", "sandbox", "ephemeral command runner"),
    "ollama": (230, 610, 160, 70, "infra", "Ollama :11434", "local models for both UIs"),
    "redeploy": (870, 610, 280, 70, "core", "redeploy", "write file, restart, health check,\nrevert on failure"),
}
# (source, target, route points, label, label centre or None, highlighted)
EDGES = [
    ("you", "owui", [(105, 420), (105, 225), (230, 225)], "chat", (140, 216), False),
    ("you", "smol", [(105, 420), (105, 340), (230, 340)], "", None, False),
    ("owui", "tools", [(390, 245), (440, 245)], "MCP", (415, 236), False),
    ("smol", "tools", [(390, 330), (415, 330), (415, 270), (440, 270)], "", None, False),
    ("smol", "ollama", [(310, 380), (310, 610)], "inference", (345, 585), False),
    ("tools", "policy", [(600, 289), (600, 320)], "every write", (650, 305), False),
    ("policy", "approvals", [(600, 386), (600, 420)], "hold", (625, 404), True),
    ("you", "approvals", [(180, 455), (440, 455)], "approve / reject", (300, 446), True),
    ("tools", "searx", [(640, 225), (640, 130)], "search", (668, 155), False),
    ("tools", "sandbox", [(730, 225), (730, 165), (820, 165), (820, 130)], "run", (775, 156), False),
    ("tools", "g_apps", [(760, 250), (850, 250)], "reads", (805, 241), False),
    ("policy", "g_apps", [(760, 353), (850, 353)], "writes", (805, 344), False),
    ("approvals", "redeploy", [(760, 470), (815, 470), (815, 645), (870, 645)],
     "approved\ncode change", (815, 595), True),
]
FOOTNOTES = [
    "Red: the human approval point. Deletes, business effects (placing a PO, sending email) "
    "and code changes wait here; additive writes run and notify.",
    "Exception: the n8nmcp passthrough (n8n workflow authoring via the n8n-mcp service) skips the "
    "write policy by design; its destructive tools are disabled instead.",
]


def svg() -> str:
    font = "font-family='-apple-system,Segoe UI,Helvetica,Arial,sans-serif'"
    out = [f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 {W} {H}' width='{W}' height='{H}' {font}>",
           "<defs>"]
    for mid, col in (("a", "#555"), ("ah", "#c0392b")):
        out.append(f"<marker id='{mid}' viewBox='0 0 10 10' refX='9' refY='5' markerWidth='7' "
                   f"markerHeight='7' orient='auto'><path d='M0,0 L10,5 L0,10 z' fill='{col}'/></marker>")
    out += ["</defs>", f"<rect width='{W}' height='{H}' fill='#ffffff'/>",
            "<text x='30' y='40' font-size='22' font-weight='600' fill='#222'>"
            "MakerOps AI: agents act through one policy-checked tool server</text>"]
    for x, y, w, h, kind, title, sub in GROUPS.values():
        fill, stroke = COLORS[kind]
        out.append(f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='12' fill='{fill}' "
                   f"stroke='{stroke}' stroke-dasharray='6 4'/>")
        out.append(f"<text x='{x + 14}' y='{y + 24}' font-size='15' font-weight='600' fill='#333'>{escape(title)}</text>")
        out.append(f"<text x='{x + 14}' y='{y + 42}' font-size='11.5' fill='#666'>{escape(sub)}</text>")
    for _src, _dst, pts, label, lpos, hi in EDGES:
        col, mk, sw = ("#c0392b", "ah", 2.5) if hi else ("#555", "a", 1.4)
        d = " ".join(f"{x},{y}" for x, y in pts)
        out.append(f"<polyline points='{d}' fill='none' stroke='{col}' stroke-width='{sw}' marker-end='url(#{mk})'/>")
        if label and lpos:
            lines = label.split("\n")
            tw = 6.3 * max(map(len, lines)) + 8
            lx, ly = lpos
            out.append(f"<rect x='{lx - tw / 2:.0f}' y='{ly - 11}' width='{tw:.0f}' height='{15 * len(lines) + 3}' "
                       "rx='3' fill='#ffffff' opacity='0.95'/>")
            for i, ln in enumerate(lines):
                out.append(f"<text x='{lx}' y='{ly + 2 + 15 * i}' font-size='11' text-anchor='middle' "
                           f"fill='{col}'>{escape(ln)}</text>")
    for x, y, w, h, kind, title, sub in NODES.values():
        fill, stroke = COLORS[kind]
        sw = 2.5 if kind == "human" else 1.4
        out.append(f"<rect x='{x}' y='{y}' width='{w}' height='{h}' rx='8' fill='{fill}' stroke='{stroke}' stroke-width='{sw}'/>")
        lines = sub.split("\n") if sub else []
        ty = y + h / 2 + 5 - 8 * len(lines)
        out.append(f"<text x='{x + w / 2:.0f}' y='{ty:.0f}' font-size='14' font-weight='600' "
                   f"text-anchor='middle' fill='#222'>{escape(title)}</text>")
        for i, ln in enumerate(lines):
            out.append(f"<text x='{x + w / 2:.0f}' y='{ty + 17 + 15 * i:.0f}' font-size='11' "
                       f"text-anchor='middle' fill='#555'>{escape(ln)}</text>")
    for i, note in enumerate(FOOTNOTES):
        out.append(f"<text x='30' y='{H - 38 + 18 * i}' font-size='11.5' fill='#666'>{escape(note)}</text>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def drawio() -> str:
    cells = ["<mxCell id='0'/>", "<mxCell id='1' parent='0'/>"]
    for nid, (x, y, w, h, kind, title, sub) in {**GROUPS, **NODES}.items():
        fill, stroke = COLORS[kind]
        extra = "dashed=1;verticalAlign=top;align=left;spacingLeft=10;" if kind == "group" else ""
        width = 3 if kind == "human" else 1
        subhtml = "<br>".join(escape(s) for s in sub.split("\n")) if sub else ""
        html = f"<b>{escape(title)}</b>" + (f"<br><font style='font-size:11px'>{subhtml}</font>" if sub else "")
        style = f"rounded=1;whiteSpace=wrap;html=1;fillColor={fill};strokeColor={stroke};strokeWidth={width};{extra}"
        cells.append(f"<mxCell id='{nid}' value=\"{escape(html, quote=True)}\" style='{style}' vertex='1' parent='1'>"
                     f"<mxGeometry x='{x}' y='{y}' width='{w}' height='{h}' as='geometry'/></mxCell>")
    for i, (src, dst, pts, label, _lpos, hi) in enumerate(EDGES):
        col, width = ("#c0392b", 3) if hi else ("#555555", 1)
        style = f"endArrow=classic;html=1;rounded=0;strokeColor={col};strokeWidth={width};fontColor={col};"
        (sx, sy), (tx, ty) = pts[0], pts[-1]
        mids = "".join(f"<mxPoint x='{x}' y='{y}'/>" for x, y in pts[1:-1])
        geo = (f"<mxGeometry relative='1' as='geometry'><mxPoint x='{sx}' y='{sy}' as='sourcePoint'/>"
               f"<mxPoint x='{tx}' y='{ty}' as='targetPoint'/>"
               + (f"<Array as='points'>{mids}</Array>" if mids else "") + "</mxGeometry>")
        value = escape(label.replace("\n", " "), quote=True)
        cells.append(f"<mxCell id='e{i}' value=\"{value}\" style='{style}' edge='1' parent='1' "
                     f"source='{src}' target='{dst}'>{geo}</mxCell>")
    body = "\n        ".join(cells)
    return (f"<mxfile host='makerops' type='device'>\n  <diagram name='Architecture' id='architecture'>\n"
            f"    <mxGraphModel dx='{W}' dy='{H}' grid='1' gridSize='10' page='1' pageWidth='{W}' pageHeight='{H}'>\n"
            f"      <root>\n        {body}\n      </root>\n    </mxGraphModel>\n  </diagram>\n</mxfile>\n")


if __name__ == "__main__":
    (OUT / "architecture.svg").write_text(svg())
    (OUT / "architecture.drawio").write_text(drawio())
    print("wrote assets/architecture.svg and assets/architecture.drawio")
