# Coupon Discount API — confirmed rules and implementation decisions

The coupon logic had grown campaign by campaign, so the basis of a
discount was hard to explain. This service recalculates discounts from one
declarative catalogue and one pipeline, and returns a per-coupon and per-line
breakdown so any yen on an order can be traced back to a rule.

- **Rules source:** Minami, Marketing Operations — confirmed over two rounds of
  questions in chat, 2026-11-07.
- **Status:** R1–R8 confirmed and implemented. The three remaining items in
  §4 are decisions I made where the rules were silent; each is isolated so
  that changing one is a data or one-line change.

---

## 1. Confirmed rules

### R1 — Minimum spend
- The minimum spend is checked against the **pre-discount total of that
  coupon's own eligible items**, not the whole cart.
- Amounts are based on **tax-inclusive item prices**.
- **Shipping is never part of the eligible-item total.**

Consequence: a coupon's minimum is evaluated once, against untouched prices,
before any discount is applied. Applying one coupon can therefore never make
another fail its minimum — eligibility is independent of application order,
which is what makes R2's order-independence guarantee achievable.

### R2 — Combining coupons
- Only coupons that **pass the eligibility checks** count toward the limit. An
  ineligible coupon does not consume a slot.
- **`VIP30` cannot be combined.** If it is submitted and eligible, it is the
  only coupon used; everything else is reported as excluded.
- Otherwise **up to 3 coupons** apply.
- Coupons are **considered** in this order:
  `VIP30` → `SAVE10`, `SAVE20` → `OFF500`, `OFF1000`;
  within each step, **coupon codes in alphabetical order**.
- Discounts are **calculated** with **percentage coupons before fixed-amount
  coupons**.
- **The result does not depend on the order the codes were entered in.**

### R3 — Percentage coupons
A percentage coupon applies **only to its eligible items**, using those items'
**pre-discount** amounts.

### R4 — Currency and rounding
- Amounts are **whole yen**.
- For a percentage coupon: apply the rate to the **total pre-discount amount of
  its eligible items**, then **drop the fractional yen**. **Any cap is applied
  after that** — not before.
- The coupon discount is then **allocated to eligible items in proportion to
  the amount remaining on each item**, **dropping fractions** for each
  allocation, and **distributing leftover yen one at a time in product-code
  order** (cart order for identical product codes).

Note the deliberate asymmetry: the discount *amount* comes from
**pre-discount** totals, while its *allocation* is weighted by each line's
**remaining** amount. Both are implemented exactly as stated.

### R5 — The catalogue

| Code | Benefit | Scope | Cap | Min. spend | Combinable |
|---|---|---|---|---|---|
| `VIP30` | 30% off | all items | ¥3,000 | none | **no — exclusive** |
| `SAVE10` | 10% off | `BOOK` items | none | none | yes |
| `SAVE20` | 20% off | `APPAREL` items | ¥1,000 | ¥5,000 | yes |
| `OFF500` | ¥500 off | **product code `GIFT-BOX`** | — | ¥3,000 | yes |
| `OFF1000` | ¥1,000 off | `HOME` items | — | ¥8,000 | yes |

`OFF500` is the only coupon scoped by **product code** rather than category —
a `GIFT-WRAP` item in the same `GIFT` category is not eligible. Every minimum
is measured against that coupon's own eligible items (R1).

### R6 — Over-sized discounts are reduced, not rejected
If a coupon is worth more than the amount still remaining on its eligible
items, it is **reduced to what remains**. It is not rejected, and **no item's
amount can go below zero**.

### R7 — Selection is deterministic, not optimal
The fixed consideration order in R2 is correct as given. The API does **not**
search for the combination of three coupons that would give the largest
discount, even when another combination would save the shopper more. A coupon
that was eligible and selected **still consumes one of the three slots even if
its discount works out to ¥0**.

### R8 — No blanket item exclusions
`VIP30`'s "all items" means all items in the cart. No exclusions are specified
for gift cards, sale items, or anything else.

---

## 2. Worked example

Cart: `B1` BOOK ¥1,200 × 2, `B2` BOOK ¥333 × 1, `A1` APPAREL ¥5,000 × 1.
Coupon submitted: `SAVE10`.

1. Eligible items → BOOK only: 2,400 + 333 = **2,733** (R3). No minimum (R5).
2. 10% of 2,733 = 273.3 → drop the fraction → **273**; no cap (R4).
3. Allocate across BOOK lines by remaining amount (R4):
   - `B1`: 273 × 2,400 / 2,733 = 239.7 → **239**
   - `B2`: 273 × 333 / 2,733 = 33.2 → **33**
   - sum 272, leftover **1 yen** → first in product-code order (`B1`) → **240**
4. Discount **¥273**; `A1` untouched.

Pinned by
`tests/test_engine.py::test_percentage_floors_then_allocates_leftover_in_product_code_order`.

---

## 3. Implementation decisions

### D1 — Rules are data, not code
`app/catalog.py` holds every coupon as a frozen `Coupon` row: rate or amount,
cap, eligible categories, eligible product codes, minimum spend, exclusivity,
consideration stage. `app/engine.py` never names a coupon. A new campaign is a
new row; Minami's second round of answers changed five rows and zero lines of
engine logic.

### D2 — One sort key gives both required orders
Each coupon carries a `stage`: 1 for `VIP30`, 2 for the other percentage
coupons, 3 for the fixed-amount coupons. Sorting by `(stage, code)` produces
Minami's *consideration* order and, because stages 1–2 are percentage and
stage 3 is fixed-amount, simultaneously satisfies "percentage before
fixed-amount" for *calculation*. One ordering, no second rule to keep in sync.

Worth flagging: plain alphabetical ordering puts **`OFF1000` before `OFF500`**
(`'1' < '5'`). This follows R2 as stated and is asserted in the tests, so if
Marketing meant numeric order the test will fail loudly rather than drift.

### D3 — Scope is two independent filters
A coupon restricts by category, by product code, by both, or by neither
(`Coupon.matches`). R5 needed product-code scoping for `OFF500` after the
first round had only categories; modelling scope as two optional filters
absorbed that without touching the pipeline.

### D4 — Integer arithmetic throughout
All money is `int` yen and all division is floor division (`//`). No floats
enter the calculation, so there is no binary-rounding drift and "drop the
fractional yen" is exact by construction.

### D5 — Input order cannot affect the result
Submitted codes are upper-cased, trimmed, and de-duplicated, then sorted by
`(stage, code)` before anything is calculated. R2's order-independence
guarantee is a property of the pipeline, not something each rule must respect.
Tested across all 24 permutations of four coupons.

### D6 — Allocation is exhaustive and bounded
Each line's share is floored, the remainder is handed out a yen at a time in
product-code order, and no line is ever allocated more than it has remaining
(R6). Per-coupon allocations always sum to that coupon's discount, and
per-line discounts always sum to the order total — both asserted.

### D7 — The response explains itself
Every submitted code comes back with its outcome: the eligible amount it was
assessed on, the raw discount before any cap, the final discount, its
allocation per line, and a machine-readable `reason` when it was not applied
or was reduced — `unknown_coupon`, `no_eligible_items`,
`minimum_spend_not_met(required=N)`, `excluded_by_exclusive_coupon`,
`not_selected_combination_limit`, `capped`, `clamped_to_remaining_amount`,
`no_remaining_amount`. This is the "explain the basis for a discount"
requirement served directly from the calculation rather than reconstructed
afterwards. `GET /coupons` additionally exposes the live catalogue so Marketing
can confirm what the API believes the rules to be.

### D8 — Pure core, thin HTTP shell
`calculate(DiscountRequest) -> DiscountResponse` is a pure function: no I/O, no
clock, no database. `app/main.py` only validates and delegates. The rules are
testable without a server, which is why 54 tests run in ~0.3 s.

### D9 — Two rules are currently unreachable, and are tested anyway
With this catalogue, no two combinable coupons overlap in scope — `BOOK`,
`APPAREL`, `GIFT-BOX`, and `HOME` are disjoint, and the one coupon covering
everything (`VIP30`) is exclusive. So no coupon can ever find its eligible
items already discounted, which means R6's clamping and R7's ¥0-coupon rule
cannot fire today. They are implemented as confirmed and covered by tests that
register synthetic overlapping coupons (`tests/conftest.py`), so the behaviour
is correct the day Marketing adds a campaign that overlaps an existing one.

---

## 4. Decisions taken where the rules were silent

| # | Decision | Reasoning |
|---|---|---|
| **A1** | An unknown, ineligible, or unselected coupon is **reported with a reason** rather than failing the whole request | A rebuild aimed at explainability should say *why* a coupon did nothing; rejecting the request hides the other coupons' results. Switching to a 4xx is a change in `app/main.py` alone |
| **A2** | Duplicate submissions of one code collapse to a single application, and codes are case-insensitive | A coupon entered twice is a UI artefact, not a double discount |
| **A3** | Shipping is accepted and passed through untouched into `payable_total`; no coupon touches it | R1 puts shipping outside eligible-item totals, and no free-shipping coupon exists in the catalogue |

### Still worth asking Minami

- Is the alphabetical tie-break intended to put `OFF1000` ahead of `OFF500`
  (D2)? It only matters when more than three coupons compete for slots.
- Should an unknown coupon code be a client error rather than a reported
  outcome (A1)?

---

## 5. Out of scope

Per the brief: inventory, coupon redemption counts and budgets, expiry,
authentication, payments, refunds, and persistence. Cart lines are trusted as a
snapshot from the cart service and are not re-priced or re-validated here.
