# Coupon Discount API

[![CI](https://github.com/Vb-777/CartDiscountEngine/actions/workflows/ci.yml/badge.svg)](https://github.com/Vb-777/CartDiscountEngine/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue)
![Coverage](https://img.shields.io/badge/coverage-99%25-brightgreen)
![License](https://img.shields.io/badge/license-MIT-green)

A discount engine for an e-commerce cart. It accepts a purchase plus the coupon
codes a shopper wants to use, and returns the discount with a **per-coupon and
per-line breakdown**, so the basis of every yen can be traced back to a rule.

The business problem was that coupons had been added campaign by campaign until
nobody could explain why a given order was discounted by a given amount. The fix
is one declarative catalogue, one calculation pipeline, and a response that
explains itself.

## What this demonstrates

- **Rules as data.** Every coupon is one row in `app/catalog.py`: rate or amount,
  cap, eligible categories, eligible product codes, minimum spend, exclusivity,
  ordering. `app/engine.py` never names a coupon. A new campaign is a config
  change, not a code change.
- **Requirements elicited, not given.** The rules were not documented anywhere.
  They were gathered by questioning a non-technical stakeholder across two
  rounds. `docs/decisions.md` records what was confirmed, what was decided in
  the absence of an answer, and what remained open.
- **Exact money arithmetic.** Integer yen throughout, floor division only. No
  float enters the calculation, so "drop the fractional yen" is exact rather
  than approximately right.
- **Deterministic allocation.** When a discount does not divide evenly across
  cart lines, the remainder is distributed one yen at a time in product-code
  order â€” a real accounting requirement, not a rounding shrug.
- **Order independence as a property.** The result never depends on the order
  coupon codes were submitted in. Verified across all 24 permutations of four
  coupons rather than asserted in a comment.
- **Tested against the hard cases.** 54 tests, 99% coverage, each test named
  after the rule it pins down.

## Run

```bash
pip install -e ".[dev]"
pytest -q                                  # 54 passed
uvicorn app.main:app --port 8000
```

Interactive docs at <http://localhost:8000/docs>.

```bash
curl -s localhost:8000/discounts -H 'content-type: application/json' \
     -d @sample_request.json | python3 -m json.tool
```

Or `make all` to run the lint, type-check and coverage gates exactly as CI does.

No database, no Docker, no environment variables, no external services â€” two
commands from clone to a green test run.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/discounts` | Calculate the discount for a cart plus coupon codes |
| `GET` | `/coupons` | The live catalogue, so the business can verify what the API believes |

## Coupons

| Code | Benefit | Scope | Cap | Min. spend | Combinable |
|---|---|---|---|---|---|
| `VIP30` | 30% off | all items | Â¥3,000 | none | **no â€” exclusive** |
| `SAVE10` | 10% off | `BOOK` items | none | none | yes |
| `SAVE20` | 20% off | `APPAREL` items | Â¥1,000 | Â¥5,000 | yes |
| `OFF500` | Â¥500 off | product code `GIFT-BOX` | â€” | Â¥3,000 | yes |
| `OFF1000` | Â¥1,000 off | `HOME` items | â€” | Â¥8,000 | yes |

`OFF500` is scoped by **product code**, not category â€” a `GIFT-WRAP` item in the
same `GIFT` category is not eligible. Scope is therefore modelled as two
independent filters rather than one, which is the kind of inconsistency real
campaign rules actually contain.

Every minimum spend is measured against that coupon's **own** eligible items,
pre-discount and tax-inclusive, never including shipping.

## How a discount is calculated

1. **Normalise** â€” upper-case, trim, de-duplicate the submitted codes.
2. **Eligibility** â€” eligible items must exist, and their pre-discount total
   must meet that coupon's minimum spend.
3. **Selection** â€” an exclusive coupon applies alone; otherwise the first three
   eligible coupons in a fixed consideration order. Ineligible coupons do not
   consume a slot; a selected coupon that discounts Â¥0 does. The order is
   deterministic, *not* discount-maximising.
4. **Application** â€” percentage coupons before fixed-amount. A percentage is
   taken on its eligible items' pre-discount total, the fractional yen is
   dropped, *then* the cap is applied.
5. **Allocation** â€” spread over eligible lines in proportion to each line's
   **remaining** amount, flooring each share and distributing the leftover yen
   one at a time in product-code order.

Step 4 and 5 use different bases on purpose: the discount *amount* comes from
pre-discount totals, its *allocation* is weighted by what is left on each line.

## Worked example

Cart: `B1` BOOK Â¥1,200 Ã— 2, `B2` BOOK Â¥333 Ã— 1, `A1` APPAREL Â¥5,000 Ã— 1.
Coupon: `SAVE10`.

1. Eligible items â†’ BOOK only: 2,400 + 333 = **2,733**
2. 10% of 2,733 = 273.3 â†’ drop the fraction â†’ **Â¥273**
3. Allocate by remaining amount: `B1` â†’ 239, `B2` â†’ 33, sum 272, leftover
   **1 yen** â†’ first in product-code order â†’ `B1` = **240**

`A1` is untouched. Pinned by
`tests/test_engine.py::test_percentage_floors_then_allocates_leftover_in_product_code_order`.

## Layout

```
app/catalog.py       Coupon definitions â€” rules as data
app/engine.py        The calculation pipeline. Pure; never names a coupon
app/schemas.py       Request/response contracts (whole-yen integers)
app/main.py          HTTP shell: validate, delegate, respond
tests/               54 tests, each naming the rule it pins down
docs/decisions.md    Confirmed rules, decisions taken, questions left open
```

`calculate(DiscountRequest) -> DiscountResponse` is a pure function â€” no I/O, no
clock, no database â€” which is why the suite runs in under half a second.

## Two rules that cannot currently fire

With this catalogue, `BOOK`, `APPAREL`, `GIFT-BOX` and `HOME` are disjoint and
the one coupon covering everything is exclusive, so no coupon can ever find its
eligible items already discounted. That makes two confirmed rules â€” clamping an
over-sized discount, and a Â¥0 coupon still consuming a combination slot â€”
unreachable in practice today.

They are implemented as specified and covered by tests that register synthetic
overlapping coupons, so the behaviour is correct the day a campaign overlaps an
existing one. See `docs/decisions.md` Â§D9.

## Provenance

This started as a timed take-home exercise with a deliberately incomplete brief
and a non-technical stakeholder available for questioning â€” which is why the
decision log, rather than the code, is the part worth reading. AI assistance was
used during the original exercise and declared to the reviewer.

## Out of scope

Inventory, coupon redemption counts and budgets, expiry, authentication,
payments, refunds, and persistence. Cart lines are trusted as a snapshot from
the cart service and are not re-priced or re-validated.

