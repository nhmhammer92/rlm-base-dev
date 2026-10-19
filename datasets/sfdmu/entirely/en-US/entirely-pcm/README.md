# entirely-pcm Data Plan

Product catalogue for the **Entirely AG** demo: 92 demo products across six
product families, plus the `DEMO-CS-CLOUD` **Censhare Cloud** bundle that Act 2
configures. Companion plan: [entirely-pricing](../entirely-pricing/README.md),
which carries the EUR prices and the adjustment bands. Load this plan first —
`entirely-pricing` resolves `Product2` and `AttributeDefinition` from it.

> Every price, code, band and configuration rule in this plan is **fictional
> demo data**. Product names come from the Entirely AG catalogue; the
> commercial settings are invented for demo preparation and state nothing about
> real product availability, compatibility or pricing.

## Generated, not hand-written

Both Entirely plans are generated from the demo workbook:

```bash
python scripts/entirely/workbook_to_sfdmu.py --workbook "<the .xlsx>"
```

The workbook itself is **not committed**. Edit the generator, not the CSVs: a
hand-edit is silently reverted by the next run. `--check` re-adds the
workbook's own line totals and compares them against its headline figures, so a
workbook change that would break a proof point fails before anything is written.

## What the plan builds

| Area | Contents |
|------|----------|
| Products | 92 workbook products (`DEMO-CS-*`, `DEMO-MM-*`, `DEMO-FL-*`, `DEMO-EL-*`, `DEMO-EQ-*`, `DEMO-OS-*`) plus the `DEMO-CS-CLOUD` bundle root. SKU is the demo code; the selling unit and demo note go in `Description`. |
| Selling models | One `ProductSellingModelOption` per product, mapped from the workbook's billing period: Monthly → `Term Monthly`, Annual → `Term Annual`, One-time → `One-Time`. All three already exist in the org, so `ProductSellingModel` is `Readonly`. |
| Catalog | The `Entirely` sales catalog (`CAT-ENTIRELY`) with one navigational category per product family, and every product filed in its family. |
| Bundle | The Censhare Cloud bundle: 11 component groups and 26 components. |
| Sizing attributes | Two read-only integers the CML model writes, and the classification that carries them. |

### The Censhare Cloud bundle

`DEMO-CS-CLOUD` is a deliberately **neutral root**: the plan itself
(Professional or Enterprise) is a component, not the root product. Act 7
amends this quote to the Enterprise plan, and swapping a *component* is an
ordinary configuration change where swapping the *root* would be a disallowed
bundle swap.

Groups in configurator order. A group with a maximum of 1 is a pick-one set:

| Group | Pick | Members |
|-------|------|---------|
| Plan | exactly 1 | `DEMO-CS-01` Professional (default), `DEMO-CS-02` Enterprise |
| Named Users | any | full, light and development users |
| Translation | any | base pack, additional language, interface |
| Modules and APIs | any | print module, Headless CMS APIs, Content Picker, connector bundle, `QB-DB` |
| Syndication | any | PIM Syndication, Connection 5-pack |
| Infrastructure | any | production environment, app server, storage |
| Test Environment | at most 1 | size M (`DEMO-CS-16`) or size L (`DEMO-CS-17`) |
| Application Support | at most 1 | Gold (`DEMO-CS-22`) or Platinum (`DEMO-CS-23`) |
| Cloud Operations | any | `DEMO-CS-24` |
| System Setup | at most 1 | size M (`DEMO-CS-20`) or size L (`DEMO-CS-21`) |
| Services | any | Technical Consulting |

The bundle mixes monthly, annual and one-time children on purpose — that is
what CS-05 demonstrates, and `QB-COMPLETE` already proves the org supports it.
Setup and services sit in their own groups so the one-time charges stay visually
apart from the recurring ones.

**`QB-DB` is the usage component.** It is QuantumBit's metered product, carried
in this plan's `Product2.csv` under its Censhare name, "Headless CMS API Usage".
Its **SKU is unchanged** — every usage script in the repo keys on `QB-DB` — and
no other plan owns the record, so naming it here is safe. It has to have a row:
a SKU that `ProductRelatedComponent.csv` references but `Product2.csv` omits is
synthesised by SFDMU as an all-empty row and fails on write.

It joins the bundle with `DoesBundlePriceIncludeChild = true`, so it adds at
EUR 0 inside the bundle, bringing its allowances and overage rates onto the
quote without changing the CS-01 total. Its own price book entries keep
QuantumBit's prices, which the QuantumBit demos still need. A CML `require` rule
pulls it in whenever Headless CMS APIs is selected.

> **That flag is insert-only.** Setting it on an existing component fails with
> "Quantity can't be changed when the bundle price includes the component
> price", and blanking `Quantity` to satisfy that fails with "Enter a positive
> number". A row loaded with the wrong value must be deleted and reloaded.

### Sizing attributes

| Attribute | On | Type | Purpose |
|-----------|----|------|---------|
| `ENT_TOTAL_NAMED_USERS` | `DEMO-CS-CLOUD` | Number | The live counter: full plus light named users. The CML model computes it. |
| `ENT_NAMED_USERS` | `DEMO-CS-09` | Picklist `ENT-USER-BAND` | The band that count falls into (`1-60`, `61-120`, `121+`), labelled "User band". **Price-impacting** — it drives the attribute-based band in `entirely-pricing`. |

Both are read-only so a rep cannot type over the configurator's answer.

The band is a picklist rather than the headcount itself because
`AttributeAdjustmentCondition` accepts only the `equals` operator, whatever its
`Operator` picklist offers — a threshold such as `NamedUsers >= 61` cannot be
expressed. So the CML model does the banding and pricing matches a band by name,
the same way `ATTR-QB-API` works.

Four things have to line up or the attribute inserts fail: a visible read-only
attribute needs a `DefaultValue`; `ProductAttributeDefinition` requires its
`ProductClassificationAttributeId`; the product's `BasedOn.Code` must equal that
classification's; and `Sequence` must mirror the classification attribute's.
`AttributeDefinition.DataType` and `PicklistId`, meanwhile, are fixed at
creation — an upsert that changes them reports success and quietly keeps the old
values. Run `scripts/apex/entirely/act2_reset_attributes.apex` before reloading
if an attribute's type ever changes.

<!-- generate_plan_readme:begin -->
<!-- Generated by scripts/ai/generate_plan_readme.py from export.json + CSVs.
     Regenerate with the same command after changing this plan's objects,
     operations, or externalIds rather than hand-editing this block — content
     outside these markers (narrative sections) is preserved on regeneration. -->

## Objects

| # | Object | Pass | Operation | External ID | Records |
|---|--------|------|-----------|-------------|---------|
| 1 | AttributePicklist | 1 | Upsert | Code | 1 |
| 2 | AttributePicklistValue | 1 | Upsert | Picklist.Code;Code | 3 |
| 3 | AttributeDefinition | 1 | Upsert | Code | 2 |
| 4 | AttributeCategory | 1 | Upsert | Code | 1 |
| 5 | AttributeCategoryAttribute | 1 | Upsert | AttributeCategory.Code;AttributeDefinition.Code | 2 |
| 6 | ProductClassification | 1 | Upsert | Code | 1 |
| 7 | ProductClassificationAttr | 1 | Upsert | Name | 2 |
| 8 | Product2 | 1 | Upsert | StockKeepingUnit | 94 |
| 9 | ProductAttributeDefinition | 1 | Upsert | AttributeDefinition.Code;Product2.StockKeepingUnit | 4 |
| 10 | ProductSellingModel | 1 | Readonly | Name | — |
| 11 | ProductSellingModelOption | 1 | Upsert | Product2.StockKeepingUnit;ProductSellingModel.Name | 93 |
| 12 | ProductRelationshipType | 1 | Readonly | Name | — |
| 13 | ProductComponentGroup | 1 | Upsert | Code | 11 |
| 14 | ProductRelatedComponent | 1 | Upsert | ChildProduct.StockKeepingUnit;ParentProduct.StockKeepingUnit;ProductComponentGroup.Code;ProductRelationshipType.Name | 26 |
| 15 | ProductCatalog | 1 | Upsert | Code | 1 |
| 16 | ProductCategory | 1 | Upsert | Code | 6 |
| 17 | ProductCategoryProduct | 1 | Upsert | ProductCategory.Code;Product.StockKeepingUnit | 93 |

## Required source CSVs

<!-- Only CSVs a live-writable declaration must load. A source-free declaration's CSV
     is not required and is omitted here even if one ships: a Readonly/Delete object
     resolves from the target org, and an excluded object is skipped entirely before
     load. -->

```
AttributePicklist.csv                    # 1 record
AttributePicklistValue.csv               # 3 records
AttributeDefinition.csv                  # 2 records
AttributeCategory.csv                    # 1 record
AttributeCategoryAttribute.csv           # 2 records
ProductClassification.csv                # 1 record
ProductClassificationAttr.csv            # 2 records
Product2.csv                             # 94 records
ProductAttributeDefinition.csv           # 4 records
ProductSellingModelOption.csv            # 93 records
ProductComponentGroup.csv                # 11 records
ProductRelatedComponent.csv              # 26 records
ProductCatalog.csv                       # 1 record
ProductCategory.csv                      # 6 records
ProductCategoryProduct.csv               # 93 records
```
<!-- generate_plan_readme:end -->

## Loading

```bash
sf sfdmu run --sourceusername csvfile --targetusername Entirely \
    --path datasets/sfdmu/entirely/en-US/entirely-pcm
```

Every live-writable object is `Upsert` with `;` externalIds, so the plan is
idempotent: loading it twice produces no duplicates. Lookup reference columns
use single fields (`ProductSellingModel.Name`, `ProductComponentGroup.Code`)
rather than `$$` composites, which SFDMU cannot decompose for a lookup
(SFDMU v5 Bug 4). The `$$` first column of each CSV is the Upsert matching key
and is unaffected by that bug.

`ProductSellingModel` and `ProductRelationshipType` are `Readonly`: the org
already ships them, and the plan only needs them resolved for parent lookups.

After loading, rebuild the catalog search index or the new products will not
appear in the product browser:

```bash
cci task run rebuild_search_index --org entirely
```

## Related

- [Act 2a runbook](../../../../../unpackaged/post_entirely/act2a-pcm-and-pricing.md) — load and validate this plan step by step
- [entirely-pricing](../entirely-pricing/README.md) — EUR prices, bands, derived support
- `datasets/constraints/entirely/CenshareCloud/` — the CML model that drives the counter and the blocking rules
- `scripts/entirely/workbook_to_sfdmu.py` — the generator
- `.cursor/skills/sfdmu-data-plans/SKILL.md` — plan authoring rules
