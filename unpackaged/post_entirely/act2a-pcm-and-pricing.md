# Act 2a: catalog and standard pricing

Part of the [Entirely demo](README.md). The first of Act 2's three pieces:

| Piece | Covers | File |
| ----- | ------ | ---- |
| **2a** | **Catalog, bundle structure, attributes, standard EUR pricing** | **this file** |
| 2b | Derived support pricing (percentage of a base) | [act2b-derived-pricing.md](act2b-derived-pricing.md) |
| 2c | Constraint model (CML): the live counter and the blocking rules | [act2c-cml.md](act2c-cml.md) |

2a is deliberately the piece that needs nothing else. It loads the two data
plans and proves every price the pricing engine can produce on its own: fixed
list prices, the translation volume bands, and the print module's
attribute-based band. It needs **no Entirely metadata, no Act 1, and no CCI** —
only the `sf` CLI and this repo's standalone scripts, on top of an org already
built by `prepare_rlm_org`.

What 2a cannot prove is who *sets* the print band. In the finished demo the
constraint model counts the named users and writes the band; here the band is
seeded directly, so the three prices behind it are verified without the
configurator. 2c proves the engine sets it.

## Story

Entirely sells six product families. The Censhare Cloud bundle is the one the
demo configures: a neutral root with a plan, named users, translation, modules,
infrastructure, support and setup. Kestrel Home & Living GmbH buys 55 named
users of it, in EUR.

## Setup

Once per org, after `prepare_rlm_org`. Replace `EntirelyQB` with your own
`sf` alias throughout — these are **`sf` CLI aliases, not CCI org aliases**.

```bash
# 1. Catalog, bundle, attributes. Then EUR prices, bands and derived-price rows.
sf sfdmu run --sourceusername csvfile --targetusername EntirelyQB \
  --path datasets/sfdmu/entirely/en-US/entirely-pcm \
  --canmodify <your-instance>.my.salesforce.com --noprompt
sf sfdmu run --sourceusername csvfile --targetusername EntirelyQB \
  --path datasets/sfdmu/entirely/en-US/entirely-pricing \
  --canmodify <your-instance>.my.salesforce.com --noprompt

# 2. The Volume schedule ships inactive; without this the language bands never fire.
sf apex run --file scripts/apex/activatePriceAdjustmentSchedules.apex --target-org EntirelyQB

# 3. Publish the new entries to the pricing engine.
for dt in Price_Book_Entry_Decision_Table_v2 \
          Price_Adjustment_Tier_Decision_Table \
          Attribute_Based_Adjustment_Decision_Table; do
  python scripts/decision_tables/refresh_decision_table.py \
    --target-org EntirelyQB --developer-name "$dt" --confirm
done

# 4. Rebuild the catalog search index, or product browse shows nothing (see Known issues).
sf api request rest --method POST /services/data/v68.0/connect/pcm/index/deploy \
  --body '{"snapshot":{"activationType":"IMMEDIATE"},"buildType":"FULL"}' \
  --target-org EntirelyQB

# 5. The Kestrel account, contact and opportunity, in EUR.
sf apex run --file scripts/apex/entirely/act2a_reset.apex --target-org EntirelyQB
```

The decision-table refresh is **asynchronous**. The script reports `Queued`;
confirm each one landed by checking that `LastSyncDate` has moved to today:

```bash
sf data query --target-org EntirelyQB \
  -q "SELECT DeveloperName, LastSyncDate FROM DecisionTable WHERE DeveloperName LIKE 'Price%' OR DeveloperName LIKE 'Attribute_Based%'"
```

Before each demo, run only step 5 again. It deletes the Kestrel quotes and puts
the opportunity back to Discovery in EUR.

| Script | What it does |
| ------ | ------------ |
| `act2a_reset.apex` | Deletes the Kestrel quotes and rebuilds the account, contact and opportunity. The metadata-free sibling of `act2_reset.apex`, which also sets the Act 1 fields |
| `activatePriceAdjustmentSchedules.apex` | Activates the org's standard adjustment schedules. Shared with the QuantumBit build, not Entirely-specific |

**Do not** run `act2_reset_attributes.apex` here. It deletes the two sizing
attributes, and deleting an `AttributeDefinition` permanently burns its
`DeveloperName` — only run it when an attribute's data type genuinely has to
change.

## Validate

### Headless, in about three minutes

`build_test_quote.py` places a workbook quote; `check_quote_totals.py` compares
it line by line against `scripts/entirely/expected_quotes.json`. Support prices
at EUR 0 until 2b, so both support SKUs are excluded from every check.

```bash
B="python scripts/entirely/build_test_quote.py --target-org EntirelyQB"
C="python scripts/entirely/check_quote_totals.py --target-org EntirelyQB"

# A. The print band at 61-120 users.
$B --expect DEMO-CS-01 --set-attribute DEMO-CS-09=ENT_NAMED_USERS:61-120 --replace
$C --expect DEMO-CS-01 --exclude-sku DEMO-CS-22 --exclude-sku DEMO-CS-24

# B. The whole CS-02 configuration, band at 121+.
$B --expect DEMO-CS-02 --set-attribute DEMO-CS-09=ENT_NAMED_USERS:121+ --replace
$C --expect DEMO-CS-02 --exclude-sku DEMO-CS-23 --exclude-sku DEMO-CS-24

# C. CS-01 as the workbook states it, band left at its 1-60 default.
$B --expect DEMO-CS-01 --replace
$C --expect DEMO-CS-01 --exclude-sku DEMO-CS-22 --exclude-sku DEMO-CS-24
```

Expected results:

| Check | What it proves | Expected |
| ----- | -------------- | -------- |
| A | The band drives the price | `DEMO-CS-09` at **EUR 280**, every other line exact. The checker reports CS-09 as a mismatch on purpose: the workbook states EUR 180 for 55 users, and the band was seeded past it |
| B | The full enterprise configuration | **PASS**. Monthly EUR 4,094.00, annual EUR 520.00, one-time EUR 2,520.00, first 12 months **EUR 52,168.00**. Includes 9 languages at EUR 6 (EUR 54) and print at EUR 420 |
| C | The workbook's own CS-01 | **PASS**. Monthly EUR 2,076.00, one-time EUR 1,000.00, first 12 months **EUR 25,912.00**. Includes 4 languages at EUR 9 (EUR 36) and print at EUR 180 |

Run C last: it leaves the clean CS-01 quote on the opportunity for the walk-through.

The three print prices across A, B and C are the whole attribute-based band —
EUR 180 at `1-60`, EUR 280 at `61-120`, EUR 420 at `121+`.

### In the browser

1. **Catalog.** App Launcher → Product Catalogs → **Entirely** (`CAT-ENTIRELY`).
   Six categories, one per family: Business OS, Censhare, Elaine, Epoq,
   Facelift, Marmind. 93 products are filed across them.
2. **Bundle.** Products → **Censhare Cloud** (`DEMO-CS-CLOUD`) → Related.
   11 component groups, 26 components:

   | Group | Pick | Notes |
   | ----- | ---- | ----- |
   | Plan | exactly 1 | Professional (default) or Enterprise |
   | Named Users | any | full, light, development |
   | Translation | any | base pack, additional language, interface |
   | Modules and APIs | any | print, Headless CMS APIs, Content Picker, connectors, `QB-DB` |
   | Syndication | any | PIM Syndication, Connection 5-pack |
   | Infrastructure | any | production environment, app server, storage |
   | Test Environment | at most 1 | size M or size L |
   | Application Support | at most 1 | Gold or Platinum |
   | Cloud Operations | any | Cloud Ops & Support |
   | System Setup | at most 1 | size M or size L |
   | Services | any | Technical Consulting |

   The plan is a *component*, not the root, so Act 7 can amend Professional to
   Enterprise as an ordinary configuration change rather than a bundle swap.
3. **Attributes.** Both are read-only, so a rep cannot type over the
   configurator's answer:

   | Attribute | On | Type | Default |
   | --------- | -- | ---- | ------- |
   | Total named users (`ENT_TOTAL_NAMED_USERS`) | `DEMO-CS-CLOUD` | Number | 0 |
   | User band (`ENT_NAMED_USERS`) | `DEMO-CS-09` | Picklist `1-60` / `61-120` / `121+` | `1-60`, price-impacting |
4. **Prices.** Open the CS-01 quote left by check C and compare its lines with
   the table above.
5. **Volume bands by hand.** On that quote, change the quantity of
   `DEMO-CS-07` (additional translation language) and reprice:
   2 languages → EUR 12 each, 4 → EUR 9, 9 → EUR 6.

## Gate for 2b

Checks A, B and C give the results above, and the browser walk-through matches.
From then on, any pricing difference is a 2b or 2c problem, not a catalog one.

## Design decisions

**Support has no minimum.** The workbook gives each support product a floor
(EUR 90 Gold, EUR 140 Platinum, EUR 30 Cloud Ops), but Revenue Cloud has no
standard way to express one: a derived product's price book entry must carry a
list price of 0, and Help says that both Formula Based Pricing and the Discount
Distribution Service — which owns the only built-in floor, Minimum Net Unit
Price — "doesn't support derived products on quote line items". Modelling it by
hand needed three custom fields, a context extension and three extra procedure
steps, and was still not currency-aware, so it was dropped. Support is a plain
percentage of its base. The floor bites on the Cloud Ops line of **both**
verification quotes, which price at EUR 17.00 (CS-01) and EUR 29.50 (CS-02)
instead of EUR 30.00; the Gold and Platinum lines clear theirs comfortably. The
only supported route to a floor is an Apex posthook on the procedure plan — see
[act2b-derived-pricing.md](act2b-derived-pricing.md). Until then the minimum
stays a talking point.

**The band is a picklist, not the headcount.** `AttributeAdjustmentCondition`
accepts only the `equals` operator, so a threshold such as "61 or more users"
cannot be expressed. The constraint model does the banding and pricing matches a
band by name.

## Known issues

- **Product browse is empty until the search index finishes.** Products are
  invisible in the configurator and in browse until a build that post-dates the
  catalog completes — about 40 minutes. The headless checks do not need it, so
  run them while it builds. Poll with:

  ```bash
  sf api request rest --method GET /services/data/v68.0/connect/pcm/index/snapshots \
    --target-org EntirelyQB
  ```

  Wait for `lastBuildStatus: COMPLETED` and a `catalogSnapshotTime` later than
  the data load.
- **SFDMU refuses to write to a production org** unless the instance host is
  confirmed: `--canmodify <host>.my.salesforce.com`. A trial org counts as
  production.
- **The Volume schedule ships inactive.** `Standard Price Adjustment Tier` is
  the only Volume schedule and the pricing procedure resolves it by name, so the
  language tiers attach to it. Leave it inactive and they are silently ignored —
  4 languages price at the EUR 12 list price instead of EUR 9. Activating it
  also switches on the 21 QuantumBit tiers it already holds, all on
  `QB-MSG-STRT` at quantity 5 or more. That is the full extent of the side
  effect.
- **The pricing discovery procedure must be active, or any quote carrying a
  support line fails to place** with *Ensure that this procedure has at least
  one active version*. The build's `reconfigure_pricing_discovery` step leaves
  `Salesforce_Default_Pricing_Discovery_Procedure` inactive, with no rank and no
  context definition, and by design will not activate an expression set that was
  inactive when it ran. A quote with no derived-price line is unaffected, which
  is what makes this look like a catalog problem rather than a pricing one.
  Check and repair:

  ```bash
  sf data query --target-org EntirelyQB -q "SELECT Id, ApiName, IsActive, Rank, StartDateTime FROM ExpressionSetVersion WHERE ApiName = 'Salesforce_Default_Pricing_Discovery_ProcedureV1'"
  sf data query --target-org EntirelyQB -q "SELECT Id, ContextDefinitionId FROM ExpressionSetDefinitionContextDefinition WHERE ExpressionSetDefinition.DeveloperName = 'Salesforce_Default_Pricing_Discovery_Procedure'"
  # Point the junction at RLM_SalesTransactionContext, then set rank and start date:
  sf data update record --target-org EntirelyQB --sobject ExpressionSetDefinitionContextDefinition \
    --record-id <9QY...> --values "ContextDefinitionId=<11O...>"
  sf data update record --target-org EntirelyQB --sobject ExpressionSetVersion \
    --record-id <9QM...> --values "Rank=1 StartDateTime=2020-01-01T00:00:00.000Z"
  python scripts/expression_sets/activate_expression_set.py --target-org EntirelyQB \
    --expression-set Salesforce_Default_Pricing_Discovery_Procedure \
    --version Salesforce_Default_Pricing_Discovery_ProcedureV1 --activate --no-cascade --confirm
  ```
- **`sf data create record` cannot create the Kestrel account.** The standard
  duplicate rule matches it against the org's sample data and rejects it with
  *Use one of these records?* — after having already inserted it, which leaves a
  stray account behind. `build_test_quote.py` then resolves the stray one and
  reports no opportunity. Use `act2a_reset.apex`, which saves through the rule
  with `DuplicateRuleHeader.AllowSave`.
- **Support lines price at EUR 0.** Expected until 2b applies the derived-pricing
  overlay. Exclude `DEMO-CS-22`, `-23` and `-24` from every 2a check.
- **`QB-DB` is renamed** to "Headless CMS API Usage" by the PCM plan, by design.
  Its SKU is unchanged, which is all the QuantumBit usage scripts key on.

## Where things live

| Path | Contents |
| ---- | -------- |
| [`datasets/sfdmu/entirely/en-US/entirely-pcm`](../../datasets/sfdmu/entirely/en-US/entirely-pcm/README.md) | Products, catalog, bundle, attributes |
| [`datasets/sfdmu/entirely/en-US/entirely-pricing`](../../datasets/sfdmu/entirely/en-US/entirely-pricing/README.md) | EUR prices, volume and attribute bands, derived-price rows |
| `scripts/entirely/workbook_to_sfdmu.py` | Generates both plans from the demo workbook. Edit the generator, never the CSVs |
| `scripts/entirely/expected_quotes.json` | The workbook's own totals, generated alongside them |
| `scripts/apex/entirely/act2a_reset.apex` | The demo reset |
