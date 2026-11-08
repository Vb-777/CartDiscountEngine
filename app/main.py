"""HTTP surface for the coupon discount API.

The endpoint is a thin wrapper: validation is handled by the schemas, all
business rules live in app/engine.py + app/catalog.py.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.catalog import COUPONS, MAX_COMBINED_COUPONS
from app.engine import calculate
from app.schemas import DiscountRequest, DiscountResponse

app = FastAPI(
    title="Coupon Discount API",
    version="1.0.0",
    description=(
        "Accepts a cart snapshot plus the coupon codes a shopper wants to use, "
        "and returns the discount with a per-coupon and per-line breakdown so "
        "the basis of every yen can be explained."
    ),
)


@app.post("/discounts", response_model=DiscountResponse)
def post_discounts(request: DiscountRequest) -> DiscountResponse:
    """Calculate the discount for a purchase.

    Ineligible or unselected coupons are reported with a reason rather than
    rejecting the whole request (see docs/decisions.md A4).
    """
    return calculate(request)


@app.get("/coupons")
def list_coupons() -> dict:
    """Expose the live catalogue, so Marketing can verify what the API believes."""
    return {
        "max_combined_coupons": MAX_COMBINED_COUPONS,
        "coupons": [
            {
                "code": c.code,
                "kind": c.kind,
                "percent": c.percent,
                "amount": c.amount,
                "cap": c.cap,
                "scope": c.scope_description,
                "categories": sorted(c.categories) if c.categories else None,
                "product_codes": sorted(c.product_codes) if c.product_codes else None,
                "min_spend": c.min_spend,
                "exclusive": c.exclusive,
                "consideration_stage": c.stage,
            }
            for c in sorted(COUPONS.values(), key=lambda c: (c.stage, c.code))
        ],
    }
