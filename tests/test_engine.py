"""Tests for the confirmed coupon rules. Each test names the rule it pins down.

Rule references (R1-R8) are to docs/decisions.md.
"""

from __future__ import annotations

import itertools

import pytest

from app.engine import calculate
from tests.conftest import by_code, cart, line_discounts

# --- R4: floor the percentage, then allocate proportionally to remaining -----


def test_percentage_floors_then_allocates_leftover_in_product_code_order():
    # BOOK total = 2400 + 333 = 2733; 10% = 273.3 -> 273
    # B1: 273*2400//2733 = 239, B2: 273*333//2733 = 33, sum 272, leftover 1
    # the leftover yen goes to the first product code -> B1 = 240
    resp = calculate(
        cart(
            ("B1", "BOOK", 1200, 2),
            ("B2", "BOOK", 333, 1),
            ("A1", "APPAREL", 5000, 1),
            coupons=["SAVE10"],
        )
    )
    assert resp.total_discount == 273
    assert line_discounts(resp) == {"B1": 240, "B2": 33, "A1": 0}


def test_leftover_tie_broken_by_cart_order_for_identical_product_codes():
    resp = calculate(
        cart(("B1", "BOOK", 333, 1), ("B1", "BOOK", 333, 1), coupons=["SAVE10"])
    )
    assert resp.total_discount == 66  # 666 * 10% = 66.6 -> 66
    assert [ln.discount for ln in resp.lines] == [33, 33]


def test_allocation_sums_to_the_coupon_discount():
    resp = calculate(
        cart(("B3", "BOOK", 777, 3), ("B1", "BOOK", 111, 1), ("B2", "BOOK", 59, 7),
             coupons=["SAVE10"])
    )
    result = by_code(resp)["SAVE10"]
    assert sum(a.amount for a in result.allocations) == result.discount
    assert sum(ln.discount for ln in resp.lines) == resp.total_discount


# --- R3: scope and caps ------------------------------------------------------


def test_percentage_applies_only_to_eligible_items():
    resp = calculate(
        cart(("B1", "BOOK", 1000, 1), ("A1", "APPAREL", 1000, 1), coupons=["SAVE10"])
    )
    assert resp.total_discount == 100
    assert line_discounts(resp) == {"B1": 100, "A1": 0}


def test_save20_cap_applied_after_truncation():
    # APPAREL 20,000 -> 20% = 4,000, capped at 1,000
    resp = calculate(cart(("A1", "APPAREL", 20000, 1), coupons=["SAVE20"]))
    result = by_code(resp)["SAVE20"]
    assert result.raw_discount == 4000
    assert result.discount == 1000
    assert result.reason == "capped"


def test_vip30_cap_applied_after_truncation():
    resp = calculate(cart(("X1", "TOY", 20000, 1), coupons=["VIP30"]))
    result = by_code(resp)["VIP30"]
    assert result.raw_discount == 6000
    assert result.discount == 3000


def test_vip30_covers_every_category_with_no_exclusions():
    # R8: "all items" means all items; no gift-card or sale-item carve-outs.
    resp = calculate(
        cart(("B1", "BOOK", 1000, 1), ("GIFT-BOX", "GIFT", 1000, 1),
             ("H1", "HOME", 1000, 1), coupons=["VIP30"])
    )
    assert resp.total_discount == 900  # 3,000 * 30%
    assert line_discounts(resp) == {"B1": 300, "GIFT-BOX": 300, "H1": 300}


# --- R1 + R5: minimum spend and scope of the fixed-amount coupons ------------


def test_save20_minimum_is_measured_on_apparel_only():
    # A large BOOK line cannot carry APPAREL over its 5,000 yen threshold.
    resp = calculate(
        cart(("B1", "BOOK", 50000, 1), ("A1", "APPAREL", 4999, 1), coupons=["SAVE20"])
    )
    result = by_code(resp)["SAVE20"]
    assert result.applied is False
    assert result.eligible_amount == 4999
    assert result.reason == "minimum_spend_not_met(required=5000)"


def test_save20_minimum_met_exactly_at_the_threshold():
    resp = calculate(cart(("A1", "APPAREL", 5000, 1), coupons=["SAVE20"]))
    assert resp.total_discount == 1000  # 20% of 5,000 = 1,000, exactly at the cap


def test_off500_is_scoped_by_product_code_not_category():
    # Same GIFT category, but only the GIFT-BOX product code is eligible.
    resp = calculate(
        cart(("GIFT-BOX", "GIFT", 1500, 2), ("GIFT-WRAP", "GIFT", 2000, 1),
             coupons=["OFF500"])
    )
    assert by_code(resp)["OFF500"].eligible_amount == 3000  # GIFT-BOX only
    assert line_discounts(resp) == {"GIFT-BOX": 500, "GIFT-WRAP": 0}


def test_off500_minimum_is_measured_on_gift_box_items_only():
    resp = calculate(
        cart(("GIFT-BOX", "GIFT", 2999, 1), ("GIFT-WRAP", "GIFT", 90000, 1),
             coupons=["OFF500"])
    )
    assert by_code(resp)["OFF500"].reason == "minimum_spend_not_met(required=3000)"


def test_off1000_requires_eight_thousand_yen_of_home_items():
    below = calculate(cart(("H1", "HOME", 7999, 1), coupons=["OFF1000"]))
    assert by_code(below)["OFF1000"].reason == "minimum_spend_not_met(required=8000)"

    at = calculate(cart(("H1", "HOME", 8000, 1), coupons=["OFF1000"]))
    assert at.total_discount == 1000


def test_fixed_discount_spreads_across_its_eligible_lines():
    # OFF1000 over HOME 6,000 + 4,000 = 10,000: 600 / 400.
    resp = calculate(
        cart(("H2", "HOME", 6000, 1), ("H1", "HOME", 4000, 1), coupons=["OFF1000"])
    )
    assert line_discounts(resp) == {"H2": 600, "H1": 400}


# --- R2: combination rules ---------------------------------------------------


def test_vip30_is_exclusive_and_wins_alone():
    resp = calculate(
        cart(("B1", "BOOK", 10000, 1), ("GIFT-BOX", "GIFT", 5000, 1),
             coupons=["SAVE10", "VIP30", "OFF500"])
    )
    assert resp.applied_coupon_codes == ["VIP30"]
    assert resp.total_discount == 3000  # 30% of 15,000 = 4,500, capped at 3,000
    assert by_code(resp)["SAVE10"].reason == "excluded_by_exclusive_coupon"
    assert by_code(resp)["OFF500"].reason == "excluded_by_exclusive_coupon"


def test_at_most_three_coupons_in_consideration_order():
    # All four are eligible. Consideration order is (stage, code):
    # SAVE10, SAVE20 (stage 2), then OFF1000, OFF500 (stage 3 -- note that
    # alphabetically "OFF1000" precedes "OFF500"). The first three win.
    resp = calculate(
        cart(("B1", "BOOK", 3000, 2), ("A1", "APPAREL", 5000, 1),
             ("GIFT-BOX", "GIFT", 1500, 2), ("H1", "HOME", 4000, 2),
             coupons=["OFF500", "OFF1000", "SAVE20", "SAVE10"])
    )
    assert resp.applied_coupon_codes == ["SAVE10", "SAVE20", "OFF1000"]
    assert by_code(resp)["OFF500"].reason == "not_selected_combination_limit"
    assert resp.total_discount == 600 + 1000 + 1000
    assert resp.payable_total == 22000 - 2600


def test_deterministic_order_is_kept_even_when_it_costs_the_shopper():
    # R7: we do NOT search for the best combination. SAVE10 earns only 100 yen
    # here but still takes a slot ahead of OFF500, which would have given 500.
    resp = calculate(
        cart(("B1", "BOOK", 1000, 1), ("A1", "APPAREL", 5000, 1),
             ("GIFT-BOX", "GIFT", 3000, 1), ("H1", "HOME", 8000, 1),
             coupons=["SAVE10", "SAVE20", "OFF500", "OFF1000"])
    )
    assert resp.applied_coupon_codes == ["SAVE10", "SAVE20", "OFF1000"]
    assert by_code(resp)["OFF500"].discount == 0


def test_ineligible_coupons_do_not_consume_a_slot():
    # SAVE20 has no APPAREL, so OFF500 takes the third slot instead.
    resp = calculate(
        cart(("B1", "BOOK", 10000, 1), ("GIFT-BOX", "GIFT", 3000, 1),
             ("H1", "HOME", 8000, 1),
             coupons=["SAVE10", "SAVE20", "OFF1000", "OFF500"])
    )
    assert resp.applied_coupon_codes == ["SAVE10", "OFF1000", "OFF500"]
    assert by_code(resp)["SAVE20"].reason == "no_eligible_items"


def test_percentage_applied_before_fixed_amount():
    # SAVE10 assesses BOOK at its pre-discount 10,000; OFF500 then applies to
    # the GIFT-BOX line. Percentage first, per R2.
    resp = calculate(
        cart(("B1", "BOOK", 10000, 1), ("GIFT-BOX", "GIFT", 3000, 1),
             coupons=["OFF500", "SAVE10"])
    )
    assert resp.applied_coupon_codes == ["SAVE10", "OFF500"]
    assert by_code(resp)["SAVE10"].discount == 1000
    assert by_code(resp)["OFF500"].discount == 500
    assert resp.payable_total == 11500


@pytest.mark.parametrize(
    "order", list(itertools.permutations(["SAVE10", "SAVE20", "OFF500", "OFF1000"]))
)
def test_result_is_independent_of_input_order(order):
    resp = calculate(
        cart(("B1", "BOOK", 3000, 2), ("A1", "APPAREL", 5000, 1),
             ("GIFT-BOX", "GIFT", 1500, 2), ("H1", "HOME", 4000, 2),
             coupons=list(order))
    )
    assert resp.applied_coupon_codes == ["SAVE10", "SAVE20", "OFF1000"]
    assert resp.total_discount == 2600
    assert resp.payable_total == 19400


def test_duplicate_codes_are_collapsed():
    resp = calculate(
        cart(("B1", "BOOK", 1000, 1), coupons=["SAVE10", "save10", " SAVE10 "])
    )
    assert resp.applied_coupon_codes == ["SAVE10"]
    assert resp.total_discount == 100


# --- R6 / R7: clamping, and a selected coupon that discounts nothing ---------
# The live catalogue has no two overlapping non-exclusive coupons, so these
# paths need synthetic coupons to reach. See tests/conftest.py.


def test_discount_never_exceeds_the_item_total(synthetic_coupons):
    resp = calculate(cart(("X1", "TOY", 300, 1), coupons=["ABIG"]))
    result = by_code(resp)["ABIG"]
    assert result.raw_discount == 100_000
    assert result.discount == 300
    assert result.reason == "clamped_to_remaining_amount"
    assert resp.payable_total == 0
    assert all(ln.payable >= 0 for ln in resp.lines)


def test_zero_discount_coupon_still_consumes_a_slot(synthetic_coupons):
    # R7: a coupon that was eligible and selected counts toward the limit of
    # three even if its discount works out to 0 yen.
    # Stage-3 alphabetical order: ABIG, AZERO, OFF500.
    resp = calculate(
        cart(("B1", "BOOK", 1000, 1), ("GIFT-BOX", "GIFT", 3000, 1),
             coupons=["SAVE10", "ABIG", "AZERO", "OFF500"])
    )
    assert resp.applied_coupon_codes == ["SAVE10", "ABIG", "AZERO"]

    results = by_code(resp)
    assert results["AZERO"].applied is True
    assert results["AZERO"].discount == 0
    assert results["AZERO"].reason == "no_remaining_amount"
    assert results["OFF500"].reason == "not_selected_combination_limit"
    assert resp.payable_total == 0


# --- misc edge cases ---------------------------------------------------------


def test_unknown_coupon_is_reported_not_fatal():
    resp = calculate(cart(("B1", "BOOK", 1000, 1), coupons=["NOPE", "SAVE10"]))
    assert resp.total_discount == 100
    assert by_code(resp)["NOPE"].reason == "unknown_coupon"


def test_shipping_is_outside_the_discount():
    resp = calculate(cart(("B1", "BOOK", 1000, 1), coupons=["SAVE10"], shipping=550))
    assert resp.total_discount == 100
    assert resp.payable_total == 1450


def test_shipping_cannot_rescue_a_minimum_spend():
    # R1: shipping is never part of the eligible-item total.
    resp = calculate(cart(("A1", "APPAREL", 4900, 1), coupons=["SAVE20"], shipping=1000))
    assert by_code(resp)["SAVE20"].applied is False


def test_no_coupons_is_a_valid_request():
    resp = calculate(cart(("B1", "BOOK", 1000, 1)))
    assert resp.total_discount == 0
    assert resp.payable_total == 1000
    assert resp.coupons == []
