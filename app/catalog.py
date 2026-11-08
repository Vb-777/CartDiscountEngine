"""Declarative coupon catalogue.

Everything Marketing can change lives here; app/engine.py never names a
coupon. Adding a campaign is one row in COUPONS.

Field semantics (all confirmed with Minami, 2026-11-07 -- see docs/decisions.md):
  stage          Order coupons are *considered* in during selection (R2).
                 1 = VIP30, 2 = SAVE10/SAVE20, 3 = OFF500/OFF1000.
                 Because stages 1-2 are percentage and stage 3 is fixed-amount,
                 this single key also yields the required calculation order
                 (percentage before fixed-amount).
  categories     None means "any category"; otherwise the item categories this
                 coupon is eligible for.
  product_codes  None means "any product code"; otherwise the exact product
                 codes this coupon is eligible for (R5: OFF500 is scoped this
                 way, not by category).
  min_spend      Checked against the PRE-DISCOUNT, tax-inclusive total of this
                 coupon's eligible items only -- not the whole cart, and never
                 including shipping (R1).
  cap            Applied AFTER the fractional yen is dropped (R4).
  exclusive      Cannot be combined; if eligible, it is the only coupon used (R2).

A coupon with both `categories` and `product_codes` set as None applies to
every item in the cart. There are no blanket item exclusions (R8).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Protocol

STAGE_EXCLUSIVE = 1
STAGE_PERCENTAGE = 2
STAGE_FIXED = 3

CouponKind = Literal["percentage", "fixed"]

PERCENTAGE: Final[CouponKind] = "percentage"
FIXED: Final[CouponKind] = "fixed"


class _Item(Protocol):
    """Minimal shape a coupon needs to judge eligibility."""

    product_code: str
    category: str


@dataclass(frozen=True)
class Coupon:
    code: str
    kind: CouponKind
    stage: int
    percent: int | None = None
    amount: int | None = None
    cap: int | None = None
    categories: frozenset[str] | None = None
    product_codes: frozenset[str] | None = None
    min_spend: int = 0
    exclusive: bool = False

    def __post_init__(self) -> None:
        if self.kind == PERCENTAGE and self.percent is None:
            raise ValueError(f"{self.code}: percentage coupon needs `percent`")
        if self.kind == FIXED and self.amount is None:
            raise ValueError(f"{self.code}: fixed coupon needs `amount`")

    def matches(self, item: _Item) -> bool:
        """Is this cart item within the coupon's scope?

        Both filters must pass; an unset filter is unrestricted.
        """
        if self.categories is not None and item.category not in self.categories:
            return False
        return not (self.product_codes is not None and item.product_code not in self.product_codes)

    @property
    def scope_description(self) -> str:
        if self.product_codes is not None:
            return "product code " + "/".join(sorted(self.product_codes))
        if self.categories is not None:
            return "/".join(sorted(self.categories)) + " items"
        return "all items"


_DEFINITIONS = [
    # 30% off all items, capped at 3,000 yen, no minimum, never combined.
    Coupon(
        code="VIP30",
        kind=PERCENTAGE,
        stage=STAGE_EXCLUSIVE,
        percent=30,
        cap=3000,
        min_spend=0,
        exclusive=True,
    ),
    # 10% off BOOK items, no cap, no minimum.
    Coupon(
        code="SAVE10",
        kind=PERCENTAGE,
        stage=STAGE_PERCENTAGE,
        percent=10,
        categories=frozenset({"BOOK"}),
        min_spend=0,
    ),
    # 20% off APPAREL items, capped at 1,000 yen, 5,000 yen minimum.
    Coupon(
        code="SAVE20",
        kind=PERCENTAGE,
        stage=STAGE_PERCENTAGE,
        percent=20,
        cap=1000,
        categories=frozenset({"APPAREL"}),
        min_spend=5000,
    ),
    # 500 yen off, scoped by PRODUCT CODE (not category), 3,000 yen minimum.
    Coupon(
        code="OFF500",
        kind=FIXED,
        stage=STAGE_FIXED,
        amount=500,
        product_codes=frozenset({"GIFT-BOX"}),
        min_spend=3000,
    ),
    # 1,000 yen off HOME items, 8,000 yen minimum.
    Coupon(
        code="OFF1000",
        kind=FIXED,
        stage=STAGE_FIXED,
        amount=1000,
        categories=frozenset({"HOME"}),
        min_spend=8000,
    ),
]

COUPONS: dict[str, Coupon] = {c.code: c for c in _DEFINITIONS}

MAX_COMBINED_COUPONS = 3


def get_coupon(code: str) -> Coupon | None:
    return COUPONS.get(code)
