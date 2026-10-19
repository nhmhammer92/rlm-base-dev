# entirely-pricing Data Plan

EUR pricing for the **Entirely AG** demo catalogue: price book entries for all
93 products, the workbook's volume and attribute bands, and the derived-price
rows that make support a percentage of its base. Load
[entirely-pcm](../entirely-pcm/README.md) **first** — this plan resolves
`Product2` and `AttributeDefinition` from it as `Readonly`.

> Every price, rate, band and minimum in this plan is **fictional demo data**.

## Generated, not hand-written

```bash
python scripts/entirely/workbook_to_sfdmu.py --workbook "<the .xlsx>"
```

The workbook is not committed. Edit the generator, not the CSVs.

## The four pricing mechanisms

The workbook's "Demo price model" column maps onto four different Revenue Cloud
mechanisms. Which one a product uses determines what this plan writes for it.

| Workbook price model | Mechanism | What is loaded |
|---|---|---|
| Fixed price | Price book entry | `UnitPrice` = the workbook price |
| Volume bands | Volume adjustment tiers | PBE at the **first** band's price, plus one `OverrideAmount` tier per band |
| Band by user count | Attribute-based adjustment | PBE at the first band's price, plus a rule per higher band |
| Percentage of base | Derived pricing | PBE at **0** with `IsDerived = true`, plus one derived-price row per contributing product |

### Volume bands

`DEMO-CS-07` (additional translation languages) is the one Act 2 shows: 1–3
languages at EUR 12, 4–8 at EUR 9, 9 or more at EUR 6. Its price book entry
carries EUR 12 and three `OverrideAmount` tiers override it by quantity, so
4 languages price at **EUR 9.00 each**. `DEMO-MM-03` and `DEMO-MM-04` get the
same treatment for free, since they use the identical workbook mechanism.

Two constraints are easy to get wrong here:

- **Tiers are per currency.** A USD-only tier never fires on a EUR quote, so
  every row carries `CurrencyIsoCode = EUR`.
- **The schedule is shared and ships inactive.** `Standard Price Adjustment
  Tier` is the only Volume schedule and the pricing procedure resolves it by
  that name, so the tiers attach to it rather than to a new schedule. It must
  be **activated** for them to apply. Activating it also switches on the 21
  QuantumBit tiers it already holds — all of them on one product,
  `QB-MSG-STRT`, at quantity 5 or more. That is the full extent of the side
  effect on QuantumBit.

### Attribute-based bands

`DEMO-CS-09` (the print module) is priced by a count it does not own: the full
plus light named users on the whole configuration. The CML model computes that,
turns it into a band, and writes the band to the module's `ENT_NAMED_USERS`
attribute; these rules then override the price from it.

| Rule | Band | Price |
|------|------|-------|
| — (list price) | `1-60` | EUR 180 |
| `ENT-PRINT-M` | `61-120` | EUR 280 |
| `ENT-PRINT-L` | `121+` | EUR 420 |

The lowest band is the price book entry itself, so it needs no rule. The bands
are mutually exclusive, so one condition per rule is enough — which is as many
as a rule may have for a given product and attribute.

**The bands are picklist values, not numbers.** `AttributeAdjustmentCondition`
accepts only the `equals` operator ("You can only use the Equals operator with
Attribute Adjustment Condition"), whatever its nine-value `Operator` picklist
suggests, so a threshold like `greaterorequal 61` is not expressible. The
banding therefore happens in CML and these rules match a band by name on
`StringValue`. The attribute must also be price-impacting on the product before
any condition referencing it will insert.

**`AttributeBasedAdjustment` is mostly read-only.** Only nine of its fields are
writable; `AttributeCount`, `ScheduleType`, `SellingModelType`, `PricingTerm`,
`PricingTermUnit` and `AttributeAdjConditionsHash` are all computed by the
platform from the rule's conditions. The hash is how the engine matches a
configured line to an adjustment, which makes the load order load-bearing:
`AttributeAdjustmentCondition` must come **before** `AttributeBasedAdjustment`,
or the hash is derived from no conditions and the band never fires. Verified by
inserting a known QuantumBit condition and watching the platform reproduce its
existing hash exactly.

`EffectiveFrom` must also fall inside the parent schedule's own effective range,
or the insert fails with `FIELD_INTEGRITY_EXCEPTION`.

### Derived support

Three Censhare support products are a percentage of a base:

| Product | Rate | Base |
|---------|------|------|
| `DEMO-CS-22` Application Support Gold | 7% | monthly Software lines |
| `DEMO-CS-23` Application Support Platinum | 10% | monthly Software lines |
| `DEMO-CS-24` Cloud Ops & Support (Core) | 5% | monthly Infrastructure lines |

Each gets one `PricebookEntryDerivedPrice` row **per contributing product**,
all carrying `PERCENTAGE(TotalPrice,<rate>)`; the engine sums the
per-contributor results. Contributors are the products the workbook marks as
"Included in support basis", restricted to the same billing period and product
family. That gives 12 rows each for Gold and Platinum (the monthly Software
products `DEMO-CS-01` to `-12`) and 5 for Cloud Ops (`DEMO-CS-15` to `-19`).

Epoq's `DEMO-EQ-05` and `DEMO-EQ-06` use the same workbook mechanism and so get
8 more rows for free. They are not part of Act 2 — Epoq support is Act 5 — but
they cost nothing and are generated from the same rule.

The workbook also gives each support product a floor (EUR 90, 140 and 30), and
**this plan does not model it**. Derived pricing has no concept of a minimum,
and Revenue Cloud offers no substitute: a derived product's price book entry
must carry a list price of 0, and Help says that both Formula Based Pricing and
the Discount Distribution Service — which owns the only built-in floor, Minimum
Net Unit Price — "doesn't support derived products on quote line items".
Support is a plain percentage, and the minimum is a talking point. The floor
bites on the Cloud Ops line of **both** Act 2 quotes, which price at EUR 17.00
(CS-01) and EUR 29.50 (CS-02) against a EUR 30.00 minimum. See the
[Act 2b runbook](../../../../../unpackaged/post_entirely/act2b-derived-pricing.md)
→ Design decisions.

Note that the percentage is taken on each contributor's **net** subtotal, not
its list price, so discounting a covered line lowers the support charge with it.
That is the engine's behaviour and is not configurable.

The `DerivedPricing` element itself does not ship in this plan either; it lives
in `datasets/expression_set_overlays/entirely_derived_support.json`. Without
that overlay the three support products price at **EUR 0** — as they also do
until the **Derived Pricing Entries** decision table is refreshed after this
plan loads.

<!-- generate_plan_readme:begin -->
<!-- Generated by scripts/ai/generate_plan_readme.py from export.json + CSVs.
     Regenerate with the same command after changing this plan's objects,
     operations, or externalIds rather than hand-editing this block — content
     outside these markers (narrative sections) is preserved on regeneration. -->

## Objects

| # | Object | Pass | Operation | External ID | Records |
|---|--------|------|-----------|-------------|---------|
| 1 | Product2 | 1 | Readonly | StockKeepingUnit | — |
| 2 | ProductSellingModel | 1 | Readonly | Name | — |
| 3 | AttributeDefinition | 1 | Readonly | Code | — |
| 4 | Pricebook2 | 1 | Readonly | Name | — |
| 5 | PriceAdjustmentSchedule | 1 | Readonly | Name | — |
| 6 | PricebookEntry | 1 | Upsert | Product2.StockKeepingUnit;ProductSellingModel.Name;CurrencyIsoCode | 93 |
| 7 | PriceAdjustmentTier | 1 | Upsert | PriceAdjustmentSchedule.Name;Product2.StockKeepingUnit;ProductSellingModel.Name;LowerBound;CurrencyIsoCode | 9 |
| 8 | AttributeBasedAdjRule | 1 | Upsert | Name | 2 |
| 9 | AttributeAdjustmentCondition | 1 | Upsert | AttributeBasedAdjRule.Name;AttributeDefinition.Code;Product.StockKeepingUnit | 2 |
| 10 | AttributeBasedAdjustment | 1 | Upsert | AttributeBasedAdjRule.Name;PriceAdjustmentSchedule.Name;Product.StockKeepingUnit;ProductSellingModel.Name;CurrencyIsoCode | 2 |
| 11 | PricebookEntryDerivedPrice | 1 | Upsert | Product.StockKeepingUnit;ContributingProduct.StockKeepingUnit;ProductSellingModel.Name;CurrencyIsoCode | 37 |

## Required source CSVs

<!-- Only CSVs a live-writable declaration must load. A source-free declaration's CSV
     is not required and is omitted here even if one ships: a Readonly/Delete object
     resolves from the target org, and an excluded object is skipped entirely before
     load. -->

```
PricebookEntry.csv                       # 93 records
PriceAdjustmentTier.csv                  # 9 records
AttributeBasedAdjRule.csv                # 2 records
AttributeAdjustmentCondition.csv         # 2 records
AttributeBasedAdjustment.csv             # 2 records
PricebookEntryDerivedPrice.csv           # 37 records
```
<!-- generate_plan_readme:end -->

## Loading

```bash
sf sfdmu run --sourceusername csvfile --targetusername Entirely \
    --path datasets/sfdmu/entirely/en-US/entirely-pricing
```

Every live-writable object is `Upsert` with `;` externalIds, so the plan is
idempotent. Lookup reference columns are single fields rather than `$$`
composites (SFDMU v5 Bug 4).

`Product2`, `ProductSellingModel`, `AttributeDefinition`, `Pricebook2` and
`PriceAdjustmentSchedule` are `Readonly` — the plan resolves them for lookups
and never writes them. In particular it does **not** create or activate a
schedule; the two it uses are the platform's own.

After loading, refresh the pricing decision tables so the new entries are
visible to the procedures:

```bash
cci task run refresh_dt_default_pricing --org entirely
cci task run refresh_dt_pricing_discovery --org entirely
```

## Verifying

`scripts/entirely/check_quote_totals.py` compares a live quote line by line
against `scripts/entirely/expected_quotes.json`, which is generated from the
same workbook.

Without the derived-support overlay the three support products price at EUR 0,
so exclude them and verify the rest of the plan on its own: `DEMO-CS-01` comes
to **EUR 25,912.00** for the first 12 months and `DEMO-CS-02`, with the user
band seeded to `121+`, to **EUR 52,168.00**. Both are verified step by step in
the [Act 2a runbook](../../../../../unpackaged/post_entirely/act2a-pcm-and-pricing.md).
Once the overlay is applied and the Derived Pricing Entries decision table is
refreshed, Gold prices at EUR 121.52 (7% of EUR 1,736) and CS-01 reaches
EUR 27,574.24; Platinum prices at EUR 350.40 (10% of EUR 3,504) and CS-02
reaches EUR 56,726.80. Both are verified in the
[Act 2b runbook](../../../../../unpackaged/post_entirely/act2b-derived-pricing.md).

## Related

- [Act 2a runbook](../../../../../unpackaged/post_entirely/act2a-pcm-and-pricing.md) — load and validate the list prices and both band mechanisms step by step
- [Act 2b runbook](../../../../../unpackaged/post_entirely/act2b-derived-pricing.md) — apply the overlay, refresh the table and validate support pricing
- [entirely-pcm](../entirely-pcm/README.md) — products, catalog, bundle, attributes
- `datasets/expression_set_overlays/entirely_derived_support.json` — the Derived Pricing element
- `scripts/entirely/workbook_to_sfdmu.py` — the generator
- `.cursor/skills/sfdmu-data-plans/SKILL.md` — plan authoring rules
