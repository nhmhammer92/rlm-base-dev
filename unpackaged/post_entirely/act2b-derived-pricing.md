# Act 2b: derived support pricing

Part of the [Entirely demo](README.md). The second of Act 2's three pieces:

| Piece | Covers | File |
| ----- | ------ | ---- |
| 2a | Catalog, bundle structure, attributes, standard EUR pricing | [act2a-pcm-and-pricing.md](act2a-pcm-and-pricing.md) |
| **2b** | **Derived support pricing (percentage of a base)** | **this file** |
| 2c | Constraint model (CML): the live counter and the blocking rules | [act2c-cml.md](act2c-cml.md) |

2b takes the two support products that priced at EUR 0 through all of 2a and
makes them price themselves off the lines they cover. It needs 2a's two data
plans loaded and nothing else — no Entirely metadata, no Act 1, no CCI, and no
custom fields.

## Story

Entirely does not quote support as a line a rep types a price into. Application
Support is a percentage of the subscription it protects, and Cloud Operations is
a percentage of the infrastructure it runs. A rep adds the support product and
the number appears.

| Support product | Rate | Covers |
| --------------- | ---- | ------ |
| `DEMO-CS-22` Application Support Gold | 7% | the Censhare subscription lines |
| `DEMO-CS-23` Application Support Platinum | 10% | the Censhare subscription lines |
| `DEMO-CS-24` Cloud Ops & Support | 5% | the infrastructure and test-environment lines |

## How it works

Three pieces, all of which 2a already put in place except the last:

1. **Price book entries at EUR 0 with `IsDerived = true`** for the three support
   products. A derived product's entry must carry a list price of 0.
2. **`PricebookEntryDerivedPrice` rows** — one per support product per
   contributing product, 37 in all, each carrying the formula
   `PERCENTAGE(TotalPrice,<rate>)/12`. The engine evaluates the formula once per
   contributor and **sums** the results. The `/12` is there because `TotalPrice`
   spans the whole term while the result is read as a unit price.
3. **The Derived Pricing element in the pricing procedure**, added by the
   `entirely_derived_support.json` overlay.

The overlay trades the procedure's header-discount block for the Derived Pricing
element, because Help forbids a Discount Distribution Service and a Derived Price
element in the same procedure. Header discounts keep working anyway: the active
quote procedure plan applies them in its third section,
`RLM_Price_Distribution_Procedure`, which carries its own Discount Distribution
Service. `force-app` is untouched — this is an org-side change only.

## Setup

After 2a, once per org. Replace `EntirelyQB` with your own `sf` alias — these are
**`sf` CLI aliases, not CCI org aliases**.

```bash
# 1. Snapshot the procedure first. The overlay cannot restore what it replaces.
python scripts/expression_sets/export_expression_set.py --target-org EntirelyQB \
  --developer-name RLM_DefaultPricingProcedure > /tmp/pricing-procedure.pre2b.json

# 2. Preview, then apply.
python scripts/expression_sets/apply_expression_set_overlay.py --target-org EntirelyQB \
  --overlay datasets/expression_set_overlays/entirely_derived_support.json
python scripts/expression_sets/apply_expression_set_overlay.py --target-org EntirelyQB \
  --overlay datasets/expression_set_overlays/entirely_derived_support.json --confirm

# 3. Publish the derived-price rows to the pricing engine.
python scripts/decision_tables/refresh_decision_table.py --target-org EntirelyQB \
  --developer-name Derived_Pricing_Entries_Decision_Table --confirm
```

Step 3 is not optional and 2a does not cover it — 2a refreshes only the tables
matching `Price%` and `Attribute_Based%`. Until the Derived Pricing Entries table
is refreshed, the 37 rows are invisible to pricing and every support line still
comes out at EUR 0. The refresh is **asynchronous**; confirm `LastSyncDate` has
moved to today:

```bash
sf data query --target-org EntirelyQB \
  -q "SELECT DeveloperName, LastSyncDate FROM DecisionTable WHERE DeveloperName = 'Derived_Pricing_Entries_Decision_Table'"
```

Applying the overlay deactivates the procedure version, patches it and
reactivates it, which takes about three minutes. Afterwards the procedure has 87
steps and 20 variables, and the Derived Pricing element sits at top-level
sequence 4, immediately after `Getbasepricesfrompricebook` — its output is
consumed by `Setthenetunitpriceforlineswithderivedpricing`.

To undo: re-apply `discount_distribution.json` and remove the added step, or
restore from the snapshot.

## Validate

### Headless, in about three minutes

Both support SKUs now price, so neither is excluded any more — the 2a checks
drop their `--exclude-sku` flags.

```bash
B="python scripts/entirely/build_test_quote.py --target-org EntirelyQB"
C="python scripts/entirely/check_quote_totals.py --target-org EntirelyQB"

# A. The whole CS-02 configuration, band at 121+.
$B --expect DEMO-CS-02 --set-attribute DEMO-CS-09=ENT_NAMED_USERS:121+ --replace
$C --expect DEMO-CS-02

# B. CS-01 as the workbook states it.
$B --expect DEMO-CS-01 --replace
$C --expect DEMO-CS-01
```

| Check | Expected |
| ----- | -------- |
| A | **PASS**. `DEMO-CS-23` Platinum at **EUR 350.40** (10% of a 3,504 base), `DEMO-CS-24` Cloud Ops at **EUR 29.50**. First 12 months EUR 56,726.80 |
| B | **PASS**. `DEMO-CS-22` Gold at **EUR 121.52** (7% of a 1,736 base), `DEMO-CS-24` Cloud Ops at **EUR 17.00**. First 12 months EUR 27,574.24 |

Run B last: it leaves the clean CS-01 quote on the opportunity for the
walk-through.

### In the browser

1. Open the CS-01 quote left by check B.
2. **Gold reads EUR 121.52 and Cloud Ops EUR 17.00**, neither of them typed.
3. **Hover Net Unit Price** on the Gold line to open the price waterfall. The
   derived row shows the charge was computed, not looked up. (Hover is the only
   way in — there is no click target. In the configurator the waterfall lives in
   the Summary component instead.)
4. Change the quantity of a covered line — `DEMO-CS-03` named users — and
   reprice. Gold moves with it.

## Design decisions

**Support is a percentage of its contributors' net prices, not their list
prices.** This is the engine's behaviour and it is not configurable. Derived
pricing resolves *after* the contributing lines are fully priced, whatever
sequence the element sits at, so the formula's `TotalPrice` is each
contributor's net subtotal. Verified live on `EntirelyQB`: a 20% manual discount
on `DEMO-CS-03` moved Platinum from EUR 350.40 to EUR 325.20, and removing the
discount moved it back. A plain reprice with nothing changed leaves every support
figure untouched, because the adjustments it re-derives are deterministic.

Moving the element earlier in the procedure does not change this, and a
quantity-weighted list-price basis cannot be expressed at all: the only formula
token carrying quantity is `TotalPrice`, which is net, while `ListPrice` is a
unit price — a 90-user line would contribute EUR 14 rather than EUR 1,260.
Salesforce's own example (`ListPrice * 0.10`) sidesteps this by deriving from a
single-unit bundle.

**Manual discounts do apply to derived lines.** Step 19
`Applyamountbasedandpercentagebaseddiscounts` filters only on
`ItemPricingSource NotEquals 'LastTransaction'`, so a rep can discount a support
line directly. The steps that *do* exclude derived lines, via
`DerivedPricingAttribute Equals false`, are attribute-based adjustments (13),
volume and contract tiers (16), contract discounts (18) and renewal price
revision (20). Step 18 is misleadingly named
`Applymanualdiscountstolineswithoutderivedpricing` but filters on
`ItemContractDiscountValue`.

**No floor.** See [act2a-pcm-and-pricing.md](act2a-pcm-and-pricing.md) →
*Design decisions*. The floor bites on the Cloud Ops line of both verification
quotes (EUR 17.00 and EUR 29.50 against a EUR 30.00 minimum).
`scripts/entirely/workbook_to_sfdmu.py` drops the workbook's floor from
`expected_quotes.json` for exactly this reason — the workbook's own
*Support base* column is already the net base the engine sums, so only the floor
has to come off.

## Known issues

- **Every support line prices at EUR 0.** The Derived Pricing Entries decision
  table has not been refreshed since the pricing plan was loaded. Run setup
  step 3.
- **A quote carrying a support line fails to place.**
  `Salesforce_Default_Pricing_Discovery_Procedure` is inactive, or active
  without a context definition or at the wrong rank. It must be active at
  Rank 1 with a context definition. 2a repairs this; a re-created org needs it
  again.
- **Support moved after a rep discounted something else.** Expected — see
  *Design decisions*.

## Gate for 2c

Checks A and B pass with the figures above. From then on any pricing difference
is a 2c problem: the configurator setting the band, not the engine pricing it.

## A floor, if it is ever needed

The supported route is an Apex posthook on the procedure plan — a
`RevSignaling.SignalingApexProcessor` implementation whose
`execute(RevSignaling.TransactionRequest)` reads the priced lines through
`Context.IndustriesContext().queryTags(...)` and clamps `NetUnitPrice`. It
attaches to the procedure plan as the first or last element, may run SOQL but
not DML, and needs the **Revenue Cloud Advanced** license plus *Procedure Plan
Orchestration for Pricing*. The same hook is the only way to get a
discount-proof, list-price basis. Not built — deliberately deferred.
