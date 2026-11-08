"""HTTP-level tests: validation and the response contract."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

SAMPLE = {
    "lines": [
        {"product_code": "B1", "category": "BOOK", "unit_price": 1200, "quantity": 2},
        {"product_code": "B2", "category": "BOOK", "unit_price": 333, "quantity": 1},
        {"product_code": "A1", "category": "APPAREL", "unit_price": 5000, "quantity": 1},
    ],
    "coupon_codes": ["SAVE20", "SAVE10"],
    "shipping_fee": 550,
}


def test_discounts_endpoint_returns_the_full_breakdown():
    resp = client.post("/discounts", json=SAMPLE)
    assert resp.status_code == 200
    body = resp.json()

    assert body["items_subtotal"] == 7733
    assert body["applied_coupon_codes"] == ["SAVE10", "SAVE20"]
    assert body["total_discount"] == 273 + 1000  # SAVE20 capped at 1,000
    assert body["payable_total"] == 7733 - 1273 + 550

    per_coupon = {c["code"]: c for c in body["coupons"]}
    assert per_coupon["SAVE20"]["raw_discount"] == 1000  # 20% of 5,000, at the cap
    assert per_coupon["SAVE10"]["eligible_amount"] == 2733
    assert sum(ln["discount"] for ln in body["lines"]) == body["total_discount"]


def test_coupons_endpoint_exposes_the_catalogue():
    body = client.get("/coupons").json()
    assert body["max_combined_coupons"] == 3
    assert [c["code"] for c in body["coupons"]] == [
        "VIP30",
        "SAVE10",
        "SAVE20",
        "OFF1000",
        "OFF500",
    ]


def test_empty_cart_is_rejected():
    assert client.post("/discounts", json={"lines": [], "coupon_codes": []}).status_code == 422


def test_negative_price_is_rejected():
    bad = {
        "lines": [
            {"product_code": "B1", "category": "BOOK", "unit_price": -1, "quantity": 1}
        ],
        "coupon_codes": [],
    }
    assert client.post("/discounts", json=bad).status_code == 422


def test_zero_quantity_is_rejected():
    bad = {
        "lines": [
            {"product_code": "B1", "category": "BOOK", "unit_price": 100, "quantity": 0}
        ],
        "coupon_codes": [],
    }
    assert client.post("/discounts", json=bad).status_code == 422
