"""Shared test helpers."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.catalog import COUPONS, Coupon
from app.schemas import CartLine, DiscountRequest


def cart(*lines, coupons=(), shipping=0) -> DiscountRequest:
    """Build a request. Each line is (product_code, category, unit_price, qty)."""
    return DiscountRequest(
        lines=[
            CartLine(product_code=p, category=c, unit_price=u, quantity=q)
            for p, c, u, q in lines
        ],
        coupon_codes=list(coupons),
        shipping_fee=shipping,
    )


def by_code(response) -> dict:
    return {c.code: c for c in response.coupons}


def line_discounts(response) -> dict:
    return {ln.product_code: ln.discount for ln in response.lines}


@pytest.fixture
def synthetic_coupons() -> Iterator[None]:
    """Temporarily register coupons that exercise code paths the live
    catalogue cannot currently reach.

    With the five real coupons, no two overlap in scope except VIP30 (which is
    exclusive), so a coupon can never find its eligible items already
    discounted to zero. The clamping and zero-discount rules Minami confirmed
    (R6, R7) are still implemented, and these synthetic coupons prove it.
    """
    extra = [
        Coupon(code="ABIG", kind="fixed", stage=3, amount=100_000),
        Coupon(code="AZERO", kind="fixed", stage=3, amount=500),
    ]
    for coupon in extra:
        COUPONS[coupon.code] = coupon
    try:
        yield
    finally:
        for coupon in extra:
            COUPONS.pop(coupon.code, None)
