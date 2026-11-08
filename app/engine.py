"""Discount calculation engine.

Pure function over a cart snapshot -- no I/O, no framework, no clock.

Pipeline (each step maps to a confirmed rule in docs/decisions.md):
  1. normalise  -- upper-case, de-duplicate submitted codes
  2. eligibility -- per coupon: eligible items exist AND their pre-discount
                    tax-inclusive total meets that coupon's minimum spend (R1)
  3. selection   -- exclusive coupon wins alone; otherwise the first
                    MAX_COMBINED_COUPONS in (stage, code) order (R2)
  4. application -- percentage coupons before fixed-amount (R2); each coupon's
                    amount is computed, capped, then clamped to the remaining
                    value of its eligible items
  5. allocation  -- spread over eligible lines in proportion to each line's
                    REMAINING amount, floor each share, hand out the leftover
                    yen one at a time in product-code order (R4)

Input order of coupon_codes never affects the result (R2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.catalog import MAX_COMBINED_COUPONS, PERCENTAGE, Coupon, get_coupon
from app.schemas import (
    CouponAllocation,
    CouponResult,
    DiscountRequest,
    DiscountResponse,
    LineResult,
)

# Reasons returned to the caller when a submitted coupon yields no discount.
REASON_UNKNOWN = "unknown_coupon"
REASON_NO_ELIGIBLE_ITEMS = "no_eligible_items"
REASON_MIN_SPEND = "minimum_spend_not_met"
REASON_NOT_SELECTED = "not_selected_combination_limit"
REASON_EXCLUSIVE = "excluded_by_exclusive_coupon"
REASON_NOTHING_LEFT = "no_remaining_amount"
REASON_CAPPED = "capped"
REASON_CLAMPED = "clamped_to_remaining_amount"


@dataclass
class _Line:
    """Mutable per-line state carried through the pipeline."""

    index: int
    product_code: str
    category: str
    line_total: int
    discount: int = 0
    by_coupon: dict[str, int] = field(default_factory=dict)

    @property
    def remaining(self) -> int:
        return self.line_total - self.discount


def _eligible(coupon: Coupon, lines: Sequence[_Line]) -> list[_Line]:
    """Lines this coupon can discount.

    Scope may be by category (SAVE10, SAVE20, OFF1000), by exact product code
    (OFF500), or unrestricted (VIP30). See Coupon.matches.
    """
    return [ln for ln in lines if coupon.matches(ln)]


def _percentage_amount(coupon: Coupon, pre_discount_total: int) -> tuple[int, int]:
    """Return (raw, capped).

    R4: the rate is applied to the total pre-discount amount of the eligible
    items and the fractional yen is DROPPED; only then is the cap applied.
    Integer floor division does the truncation exactly, with no float drift.
    """
    if coupon.percent is None:  # guarded by Coupon.__post_init__
        raise ValueError(f"{coupon.code}: percentage coupon without a rate")
    raw = pre_discount_total * coupon.percent // 100
    capped = min(raw, coupon.cap) if coupon.cap is not None else raw
    return raw, capped


def _allocate(amount: int, lines: Sequence[_Line]) -> dict[int, int]:
    """Split `amount` across `lines` in proportion to each line's remaining value.

    R4: floor every share, then distribute the leftover yen one at a time in
    product-code order (original cart order breaks ties between identical
    product codes). A line never receives more than it has remaining.
    """
    if amount <= 0:
        return {}

    total_remaining = sum(ln.remaining for ln in lines)
    if total_remaining <= 0:
        return {}

    shares: dict[int, int] = {
        ln.index: amount * ln.remaining // total_remaining for ln in lines
    }
    leftover = amount - sum(shares.values())

    order = sorted(lines, key=lambda ln: (ln.product_code, ln.index))
    while leftover > 0:
        progressed = False
        for ln in order:
            if leftover == 0:
                break
            if shares[ln.index] < ln.remaining:
                shares[ln.index] += 1
                leftover -= 1
                progressed = True
        if not progressed:  # every eligible line is fully discounted
            break

    return {index: share for index, share in shares.items() if share > 0}


def _normalise_codes(codes: Sequence[str]) -> list[str]:
    """Upper-case, trim, drop blanks, de-duplicate keeping first appearance."""
    seen = set()
    out: list[str] = []
    for raw in codes:
        code = raw.strip().upper()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _screen(
    codes: Sequence[str], lines: Sequence[_Line]
) -> tuple[list[Coupon], dict[str, CouponResult]]:
    """Step 2: eligibility. Returns candidates plus a result stub per code."""
    candidates: list[Coupon] = []
    results: dict[str, CouponResult] = {}

    for code in codes:
        coupon = get_coupon(code)
        if coupon is None:
            results[code] = CouponResult(code=code, applied=False, reason=REASON_UNKNOWN)
            continue

        eligible_lines = _eligible(coupon, lines)
        eligible_amount = sum(ln.line_total for ln in eligible_lines)

        if not eligible_lines:
            results[code] = CouponResult(
                code=code,
                applied=False,
                kind=coupon.kind,
                eligible_amount=0,
                cap=coupon.cap,
                reason=REASON_NO_ELIGIBLE_ITEMS,
            )
            continue

        if eligible_amount < coupon.min_spend:
            results[code] = CouponResult(
                code=code,
                applied=False,
                kind=coupon.kind,
                eligible_amount=eligible_amount,
                cap=coupon.cap,
                reason=f"{REASON_MIN_SPEND}(required={coupon.min_spend})",
            )
            continue

        candidates.append(coupon)
        results[code] = CouponResult(
            code=code,
            applied=False,
            kind=coupon.kind,
            eligible_amount=eligible_amount,
            cap=coupon.cap,
            reason=REASON_NOT_SELECTED,
        )

    return candidates, results


def _select(candidates: list[Coupon]) -> tuple[list[Coupon], Coupon | None]:
    """Step 3: selection.

    R2: only coupons that pass eligibility count toward the limit. An exclusive
    coupon, if eligible, is used alone. Otherwise the first
    MAX_COMBINED_COUPONS in consideration order (stage, then code
    alphabetically) are used.
    """
    ordered = sorted(candidates, key=lambda c: (c.stage, c.code))
    exclusive = next((c for c in ordered if c.exclusive), None)
    if exclusive is not None:
        return [exclusive], exclusive
    return ordered[:MAX_COMBINED_COUPONS], None


def calculate(request: DiscountRequest) -> DiscountResponse:
    """Apply the submitted coupons to the cart snapshot and explain the result."""
    lines = [
        _Line(
            index=i,
            product_code=raw.product_code,
            category=raw.category,
            line_total=raw.line_total,
        )
        for i, raw in enumerate(request.lines)
    ]
    items_subtotal = sum(ln.line_total for ln in lines)

    codes = _normalise_codes(request.coupon_codes)
    candidates, results = _screen(codes, lines)
    selected, exclusive = _select(candidates)
    selected_codes = {c.code for c in selected}

    # Unselected-but-eligible coupons: say which rule kept them out.
    for coupon in candidates:
        if coupon.code not in selected_codes:
            results[coupon.code].reason = (
                REASON_EXCLUSIVE if exclusive is not None else REASON_NOT_SELECTED
            )

    # Step 4/5: apply in (stage, code) order -- percentage before fixed-amount.
    for coupon in selected:
        eligible_lines = _eligible(coupon, lines)
        pre_discount_total = sum(ln.line_total for ln in eligible_lines)
        remaining_total = sum(ln.remaining for ln in eligible_lines)
        result = results[coupon.code]

        if coupon.kind == PERCENTAGE:
            raw, amount = _percentage_amount(coupon, pre_discount_total)
        elif coupon.amount is not None:  # FIXED
            raw = amount = coupon.amount
        else:  # pragma: no cover - guarded by Coupon.__post_init__
            raise ValueError(f"{coupon.code}: fixed coupon without an amount")

        clamped = min(amount, remaining_total)

        shares = _allocate(clamped, eligible_lines)
        for ln in eligible_lines:
            share = shares.get(ln.index, 0)
            if share:
                ln.discount += share
                ln.by_coupon[coupon.code] = ln.by_coupon.get(coupon.code, 0) + share

        result.applied = True
        result.discount = clamped
        result.raw_discount = raw
        result.allocations = [
            CouponAllocation(
                line_index=ln.index, product_code=ln.product_code, amount=shares[ln.index]
            )
            for ln in eligible_lines
            if ln.index in shares
        ]
        if clamped == 0:
            result.reason = REASON_NOTHING_LEFT
        elif clamped < amount:
            result.reason = REASON_CLAMPED
        elif coupon.cap is not None and raw > coupon.cap:
            result.reason = REASON_CAPPED
        else:
            result.reason = None

    total_discount = sum(ln.discount for ln in lines)

    return DiscountResponse(
        items_subtotal=items_subtotal,
        shipping_fee=request.shipping_fee,
        total_discount=total_discount,
        payable_total=items_subtotal - total_discount + request.shipping_fee,
        applied_coupon_codes=[c.code for c in selected],
        coupons=[results[code] for code in codes],
        lines=[
            LineResult(
                line_index=ln.index,
                product_code=ln.product_code,
                category=ln.category,
                line_total=ln.line_total,
                discount=ln.discount,
                payable=ln.remaining,
                by_coupon=ln.by_coupon,
            )
            for ln in lines
        ],
    )
