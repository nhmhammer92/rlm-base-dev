# Act 2c: the Censhare constraint model (CML)

Part of the [Entirely demo](README.md). The third of Act 2's three pieces:

| Piece | Covers | File |
| ----- | ------ | ---- |
| 2a | Catalog, bundle structure, attributes, standard EUR pricing | [act2a-pcm-and-pricing.md](act2a-pcm-and-pricing.md) |
| 2b | Derived support pricing (percentage of a base) | [act2b-derived-pricing.md](act2b-derived-pricing.md) |
| **2c** | **Constraint model (CML): the live counter, the band, the blocking rules** | **this file** |

2c is the only piece that needs the configurator. It takes the bundle 2a built
and the prices 2b completed, and makes the configurator compute two things the
rep never types: how many named users the configuration carries, and which price
band the print module falls into.

## Story

Kestrel's rollout is sized by named users, and three things follow from that
number. The rep adds users; the configurator does the rest.

| What the rep does | What the configurator does |
| ----------------- | -------------------------- |
| Adds full and light named users | Counts them live on the bundle — **Total named users** |
| Nothing | Bands that count and prices Cloud Print Prod. Mgmt by the band |
| Adds extra translation languages | Blocks, until the Translation base pack is there |
| Adds the Headless CMS Content Picker | Blocks, until Headless CMS - APIs is there |
| Adds Headless CMS - APIs | Adds the metered API usage line for them |
| Crosses 100 users on a Size M environment | Warns to move to Size L |

## How it works

One constraint model, `CenshareCloud`, in
[`datasets/constraints/entirely/CenshareCloud/`](../../datasets/constraints/entirely/CenshareCloud/).
Its CML is `blobs/ESDV_CenshareCloud_V1.ffxblob`; the CSVs beside it carry the
`ExpressionSet` records and the 53 `ExpressionSetConstraintObj` rows (27 Type,
26 Port) that bind each bundle member to a CML type.

Two product attributes carry the computed values, both read-only, both from
2a's `PC-ENT-CENSHARE-CLOUD` classification:

| Attribute | Developer name | On | Set by |
| --------- | -------------- | -- | ------ |
| Total named users | `ENT_Named_User_Count` | `DEMO-CS-CLOUD` | `fullUsers[FullNamedUser] + lightUsers[LightNamedUser]` |
| User band | `ENT_User_Band` | `DEMO-CS-09` | three implication constraints on the count |

`relation[Type]` counts line **quantity**, not instances, so one Full Named User
line with quantity 90 contributes 90.

The band is a picklist (`1-60`, `61-120`, `121+`) rather than the number itself
because an attribute-based price adjustment accepts only the `equals` operator —
see [act2a-pcm-and-pricing.md](act2a-pcm-and-pricing.md). CML does the banding
and the price adjustment matches a band by name.

The three rules that stop a rep are written as `message(..., "Error")`, not as
`constraint(A -> B)`. A constraint of that shape is resolved by the engine
**adding** B silently, which is the opposite of what the demo wants to show. The
one rule that should add something — the metered usage line behind the Headless
CMS APIs — stays a `require()`.

## Setup

After 2a and 2b, once per org. Replace `EntirelyQB` with your own aliases; note
that `import_cml` takes a **CCI** org alias and everything else takes an `sf`
alias.

```bash
# 1. Check the model offline first (expect 0 errors).
cci task run validate_cml --data_dirs datasets/constraints/entirely/CenshareCloud

# 2. Free QB-DB. A product may be typed by only ONE active constraint model, and
#    QuantumBitBundle types QB-DB, which this bundle reuses as the metered usage
#    line. Deactivate QuantumBitBundle in Constraint Builder (Setup -> Constraint
#    Models). Server2 may stay active; it shares no products with this bundle.

# 3. Import the model, the ESC wiring and the blob.
cci task run import_cml --org entirelyqb --data_dir datasets/constraints/entirely/CenshareCloud

# 4. Activate CenshareCloud V1 in Constraint Builder.
```

Steps 2 and 4 are **UI steps on purpose**.
`scripts/expression_sets/activate_expression_set.py` only PATCHes
`ExpressionSetVersion.IsActive`; for a constraint model that flips a field
without running the product-overlap check or deploying the model to the
configurator runtime. The result looks activated and runs nothing. The same
applies to every later change: **deactivate in the UI, `import_cml`, activate in
the UI.** `import_cml` on its own uploads a blob that is never deployed.

If step 4 reports *"The constraint model contains products that are included in
other active models"*, step 2 was skipped or another model was activated since.
The message names both the product Id and the model Id to deactivate.

## Validate

### Headless, in about two minutes

The configure endpoint runs the model against an existing quote without opening
a browser, which is also the quickest way to see a model error.

```bash
B="python scripts/entirely/build_test_quote.py --target-org EntirelyQB"

# A. 90 + 50 named users: the top band.
$B --expect DEMO-CS-02 --bundle DEMO-CS-CLOUD --run-config-rules --replace

# B. 40 + 15 named users: the bottom band.
$B --expect DEMO-CS-01 --bundle DEMO-CS-CLOUD --run-config-rules --replace
```

Read the computed values and the banded price off the quote:

```bash
sf data query --target-org EntirelyQB -q "SELECT QuoteLineItem.Product2.StockKeepingUnit, \
  AttributeDefinition.DeveloperName, AttributeValue FROM QuoteLineItemAttribute \
  WHERE QuoteLineItem.Quote.Name LIKE 'DEMO-CS-0%'"
```

| Check | Expected |
| ----- | -------- |
| A | `ENT_Named_User_Count` **140** on `DEMO-CS-CLOUD`, `ENT_User_Band` **121+** on `DEMO-CS-09`, which prices at **EUR 5,040** (420 x 12) |
| B | **55** and **1-60**, `DEMO-CS-09` at **EUR 2,160** (180 x 12) |
| Both | A `QB-DB` line appears that nobody added — the `require()` rule |

To check the rules, delete a line from the placed quote and re-run the
configurator against the bundle root:

```bash
cat > /tmp/configure.json <<'JSON'
{"transactionLineId": "<bundle root QuoteLineItem Id>",
 "transactionId": "<Quote Id>",
 "correlationId": "entirely-2c",
 "configuratorOptions": {"executeConfigurationRules": true, "validateProductCatalog": false}}
JSON
sf api request rest "/services/data/v68.0/connect/cpq/configurator/actions/configure" \
  --method POST --body @/tmp/configure.json --header "Content-Type:application/json" \
  --target-org EntirelyQB
```

| Line deleted from the CS-02 quote | Expected in `messages` |
| --------------------------------- | ---------------------- |
| `DEMO-CS-06` Translation base pack | error, *"Additional languages need the Translation base pack"*, and the base pack is **not** re-added |
| `DEMO-CS-10` Headless CMS - APIs | error, *"Content Picker runs on Headless CMS APIs"*, and nothing is added |

For the warnings, take the CS-01 quote (Size M environment and Size M setup) and
raise `DEMO-CS-03` to 95: at 110 users both sizing warnings appear and the band
moves to `61-120`.

### In the browser

1. Open the CS-01 quote and configure **Censhare Cloud**.
2. Set Full Named Users to 90 and Light Named Users to 61. **Total named users
   reads 151**, counting up as you type, and nobody can edit it.
3. The Summary prices **Cloud Print Prod. Mgmt at EUR 420**, tagged with the
   band it matched. Drop the users back under 60 and it returns to EUR 180.
4. Add an **Additional Language** without the Translation base pack. A red
   banner blocks you, and the base pack is not added for you. Add the base pack
   and the banner clears.
5. Add the **Content Picker** without Headless CMS - APIs: the same. Add
   Headless CMS - APIs and watch the metered usage line appear on its own.
6. With more than 100 users, switch to the **Size M** test environment: a yellow
   warning suggests Size L.

## Design decisions

**The band lives only on the product it prices.** Deriving it on the bundle as
well, next to the count, does not work: the band's condition is a count built
from relation cardinality, so the engine satisfies the rule by rewriting the
user quantities instead of the band, and gives up at the 15-second solver limit
with *"There's a goal execution error in your CML code: Require(IntComparison(GT,
[IntVar(ENT_Named_User_Count=),IntConst(120)]), ...)"*. `peelable`, `sequence`
and `domainComputation` were each tried on top of the band and none of them
moved the engine off that choice point. On `DEMO-CS-09` the count arrives
through `parent()` as a propagated value, there is no cardinality to search, and
the same three constraints resolve in single-digit milliseconds.

**Both products hide the other's attribute.** `DEMO-CS-CLOUD` and `DEMO-CS-09`
share one classification, and a classification attribute surfaces on every
product based on it. Without the two `IsHidden` rows that
`scripts/entirely/workbook_to_sfdmu.py` writes, the bundle would show a band
stuck at "1-60 users" beside a count of 151, and the print module a count of 0
beside the band that prices it.

**`QB-DB` is reused, not renamed in Apex.** It is the metered usage line for the
Headless CMS APIs, carried in 2a's `Product2.csv` under its Censhare name with
its SKU untouched, so Act 7's usage scripts keep working. The cost is that
`QuantumBitBundle` has to be deactivated: one product, one active model.

## Known issues

- **The configurator runs no model at all.** The version was activated with
  `activate_expression_set.py` rather than in the UI. Deactivate and reactivate
  in Constraint Builder; `RLM_CONFIGURATOR_STATS` stays empty until you do.
- **A model change has no effect.** `import_cml` was run without the UI
  deactivate and activate around it.
- **No `RLM_CONFIGURATOR_*` sections in the debug log.** The dev guide says
  `FINE`; the sections only appear at `FINEST`.
- **The band is right but the price is not.** The attribute-based adjustment or
  its decision table is stale — see
  [act2a-pcm-and-pricing.md](act2a-pcm-and-pricing.md).

## Gate for Act 3

Checks A and B pass with the figures above, both blocking rules return an error
without adding anything, and the solver reports 0 backtracks and 0 violations in
`RLM_CONFIGURATOR_STATS`.
