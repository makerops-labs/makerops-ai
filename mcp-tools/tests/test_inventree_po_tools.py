"""BOM shortfall + purchase-order tools (InvenTree API faked in-process)."""

import pytest

from tools import inventree as inv
from tools import policy


def fn(tool):
    return getattr(tool, "fn", tool)


class FakeInvenTree:
    """Routes _req(method, path, ...) to canned data and records every call."""

    def __init__(self):
        self.calls = []
        self.parts = {
            10: {"pk": 10, "unallocated_stock": 25},   # shell: enough
            11: {"pk": 11, "unallocated_stock": 8},    # lid: short
            12: {"pk": 12, "unallocated_stock": 50},   # screw: short at 4/each
        }
        self.bom = [
            {"pk": 1, "part": 1, "sub_part": 10, "quantity": 1, "sub_part_detail": {"name": "Shell"}},
            {"pk": 2, "part": 1, "sub_part": 11, "quantity": 1, "sub_part_detail": {"name": "Lid"}},
            {"pk": 3, "part": 1, "sub_part": 12, "quantity": 4, "sub_part_detail": {"name": "Screw"}},
            {"pk": 9, "part": 99, "sub_part": 10, "quantity": 7},  # other assembly: must be ignored
        ]
        self.supplier_parts = [
            {"pk": 101, "part": 11, "supplier": 5, "SKU": "LID-1"},
            {"pk": 102, "part": 12, "supplier": 5, "SKU": "M3-8"},
        ]
        self.pos = [{"pk": 6, "reference": "PO-0006"}, {"pk": 3, "reference": "LEGACY-17"}]

    def __call__(self, method, path, params=None, json=None, **_):
        self.calls.append((method, path, params, json))
        if method == "GET" and path == "/api/bom/":
            return True, self.bom  # ignores filters, like the real API sometimes does
        if method == "GET" and path.startswith("/api/part/"):
            return True, self.parts[int(path.strip("/").split("/")[-1])]
        if method == "GET" and path == "/api/company/part/":
            sp = self.supplier_parts
            if params and "part" in params:
                sp = [s for s in sp if s["part"] == params["part"]]
            return True, sp
        if method == "GET" and path == "/api/order/po/":
            return True, self.pos
        if method == "GET" and path.startswith("/api/order/po/"):
            return True, {"pk": 7, "reference": "PO-0007", "line_items": 2,
                          "status_text": "Pending", "supplier_detail": {"name": "Acme"}}
        if method == "POST" and path == "/api/order/po/":
            return True, {"pk": 7, **json}
        if method == "POST" and path == "/api/order/po-line/":
            return True, {"pk": 70, **json}
        if method == "POST" and path.endswith("/issue/"):
            return True, {}
        raise AssertionError(f"unexpected call {method} {path}")

    def posts(self):
        return [(p, j) for m, p, _, j in self.calls if m == "POST"]


@pytest.fixture
def api(monkeypatch):
    fake = FakeInvenTree()
    monkeypatch.setattr(inv, "_req", fake)
    return fake


# ── inventree_get_bom ────────────────────────────────────────────────────────

def test_bom_reports_shortfall_and_suppliers(api):
    out = fn(inv.inventree_get_bom)(part_id=1, build_quantity=20)
    assert out.startswith("BOM for part 1, building 20: 3 components, 2 short.")
    lines = out.splitlines()[1:]
    assert "need 20, available 25 — ok" in lines[0]
    assert "need 20, available 8 — SHORT 12; suppliers: supplier 5 SKU LID-1" in lines[1]
    assert "need 80, available 50 — SHORT 30; suppliers: supplier 5 SKU M3-8" in lines[2]


def test_bom_ignores_lines_of_other_assemblies(api):
    # The fake returns a line for part 99 even when asked for part 1.
    assert "7 per assembly" not in fn(inv.inventree_get_bom)(part_id=1, build_quantity=1)


def test_bom_rejects_non_positive_quantity(api):
    assert fn(inv.inventree_get_bom)(part_id=1, build_quantity=0).startswith("ERROR")
    assert api.calls == []


def test_bom_is_read_only(api):
    fn(inv.inventree_get_bom)(part_id=1, build_quantity=20)
    assert api.posts() == []


# ── inventree_create_purchase_order (notify tier) ────────────────────────────

def test_create_po_executes_immediately_with_next_reference(api):
    out = fn(inv.inventree_create_purchase_order)(
        supplier_id=5, lines=[{"part_id": 11, "quantity": 12}, {"part_id": 12, "quantity": 30}])
    assert "Created purchase order PO-0007" in out and "status Pending" in out
    posts = api.posts()
    assert posts[0] == ("/api/order/po/", {"supplier": 5, "reference": "PO-0007", "description": ""})
    assert [j["part"] for p, j in posts[1:]] == [101, 102]  # supplier-part ids, not part ids
    assert [j["quantity"] for p, j in posts[1:]] == [12.0, 30.0]
    assert policy.is_agent_owned("inventree", "7")


def test_create_po_validates_before_creating_anything(api):
    out = fn(inv.inventree_create_purchase_order)(
        supplier_id=5, lines=[{"part_id": 11, "quantity": 1}, {"part_id": 10, "quantity": 1}])
    assert out.startswith("ERROR: supplier 5 has no supplier part for part id(s) [10]")
    assert api.posts() == []


@pytest.mark.parametrize("delete_ok", [True, False])
def test_failed_line_rolls_back_the_draft(api, monkeypatch, delete_ok):
    real = api.__call__

    def flaky(method, path, params=None, json=None, **kw):
        if method == "POST" and path == "/api/order/po-line/" and json["part"] == 102:
            api.calls.append((method, path, params, json))
            return False, "ERROR: InvenTree rejected the line"
        if method == "DELETE":
            api.calls.append((method, path, params, json))
            return delete_ok, None
        return real(method, path, params=params, json=json, **kw)

    monkeypatch.setattr(inv, "_req", flaky)
    out = fn(inv.inventree_create_purchase_order)(
        supplier_id=5, lines=[{"part_id": 11, "quantity": 12}, {"part_id": 12, "quantity": 30}])
    assert out.startswith("ERROR: adding a line for part 12 to PO-0007 failed")
    assert ("DELETE", "/api/order/po/7/", None, None) in api.calls
    assert ("rolled back" in out) if delete_ok else ("rollback FAILED" in out and "id 7" in out)
    assert not policy.is_agent_owned("inventree", "7")


@pytest.mark.parametrize("lines", [[], [{"part_id": 11, "quantity": 0}],
                                   [{"part_id": 11}], [{"part": 11, "quantity": 1}], ["x"]])
def test_create_po_rejects_malformed_lines(api, lines):
    assert fn(inv.inventree_create_purchase_order)(supplier_id=5, lines=lines).startswith("ERROR")
    assert api.posts() == []


def test_po_reference_starts_at_one_when_none_exist(api):
    api.pos = [{"pk": 1, "reference": "something-else"}]
    assert inv._next_po_reference() == (True, "PO-0001")


# ── inventree_issue_purchase_order (gated) ───────────────────────────────────

def test_issue_po_is_held_until_approved(api):
    out = fn(inv.inventree_issue_purchase_order)(order_id=7)
    assert out.startswith("PENDING APPROVAL #")
    assert "Place purchase order PO-0007 with Acme" in out
    assert not any(p.endswith("/issue/") for p, _ in api.posts())

    action_id = out.split("#", 1)[1].split(":", 1)[0]
    assert policy.resolve_action(action_id, approve=True)[0]
    assert [p for p, _ in api.posts()] == ["/api/order/po/7/issue/"]


def test_rejected_issue_never_places_the_order(api):
    out = fn(inv.inventree_issue_purchase_order)(order_id=7)
    action_id = out.split("#", 1)[1].split(":", 1)[0]
    policy.resolve_action(action_id, approve=False)
    assert api.posts() == []
