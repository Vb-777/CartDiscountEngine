"""Request/response contracts for the coupon discount API.

All monetary amounts are whole yen (int). Item prices are tax-inclusive,
per Minami's confirmation (see docs/decisions.md, R1).
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class CartLine(BaseModel):
    """One line of the trusted cart snapshot."""

    product_code: str = Field(min_length=1)
    category: str = Field(min_length=1, description="e.g. BOOK, APPAREL")
    unit_price: int = Field(ge=0, description="Tax-inclusive price per unit, whole yen")
    quantity: int = Field(ge=1)

    @property
    def line_total(self) -> int:
        return self.unit_price * self.quantity


class DiscountRequest(BaseModel):
    lines: list[CartLine] = Field(min_length=1)
    coupon_codes: list[str] = Field(default_factory=list)
    shipping_fee: int = Field(
        default=0,
        ge=0,
        description="Carried through untouched; never part of eligible-item totals (R1).",
    )


class CouponAllocation(BaseModel):
    """How one coupon's discount was spread over the cart lines."""

    line_index: int
    product_code: str
    amount: int


class CouponResult(BaseModel):
    """Per-coupon outcome — the explainability payload."""

    code: str
    applied: bool
    kind: str | None = None
    discount: int = 0
    eligible_amount: int | None = Field(
        default=None, description="Pre-discount total of this coupon's eligible items"
    )
    raw_discount: int | None = Field(
        default=None, description="Discount before cap/remaining clamp"
    )
    cap: int | None = None
    reason: str | None = Field(
        default=None, description="Why the coupon was not applied, or was reduced"
    )
    allocations: list[CouponAllocation] = Field(default_factory=list)


class LineResult(BaseModel):
    line_index: int
    product_code: str
    category: str
    line_total: int
    discount: int
    payable: int
    by_coupon: dict[str, int] = Field(default_factory=dict)


class DiscountResponse(BaseModel):
    items_subtotal: int
    shipping_fee: int
    total_discount: int
    payable_total: int = Field(description="items_subtotal - total_discount + shipping_fee")
    applied_coupon_codes: list[str]
    coupons: list[CouponResult]
    lines: list[LineResult]
