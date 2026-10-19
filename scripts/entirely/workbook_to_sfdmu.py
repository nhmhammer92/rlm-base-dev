#!/usr/bin/env python3
"""Generate the Entirely SFDMU data plans from the demo workbook.

Reads the demo catalogue workbook (``.xlsx``) with the standard library only —
no ``openpyxl`` — and writes:

* ``datasets/sfdmu/entirely/en-US/entirely-pcm/``     product catalogue + bundle
* ``datasets/sfdmu/entirely/en-US/entirely-pricing/`` EUR prices + adjustments
* ``scripts/entirely/expected_quotes.json``           the workbook's own totals

The workbook itself is never committed. Every price, code and rule in it is
fictional demo data.

Usage::

    python scripts/entirely/workbook_to_sfdmu.py --workbook <path to .xlsx>
    python scripts/entirely/workbook_to_sfdmu.py --workbook <path> --check
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from decimal import Decimal
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PCM_DIR = REPO / "datasets/sfdmu/entirely/en-US/entirely-pcm"
PRICING_DIR = REPO / "datasets/sfdmu/entirely/en-US/entirely-pricing"
EXPECTED_QUOTES = Path(__file__).resolve().parent / "expected_quotes.json"

CURRENCY = "EUR"
PRICEBOOK = "Standard Price Book"
CATALOG_CODE = "CAT-ENTIRELY"
CATALOG_NAME = "Entirely"
ROOT_SKU = "DEMO-CS-CLOUD"
ROOT_NAME = "Censhare Cloud"
REL_TYPE = "Bundle to Bundle Component Relationship"
VOLUME_SCHEDULE = "Standard Price Adjustment Tier"
ATTRIBUTE_SCHEDULE = "Standard Attribute Based Adjustment"

# Adjustment and tier rows must sit inside the schedule's own effective range,
# which starts 2023-01-01 (FIELD_INTEGRITY_EXCEPTION otherwise).
EFFECTIVE_FROM = "2024-01-01T00:00:00.000+0000"

# A derived-price formula may only reference UnitPrice, TotalPrice, ListPrice and
# HeaderTotal — there is no quantity — and the engine reads its result as a *unit*
# price. The workbook's support base is the sum of the contributors' monthly line
# totals, and `TotalPrice` is a contributor's total over the whole term, so the
# formula divides by the term length to get back to a month. Every workbook quote
# runs a 12-month term; a longer one would need this changed with it.
SUPPORT_TERM_MONTHS = 12

# Workbook billing period -> selling model. The org ships all three.
SELLING_MODEL = {
    "Monthly": "Term Monthly",
    "Annual": "Term Annual",
    "One-time": "One-Time",
}

# Product family -> product category code in the Entirely catalog.
FAMILY_CATEGORY = {
    "Censhare": "PC-ENT-CENSHARE",
    "Marmind": "PC-ENT-MARMIND",
    "Facelift": "PC-ENT-FACELIFT",
    "Elaine": "PC-ENT-ELAINE",
    "Epoq": "PC-ENT-EPOQ",
    "Business OS": "PC-ENT-BUSINESSOS",
}

ATTR_TOTAL_USERS = "ENT_TOTAL_NAMED_USERS"
ATTR_NAMED_USERS = "ENT_NAMED_USERS"
# The CenshareCloud constraint model binds its variables to these developer names,
# so they must match the blob. A deleted AttributeDefinition keeps its developer
# name reserved, and a re-insert silently gets a numeric suffix the model does not
# match — never delete these to reload them; let the plan's Upsert update them.
# (ENT_Total_Named_Users / ENT_Named_Users are burnt on the Entirely org that way.)
DEV_TOTAL_USERS = "ENT_Named_User_Count"
DEV_NAMED_USERS = "ENT_User_Band"
BAND_PICKLIST = "ENT-USER-BAND"
# (stored value, label shown in the configurator), lowest band first.
USER_BANDS = [("1-60", "1–60 users"), ("61-120", "61–120 users"),
              ("121+", "121 or more users")]
CLASSIFICATION = "PC-ENT-CENSHARE-CLOUD"
ATTR_CATEGORY = "AC-ENT-SIZING"

# The Censhare Cloud bundle. Each entry is a component group on the root
# product: (code, name, min, max, sequence, [member SKUs]). A group with
# max 1 is a pick-one set.
BUNDLE_GROUPS = [
    ("PCG-ENT-PLAN", "Plan", 1, 1, 1, ["DEMO-CS-01", "DEMO-CS-02"]),
    ("PCG-ENT-USERS", "Named Users", 0, None, 2,
     ["DEMO-CS-03", "DEMO-CS-04", "DEMO-CS-05"]),
    ("PCG-ENT-TRANS", "Translation", 0, None, 3,
     ["DEMO-CS-06", "DEMO-CS-07", "DEMO-CS-08"]),
    ("PCG-ENT-MOD", "Modules and APIs", 0, None, 4,
     ["DEMO-CS-09", "DEMO-CS-10", "DEMO-CS-11", "DEMO-CS-12", "QB-DB"]),
    ("PCG-ENT-SYND", "Syndication", 0, None, 5,
     ["DEMO-CS-13", "DEMO-CS-14"]),
    ("PCG-ENT-INFRA", "Infrastructure", 0, None, 6,
     ["DEMO-CS-15", "DEMO-CS-18", "DEMO-CS-19"]),
    ("PCG-ENT-INFRA-TEST", "Test Environment", 0, 1, 7,
     ["DEMO-CS-16", "DEMO-CS-17"]),
    ("PCG-ENT-SUPP", "Application Support", 0, 1, 8,
     ["DEMO-CS-22", "DEMO-CS-23"]),
    ("PCG-ENT-SUPP-OPS", "Cloud Operations", 0, None, 9, ["DEMO-CS-24"]),
    ("PCG-ENT-SETUP", "System Setup", 0, 1, 10,
     ["DEMO-CS-20", "DEMO-CS-21"]),
    ("PCG-ENT-SERVICES", "Services", 0, None, 11, ["DEMO-CS-25"]),
]

# Components the configurator starts with, so adding the bundle lands on the
# CS-01 shape without hunting through every group.
DEFAULT_COMPONENTS = {"DEMO-CS-01"}

# QB-DB rides along at no charge; Act 7 drives its consumption.
BUNDLE_PRICE_INCLUDES = {"QB-DB"}

# Attribute-based price bands for the print module, keyed by the band value the
# CML model writes. The lowest band equals the list price and so needs no rule.
#
# One condition per rule: the platform rejects a second condition on the same
# product and attribute within a rule ("Ensure that the relationship between the
# Product, the Attribute Definition, and an adjustment rule is unique"). The
# bands are mutually exclusive, so one `equals` each is enough.
PRINT_BANDS = [
    ("ENT-PRINT-M", "61-120", 280),
    ("ENT-PRINT-L", "121+", 420),
]


# --------------------------------------------------------------------------
# workbook reading (standard library only)
# --------------------------------------------------------------------------

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RELNS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _col_index(ref: str) -> int:
    letters = "".join(c for c in ref if c.isalpha())
    n = 0
    for c in letters:
        n = n * 26 + ord(c) - 64
    return n - 1


class Workbook:
    """A read-only .xlsx reader built on zipfile and ElementTree."""

    def __init__(self, path: Path):
        self.zip = zipfile.ZipFile(path)
        self.shared = [
            "".join(t.text or "" for t in si.iter(NS + "t"))
            for si in ET.fromstring(self.zip.read("xl/sharedStrings.xml"))
        ]
        rels = {
            r.get("Id"): r.get("Target")
            for r in ET.fromstring(self.zip.read("xl/_rels/workbook.xml.rels"))
        }
        book = ET.fromstring(self.zip.read("xl/workbook.xml"))
        self.sheets = {
            sheet.get("name"): rels[sheet.get(RELNS + "id")]
            for sheet in book.find(NS + "sheets")
        }

    def rows(self, sheet_name: str) -> list[list[str]]:
        target = self.sheets[sheet_name].lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        root = ET.fromstring(self.zip.read(target))
        out: list[list[str]] = []
        for row in root.iter(NS + "row"):
            cells: dict[int, str] = {}
            for c in row.iter(NS + "c"):
                inline = c.find(NS + "is")
                value = c.find(NS + "v")
                if inline is not None:
                    text = "".join(t.text or "" for t in inline.iter(NS + "t"))
                elif value is None:
                    text = ""
                elif c.get("t") == "s":
                    text = self.shared[int(value.text)]
                else:
                    text = value.text or ""
                cells[_col_index(c.get("r"))] = text
            out.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
        return out

    def table(self, sheet_name: str, first_header: str) -> list[dict[str, str]]:
        """Rows as dicts, skipping the sheet's prose preamble."""
        rows = self.rows(sheet_name)
        header_idx = next(
            i for i, r in enumerate(rows) if r and r[0].strip() == first_header
        )
        header = [h.strip() for h in rows[header_idx]]
        table = []
        for row in rows[header_idx + 1:]:
            if not row or not row[0].strip():
                continue
            padded = list(row) + [""] * (len(header) - len(row))
            table.append({h: padded[i].strip() for i, h in enumerate(header) if h})
        return table


# --------------------------------------------------------------------------
# value helpers
# --------------------------------------------------------------------------

def money(value: str) -> str:
    """Normalise a workbook number, dropping float noise like 7.0000...E-2."""
    if value in ("", None):
        return ""
    d = Decimal(value).quantize(Decimal("0.0001")).normalize()
    return format(d, "f")


def rate_percent(value: str) -> str:
    """A support rate stored as a fraction (0.07) becomes a percentage (7)."""
    if not value:
        return ""
    return money(str(Decimal(value) * 100))


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


# --------------------------------------------------------------------------
# model
# --------------------------------------------------------------------------

class Catalogue:
    def __init__(self, book: Workbook):
        self.products = book.table("Demo catalogue", "Demo product code")
        self.rules = book.table("Pricing rules", "Demo pricing rule")
        self.quotes = book.table("Example quotes", "Quote ID")
        self.lines = book.table("Quote lines", "Quote ID")
        self.by_code = {p["Demo product code"]: p for p in self.products}

        self.bands: dict[str, list[dict[str, str]]] = {}
        for r in self.rules:
            self.bands.setdefault(r["Demo pricing rule"], []).append(r)
        for rows in self.bands.values():
            rows.sort(key=lambda r: int(r["From quantity"]))

    def selling_model(self, product: dict[str, str]) -> str:
        return SELLING_MODEL[product["Demo billing period"]]

    def list_price(self, product: dict[str, str]) -> str:
        """The price book entry price.

        Fixed products carry their own price. Banded products carry their
        first band, which the adjustment engine then overrides. Percentage
        support products are derived and carry zero.
        """
        model = product["Demo price model"]
        if model == "Percentage of base":
            return "0"
        if product["Demo unit price (EUR)"]:
            return money(product["Demo unit price (EUR)"])
        rule = product["Demo pricing rule"]
        if rule and rule in self.bands:
            return money(self.bands[rule][0]["Demo band price (EUR)"])
        return "0"

    def is_derived(self, product: dict[str, str]) -> bool:
        return product["Demo price model"] == "Percentage of base"


# --------------------------------------------------------------------------
# entirely-pcm
# --------------------------------------------------------------------------

def build_pcm(cat: Catalogue) -> None:
    out = PCM_DIR

    # --- Product2 ---------------------------------------------------------
    header = [
        "StockKeepingUnit", "Name", "ProductCode", "Description", "Family",
        "Type", "ConfigureDuringSale", "IsActive", "IsAssetizable",
        "IsSoldOnlyWithOtherProds", "BasedOn.Code",
    ]
    rows = [[
        ROOT_SKU, ROOT_NAME, ROOT_SKU,
        "Censhare Cloud subscription. Choose a plan, then add users, "
        "translation, modules, infrastructure, support and setup.",
        "Bundle", "Bundle", "Allowed", "true", "true", "false",
        CLASSIFICATION,
    ], [
        # QuantumBit's metered database product doubles as the bundle's usage
        # component, so this plan restates it under its Censhare name. No other
        # plan owns QB-DB, and naming it here rather than in Apex keeps the
        # child lookup in ProductRelatedComponent.csv resolvable — a SKU
        # referenced but absent from this CSV is synthesised by SFDMU as an
        # all-empty row and fails on write. The SKU itself must not change:
        # every usage script in the repo keys on it.
        "QB-DB", "Headless CMS API Usage", "QB-DB",
        "Metered usage for the Headless CMS APIs. Includes 10 TB of API cache "
        "storage a month. Delivery traffic and API compute are metered and "
        "charged on the rates shown on the line: delivery traffic per GB, "
        "compute per minute, and storage per TB above the included allowance.",
        "Software", "", "", "true", "true", "false", "",
    ]]
    for p in cat.products:
        note = p["Demo note"]
        unit = p["Demo selling unit"]
        description = f"Sold by: {unit}." + (f" {note}" if note else "")
        # Only the products that carry an attribute need a classification, and
        # the platform insists the two agree: a ProductAttributeDefinition is
        # rejected unless its product's BasedOnId matches the classification of
        # the ProductClassificationAttr it instantiates.
        rows.append([
            p["Demo product code"], p["Product name"], p["Demo product code"],
            description, p["Product family"], "", "NotAllowed", "true",
            "true", "false",
            CLASSIFICATION if p["Demo product code"] == "DEMO-CS-09" else "",
        ])
    write_csv(out / "Product2.csv", header, sorted(rows, key=lambda r: r[0]))

    # --- ProductSellingModelOption ---------------------------------------
    header = [
        "$$Product2.StockKeepingUnit$ProductSellingModel.Name",
        "Product2.StockKeepingUnit", "ProductSellingModel.Name", "IsDefault",
    ]
    rows = [[f"{ROOT_SKU};Term Monthly", ROOT_SKU, "Term Monthly", "true"]]
    for p in cat.products:
        sku, model = p["Demo product code"], cat.selling_model(p)
        rows.append([f"{sku};{model}", sku, model, "true"])
    write_csv(out / "ProductSellingModelOption.csv", header,
              sorted(rows, key=lambda r: r[0]))

    # --- catalog and categories ------------------------------------------
    write_csv(out / "ProductCatalog.csv",
              ["Code", "Name", "CatalogType", "Description"],
              [[CATALOG_CODE, CATALOG_NAME, "Sales",
                "Entirely AG demo catalog. Fictional demo data."]])

    categories = []
    for family, code in FAMILY_CATEGORY.items():
        categories.append([code, family, CATALOG_CODE, "true", ""])
    write_csv(out / "ProductCategory.csv",
              ["Code", "Name", "Catalog.Code", "IsNavigational", "SortOrder"],
              sorted(categories, key=lambda r: r[0]))

    header = [
        "$$ProductCategory.Code$Product.StockKeepingUnit", "Catalog.Code",
        "ProductCategory.Code", "Product.StockKeepingUnit", "IsPrimaryCategory",
    ]
    rows = []
    for p in cat.products:
        code = FAMILY_CATEGORY[p["Product family"]]
        sku = p["Demo product code"]
        rows.append([f"{code};{sku}", CATALOG_CODE, code, sku, "true"])
    root_cat = FAMILY_CATEGORY["Censhare"]
    rows.append([f"{root_cat};{ROOT_SKU}", CATALOG_CODE, root_cat, ROOT_SKU,
                 "true"])
    write_csv(out / "ProductCategoryProduct.csv", header,
              sorted(rows, key=lambda r: r[0]))

    # --- bundle groups and components ------------------------------------
    header = [
        "Code", "Name", "ParentProduct.StockKeepingUnit", "MinBundleComponents",
        "MaxBundleComponents", "Sequence", "Description",
    ]
    rows = [[code, name, ROOT_SKU, str(lo), "" if hi is None else str(hi),
             str(seq), ""]
            for code, name, lo, hi, seq, _ in BUNDLE_GROUPS]
    write_csv(out / "ProductComponentGroup.csv", header, rows)

    header = [
        "$$ChildProduct.StockKeepingUnit$ParentProduct.StockKeepingUnit"
        "$ProductComponentGroup.Code$ProductRelationshipType.Name",
        "ParentProduct.StockKeepingUnit", "ChildProduct.StockKeepingUnit",
        "ProductComponentGroup.Code", "ProductRelationshipType.Name",
        "ParentProductRole", "ChildProductRole", "Sequence",
        "IsComponentRequired", "IsDefaultComponent", "IsQuantityEditable",
        "DoesBundlePriceIncludeChild", "MinQuantity", "MaxQuantity",
        "Quantity", "QuoteVisibility",
    ]
    rows = []
    for code, _name, _lo, _hi, _seq, members in BUNDLE_GROUPS:
        for i, sku in enumerate(members, start=1):
            included = sku in BUNDLE_PRICE_INCLUDES
            rows.append([
                f"{sku};{ROOT_SKU};{code};{REL_TYPE}",
                ROOT_SKU, sku, code, REL_TYPE, "Bundle", "BundleComponent",
                str(i),
                "false",
                "true" if sku in DEFAULT_COMPONENTS else "false",
                # A component whose price the bundle already includes must have
                # a fixed quantity: the platform rejects an editable one
                # ("Quantity can't be changed when the bundle price includes
                # the component price"), and rejects a blank one outright.
                "false" if included else "true",
                "true" if included else "false",
                "", "", "1", "Always",
            ])
    write_csv(out / "ProductRelatedComponent.csv", header,
              sorted(rows, key=lambda r: r[0]))

    # --- sizing attributes -------------------------------------------------
    # Two read-only attributes the CML model writes: a live headcount on the
    # root, and the band that headcount falls into on the print module, which
    # drives its attribute-based price.
    #
    # The band is a picklist rather than the headcount itself because
    # AttributeAdjustmentCondition accepts only the `equals` operator ("You can
    # only use the Equals operator with Attribute Adjustment Condition"),
    # whatever the Operator picklist offers. A threshold such as
    # `NamedUsers >= 61` is therefore not expressible, so CML does the banding
    # and pricing matches the band by name.
    write_csv(out / "AttributeCategory.csv", ["Code", "Name", "Description"],
              [[ATTR_CATEGORY, "Sizing", "Censhare Cloud sizing counters."]])

    write_csv(out / "AttributePicklist.csv",
              ["Code", "Name", "DataType", "Status", "Description"],
              [[BAND_PICKLIST, "Entirely User Band", "Text", "Active",
                "Named-user bands that price the Censhare print module."]])

    write_csv(out / "AttributePicklistValue.csv",
              ["$$Picklist.Code$Code", "Picklist.Code", "Code", "Name",
               "Value", "DisplayValue", "Sequence", "IsDefault", "Status"],
              [[f"{BAND_PICKLIST};{value}", BAND_PICKLIST, value, value, value,
                label, str(i), "true" if i == 1 else "false", "Active"]
               for i, (value, label) in enumerate(USER_BANDS, start=1)])

    header = ["Code", "Name", "Label", "DeveloperName", "DataType",
              "Picklist.Code", "IsActive", "IsRequired", "Description"]
    write_csv(out / "AttributeDefinition.csv", header, [
        [ATTR_TOTAL_USERS, "Total named users",
         "Total named users", DEV_TOTAL_USERS, "Number", "", "true",
         "false", "Full plus light named users on the configuration."],
        [ATTR_NAMED_USERS, "User band", "User band", DEV_NAMED_USERS,
         "Picklist", BAND_PICKLIST, "true", "false",
         "Named-user band of the configuration, copied onto a module that "
         "prices by user count."],
    ])

    write_csv(out / "AttributeCategoryAttribute.csv",
              ["$$AttributeCategory.Code$AttributeDefinition.Code",
               "AttributeCategory.Code", "AttributeDefinition.Code"],
              [[f"{ATTR_CATEGORY};{code}", ATTR_CATEGORY, code]
               for code in sorted([ATTR_TOTAL_USERS, ATTR_NAMED_USERS])])

    write_csv(out / "ProductClassification.csv",
              ["Code", "Name", "Status", "ParentProductClassification.Code"],
              [[CLASSIFICATION, "Censhare Cloud", "Active", ""]])

    # A visible read-only attribute must carry a DefaultValue, or the insert
    # fails with "Enter a default value for an attribute that's visible and
    # read-only." The configurator overwrites it with the live count.
    header = ["Name", "ProductClassification.Code", "AttributeCategory.Code",
              "AttributeDefinition.Code", "DefaultValue", "IsPriceImpacting",
              "IsReadOnly", "IsRequired", "IsHidden", "Status", "Sequence"]
    write_csv(out / "ProductClassificationAttr.csv", header, [
        ["Total named users", CLASSIFICATION, ATTR_CATEGORY, ATTR_TOTAL_USERS,
         "0", "false", "true", "false", "false", "Active", "1"],
        ["User band", CLASSIFICATION, ATTR_CATEGORY, ATTR_NAMED_USERS,
         USER_BANDS[0][0], "true", "true", "false", "false", "Active", "2"],
    ])

    # ProductClassificationAttributeId is required: a product attribute is always
    # an instance of a classification attribute. The lookup goes by Name — a
    # single field, because `$$` composite notation does not resolve on a lookup
    # reference column (SFDMU v5 Bug 4).
    header = ["$$AttributeDefinition.Code$Product2.StockKeepingUnit",
              "Product2.StockKeepingUnit", "AttributeDefinition.Code",
              "AttributeCategory.Code", "ProductClassificationAttribute.Name",
              "Name", "DefaultValue", "IsPriceImpacting", "IsReadOnly",
              "IsRequired", "IsHidden", "Status", "Sequence"]
    # Sequence mirrors the classification attribute's: the platform rejects a
    # product attribute whose sequence is already taken on the classification.
    #
    # Four rows for two attributes. A classification attribute surfaces on every
    # product based on that classification, so each of these two products also
    # inherits the other's attribute. The CML model writes only one of them per
    # product (the count on the bundle, the band on the print module), so the
    # inherited copy would sit on the configurator screen at its default — a
    # band reading "1-60 users" beside a count of 151, and a count reading 0
    # beside the band that prices the line. The IsHidden rows suppress those.
    write_csv(out / "ProductAttributeDefinition.csv", header, [
        [f"{ATTR_TOTAL_USERS};{ROOT_SKU}", ROOT_SKU, ATTR_TOTAL_USERS,
         ATTR_CATEGORY, "Total named users", "Total named users", "0", "false",
         "true", "false", "false", "Active", "1"],
        [f"{ATTR_NAMED_USERS};{ROOT_SKU}", ROOT_SKU, ATTR_NAMED_USERS,
         ATTR_CATEGORY, "User band", "User band", USER_BANDS[0][0], "false",
         "true", "false", "true", "Active", "2"],
        [f"{ATTR_TOTAL_USERS};DEMO-CS-09", "DEMO-CS-09", ATTR_TOTAL_USERS,
         ATTR_CATEGORY, "Total named users", "Total named users", "0", "false",
         "true", "false", "true", "Active", "1"],
        [f"{ATTR_NAMED_USERS};DEMO-CS-09", "DEMO-CS-09", ATTR_NAMED_USERS,
         ATTR_CATEGORY, "User band", "User band", USER_BANDS[0][0], "true",
         "true", "false", "false", "Active", "2"],
    ])

    (out / "export.json").write_text(json.dumps(PCM_EXPORT, indent=2) + "\n")


# --------------------------------------------------------------------------
# entirely-pricing
# --------------------------------------------------------------------------

def build_pricing(cat: Catalogue) -> None:
    out = PRICING_DIR

    # --- price book entries ------------------------------------------------
    header = [
        "$$Product2.StockKeepingUnit$ProductSellingModel.Name$CurrencyIsoCode",
        "Product2.StockKeepingUnit", "ProductSellingModel.Name",
        "Pricebook2.Name", "CurrencyIsoCode", "UnitPrice", "IsActive",
        "IsDerived", "Name",
    ]
    rows = [[
        f"{ROOT_SKU};Term Monthly;{CURRENCY}", ROOT_SKU, "Term Monthly",
        PRICEBOOK, CURRENCY, "0", "true", "false", ROOT_NAME,
    ]]
    for p in cat.products:
        sku, model = p["Demo product code"], cat.selling_model(p)
        rows.append([
            f"{sku};{model};{CURRENCY}", sku, model, PRICEBOOK, CURRENCY,
            cat.list_price(p), "true",
            "true" if cat.is_derived(p) else "false", p["Product name"],
        ])
    write_csv(out / "PricebookEntry.csv", header,
              sorted(rows, key=lambda r: r[0]))

    # --- volume tiers ------------------------------------------------------
    # Every "Volume bands" rule becomes OverrideAmount tiers on the shared
    # Volume schedule, in EUR. Tiers are per currency: a USD-only tier never
    # fires on a EUR quote.
    header = [
        "$$PriceAdjustmentSchedule.Name$Product2.StockKeepingUnit"
        "$ProductSellingModel.Name$LowerBound$CurrencyIsoCode",
        "PriceAdjustmentSchedule.Name", "Product2.StockKeepingUnit",
        "ProductSellingModel.Name", "CurrencyIsoCode", "TierType",
        "AdjustmentType", "LowerBound", "UpperBound", "TierValue",
        "EffectiveFrom", "EffectiveTo",
    ]
    rows = []
    for p in cat.products:
        if p["Demo price model"] != "Volume bands":
            continue
        sku, model = p["Demo product code"], cat.selling_model(p)
        for band in cat.bands[p["Demo pricing rule"]]:
            lo = band["From quantity"]
            rows.append([
                f"{VOLUME_SCHEDULE};{sku};{model};{lo};{CURRENCY}",
                VOLUME_SCHEDULE, sku, model, CURRENCY, "OverrideAmount",
                "Override", lo, band["To quantity"],
                money(band["Demo band price (EUR)"]), EFFECTIVE_FROM, "",
            ])
    write_csv(out / "PriceAdjustmentTier.csv", header,
              sorted(rows, key=lambda r: (r[2], int(r[7]))))

    # --- attribute-based bands for the print module ------------------------
    # AttributeCount, ScheduleType, SellingModelType, PricingTerm and
    # AttributeAdjConditionsHash are all platform-computed and must not be
    # written. The conditions have to load before the adjustments so the hash
    # is derived from them.
    write_csv(out / "AttributeBasedAdjRule.csv", ["Name"],
              [[name] for name, _band, _v in PRINT_BANDS])

    header = ["$$AttributeBasedAdjRule.Name$AttributeDefinition.Code"
              "$Product.StockKeepingUnit",
              "AttributeBasedAdjRule.Name", "AttributeDefinition.Code",
              "Product.StockKeepingUnit", "Operator", "StringValue"]
    rows = [[
        f"{name};{ATTR_NAMED_USERS};DEMO-CS-09",
        name, ATTR_NAMED_USERS, "DEMO-CS-09", "equals", band,
    ] for name, band, _value in PRINT_BANDS]
    write_csv(out / "AttributeAdjustmentCondition.csv", header, rows)

    header = ["$$AttributeBasedAdjRule.Name$PriceAdjustmentSchedule.Name"
              "$Product.StockKeepingUnit$ProductSellingModel.Name"
              "$CurrencyIsoCode",
              "AttributeBasedAdjRule.Name", "PriceAdjustmentSchedule.Name",
              "Product.StockKeepingUnit", "ProductSellingModel.Name",
              "CurrencyIsoCode", "AdjustmentType", "AdjustmentValue",
              "EffectiveFrom", "EffectiveTo"]
    rows = [[
        f"{name};{ATTRIBUTE_SCHEDULE};DEMO-CS-09;Term Monthly;{CURRENCY}",
        name, ATTRIBUTE_SCHEDULE, "DEMO-CS-09", "Term Monthly", CURRENCY,
        "Override", str(value), EFFECTIVE_FROM, "",
    ] for name, _band, value in PRINT_BANDS]
    write_csv(out / "AttributeBasedAdjustment.csv", header, rows)

    # --- derived support prices -------------------------------------------
    # One row per support product per contributing product, each carrying the
    # support rate. The engine sums the per-contributor results.
    header = [
        "$$Product.StockKeepingUnit$ContributingProduct.StockKeepingUnit"
        "$ProductSellingModel.Name$CurrencyIsoCode",
        "PricebookEntry.$$Product2.StockKeepingUnit$ProductSellingModel.Name"
        "$CurrencyIsoCode",
        "Pricebook.Name", "Product.StockKeepingUnit",
        "ContributingProduct.StockKeepingUnit", "ProductSellingModel.Name",
        "CurrencyIsoCode", "PricingSource", "DerivedPricingScope", "Formula",
        "EffectiveFrom", "EffectiveTo",
    ]
    rows = []
    for p in cat.products:
        if not cat.is_derived(p):
            continue
        basis = p["Support calculation basis"]
        rate = rate_percent(p["Demo support rate"])
        sku, model = p["Demo product code"], cat.selling_model(p)
        for contributor in cat.products:
            if contributor["Included in support basis"] != basis:
                continue
            if contributor["Demo billing period"] != p["Demo billing period"]:
                continue
            if contributor["Product family"] != p["Product family"]:
                continue
            csku = contributor["Demo product code"]
            rows.append([
                f"{sku};{csku};{model};{CURRENCY}",
                f"{sku};{model};{CURRENCY}", PRICEBOOK, sku, csku, model,
                CURRENCY, "Product", "Both",
                f"PERCENTAGE(TotalPrice,{rate})/{SUPPORT_TERM_MONTHS}",
                EFFECTIVE_FROM, "",
            ])
    write_csv(out / "PricebookEntryDerivedPrice.csv", header,
              sorted(rows, key=lambda r: r[0]))

    (out / "export.json").write_text(json.dumps(PRICING_EXPORT, indent=2) + "\n")


# --------------------------------------------------------------------------
# expected quotes
# --------------------------------------------------------------------------

def unfloor_support(quotes: dict) -> None:
    """Restate each derived support line as base x rate, with no floor.

    The workbook's "Line total" for a support line is floored at EUR 30, which
    only bites on the two Cloud Ops lines. Nothing in the org enforces that
    floor: Help rules out every in-procedure mechanism for derived lines, so
    the Derived Pricing element returns the raw percentage. The workbook's
    "Support base" column already holds the net, post-adjustment base the
    element sums, so only the floor has to come off. Quote totals are then
    recomputed, since dropping it moves two of them.
    """
    for quote in quotes.values():
        for line in quote["lines"]:
            if line["priceModel"] != "Percentage of base":
                continue
            base = Decimal(line["supportBase"] or 0)
            rate = Decimal(line["supportRate"] or 0)
            line["lineTotal"] = money(
                str((base * rate / 100).quantize(Decimal("0.01"))))

        periods = {"Monthly": Decimal(0), "Annual": Decimal(0),
                   "One-time": Decimal(0)}
        for line in quote["lines"]:
            periods[line["billingPeriod"]] += Decimal(line["lineTotal"] or 0)
        quote["totals"] = {
            "monthly": money(str(periods["Monthly"])),
            "annual": money(str(periods["Annual"])),
            "oneTime": money(str(periods["One-time"])),
            "first12Months": money(str(periods["Monthly"] * 12
                                       + periods["Annual"]
                                       + periods["One-time"])),
        }


def build_expected_quotes(cat: Catalogue) -> dict:
    quotes: dict[str, dict] = {}
    for q in cat.quotes:
        quotes[q["Quote ID"]] = {
            "family": q["Product family"],
            "offer": q["Example offer"],
            "shows": q["What this offer shows"],
            "termMonths": 12,
            "currency": CURRENCY,
            "totals": {
                "monthly": money(q["Monthly charges (EUR)"]),
                "annual": money(q["Annual charges (EUR)"]),
                "oneTime": money(q["One-time charges (EUR)"]),
                "first12Months": money(q["First 12 months (EUR)"]),
            },
            "lines": [],
        }
    for line in cat.lines:
        quote = quotes.get(line["Quote ID"])
        if quote is None:
            continue
        quote["lines"].append({
            "sku": line["Demo product code"],
            "name": line["Product name"],
            "quantity": line["Demo quantity"],
            "pricingDriverQuantity": line["Pricing driver quantity"],
            "billingPeriod": line["Billing period"],
            "priceModel": line["Demo price model"],
            "unitPrice": money(line["Demo unit price (EUR)"]),
            "baseCharge": money(line["Base charge (EUR)"]),
            "supportBase": money(line["Support base (EUR)"]),
            "supportRate": rate_percent(line["Demo support rate"]),
            "lineTotal": money(line["Line total (EUR)"]),
            "supportBaseCategory": line["Support base category"],
        })

    unfloor_support(quotes)

    return {
        "source": "Salesforce demo catalogue and example quotes workbook",
        "note": "Fictional demo data. Regenerate with "
                "scripts/entirely/workbook_to_sfdmu.py. Support lines carry "
                "the workbook's base times its rate; the workbook's EUR 30 "
                "minimum is dropped, because the org applies no floor.",
        "currency": CURRENCY,
        "quotes": quotes,
    }


# --------------------------------------------------------------------------
# export.json documents
# --------------------------------------------------------------------------

PCM_EXPORT = {
    "objects": [
        {"query": "SELECT Code, DataType, Description, Id, Name, Status "
                  "FROM AttributePicklist WHERE Code = 'ENT-USER-BAND' "
                  "ORDER BY Code ASC",
         "operation": "Upsert", "externalId": "Code"},
        {"query": "SELECT Code, DisplayValue, Id, IsDefault, Name, PicklistId, "
                  "Picklist.Code, Sequence, Status, Value "
                  "FROM AttributePicklistValue "
                  "WHERE Picklist.Code = 'ENT-USER-BAND' ORDER BY Code ASC",
         "operation": "Upsert", "externalId": "Picklist.Code;Code"},
        {"query": "SELECT Code, DataType, Description, DeveloperName, Id, "
                  "IsActive, IsRequired, Label, Name, PicklistId, "
                  "Picklist.Code FROM AttributeDefinition "
                  "WHERE Code IN ('ENT_NAMED_USERS', 'ENT_TOTAL_NAMED_USERS') ORDER BY Code ASC",
         "operation": "Upsert", "externalId": "Code"},
        {"query": "SELECT Code, Description, Id, Name FROM AttributeCategory "
                  "WHERE Code LIKE 'AC-ENT-%' ORDER BY Code ASC",
         "operation": "Upsert", "externalId": "Code"},
        {"query": "SELECT AttributeCategoryId, AttributeDefinitionId, Id, "
                  "AttributeCategory.Code, AttributeDefinition.Code "
                  "FROM AttributeCategoryAttribute "
                  "WHERE AttributeCategory.Code LIKE 'AC-ENT-%' "
                  "ORDER BY AttributeCategory.Code ASC, "
                  "AttributeDefinition.Code ASC",
         "operation": "Upsert",
         "externalId": "AttributeCategory.Code;AttributeDefinition.Code"},
        {"query": "SELECT Code, Id, Name, ParentProductClassificationId, "
                  "Status FROM ProductClassification "
                  "WHERE Code LIKE 'PC-ENT-%' ORDER BY Code ASC",
         "operation": "Upsert", "externalId": "Code"},
        {"query": "SELECT AttributeCategoryId, AttributeDefinitionId, DefaultValue, "
                  "Id, IsHidden, IsPriceImpacting, IsReadOnly, IsRequired, "
                  "Name, ProductClassificationId, Sequence, Status "
                  "FROM ProductClassificationAttr "
                  "WHERE ProductClassification.Code LIKE 'PC-ENT-%' "
                  "ORDER BY Name ASC",
         "operation": "Upsert", "externalId": "Name"},
        # QB-DB is in scope because this plan restates it under its Censhare
        # name and the bundle's usage component resolves its child lookup
        # against it.
        {"query": "SELECT BasedOnId, BasedOn.Code, ConfigureDuringSale, "
                  "Description, Family, Id, IsActive, IsAssetizable, "
                  "IsSoldOnlyWithOtherProds, Name, ProductCode, "
                  "StockKeepingUnit, Type "
                  "FROM Product2 "
                  "WHERE StockKeepingUnit LIKE 'DEMO-%' "
                  "OR StockKeepingUnit = 'QB-DB' "
                  "ORDER BY StockKeepingUnit ASC",
         "operation": "Upsert", "externalId": "StockKeepingUnit"},
        {"query": "SELECT AttributeCategoryId, AttributeDefinitionId, DefaultValue, "
                  "Id, IsHidden, IsPriceImpacting, IsReadOnly, IsRequired, "
                  "Name, Product2Id, ProductClassificationAttributeId, Sequence, "
                  "Status, AttributeDefinition.Code, "
                  "ProductClassificationAttribute.Name, "
                  "Product2.StockKeepingUnit FROM ProductAttributeDefinition "
                  "WHERE AttributeDefinition.Code IN ('ENT_NAMED_USERS', 'ENT_TOTAL_NAMED_USERS') "
                  "ORDER BY Product2.StockKeepingUnit ASC, "
                  "AttributeDefinition.Code ASC",
         "operation": "Upsert",
         "externalId": "AttributeDefinition.Code;Product2.StockKeepingUnit"},
        {"query": "SELECT DoesAutoRenewAssetByDefault, Id, Name, PricingTerm, "
                  "PricingTermUnit, SellingModelType, Status "
                  "FROM ProductSellingModel ORDER BY Name ASC",
         "operation": "Readonly", "externalId": "Name"},
        {"query": "SELECT Id, IsDefault, Product2Id, ProductSellingModelId, "
                  "Product2.StockKeepingUnit, ProductSellingModel.Name "
                  "FROM ProductSellingModelOption "
                  "WHERE Product2.StockKeepingUnit LIKE 'DEMO-%' "
                  "ORDER BY Product2.StockKeepingUnit ASC, "
                  "ProductSellingModel.Name ASC",
         "operation": "Upsert",
         "externalId": "Product2.StockKeepingUnit;ProductSellingModel.Name"},
        {"query": "SELECT AssociatedProductRoleCat, Id, MainProductRoleCat, "
                  "Name FROM ProductRelationshipType ORDER BY Name ASC",
         "operation": "Readonly", "externalId": "Name"},
        {"query": "SELECT Code, Description, Id, MaxBundleComponents, "
                  "MinBundleComponents, Name, ParentProductId, Sequence "
                  "FROM ProductComponentGroup WHERE Code LIKE 'PCG-ENT-%' "
                  "ORDER BY Code ASC",
         "operation": "Upsert", "externalId": "Code"},
        {"query": "SELECT ChildProductId, ChildProductRole, "
                  "DoesBundlePriceIncludeChild, Id, IsComponentRequired, "
                  "IsDefaultComponent, IsQuantityEditable, MaxQuantity, "
                  "MinQuantity, ParentProductId, ParentProductRole, "
                  "ProductComponentGroupId, ProductRelationshipTypeId, "
                  "Quantity, QuoteVisibility, Sequence, "
                  "ChildProduct.StockKeepingUnit, "
                  "ParentProduct.StockKeepingUnit, ProductComponentGroup.Code, "
                  "ProductRelationshipType.Name FROM ProductRelatedComponent "
                  "WHERE ParentProduct.StockKeepingUnit = 'DEMO-CS-CLOUD' "
                  "ORDER BY ChildProduct.StockKeepingUnit ASC, "
                  "ParentProduct.StockKeepingUnit ASC, "
                  "ProductComponentGroup.Code ASC, "
                  "ProductRelationshipType.Name ASC",
         "operation": "Upsert",
         "externalId": "ChildProduct.StockKeepingUnit;"
                       "ParentProduct.StockKeepingUnit;"
                       "ProductComponentGroup.Code;ProductRelationshipType.Name"},
        {"query": "SELECT CatalogType, Code, Description, Id, Name "
                  "FROM ProductCatalog WHERE Code = 'CAT-ENTIRELY' "
                  "ORDER BY Code ASC",
         "operation": "Upsert", "externalId": "Code"},
        {"query": "SELECT CatalogId, Code, Description, Id, IsNavigational, "
                  "Name, ParentCategoryId, SortOrder FROM ProductCategory "
                  "WHERE Catalog.Code = 'CAT-ENTIRELY' ORDER BY Code ASC",
         "operation": "Upsert", "externalId": "Code"},
        {"query": "SELECT CatalogId, Id, IsPrimaryCategory, "
                  "ProductCategoryId, ProductId, ProductCategory.Code, "
                  "Product.StockKeepingUnit FROM ProductCategoryProduct "
                  "WHERE Catalog.Code = 'CAT-ENTIRELY' "
                  "ORDER BY ProductCategory.Code ASC, "
                  "Product.StockKeepingUnit ASC",
         "operation": "Upsert",
         "externalId": "ProductCategory.Code;Product.StockKeepingUnit"},
    ],
    "apiVersion": "68.0",
    "excludeIdsFromCSVFiles": "true",
    "orgs": [],
}

PRICING_EXPORT = {
    "objects": [
        {"query": "SELECT Id, StockKeepingUnit FROM Product2 "
                  "WHERE StockKeepingUnit LIKE 'DEMO-%' "
                  "ORDER BY StockKeepingUnit ASC",
         "operation": "Readonly", "externalId": "StockKeepingUnit"},
        {"query": "SELECT Id, Name, SellingModelType FROM ProductSellingModel "
                  "ORDER BY Name ASC",
         "operation": "Readonly", "externalId": "Name"},
        {"query": "SELECT Code, Id, Name FROM AttributeDefinition "
                  "WHERE Code IN ('ENT_NAMED_USERS', 'ENT_TOTAL_NAMED_USERS') ORDER BY Code ASC",
         "operation": "Readonly", "externalId": "Code"},
        {"query": "SELECT Id, IsActive, IsStandard, Name FROM Pricebook2 "
                  "WHERE IsStandard = true",
         "operation": "Readonly", "externalId": "Name"},
        {"query": "SELECT AdjustmentMethod, Id, IsActive, Name, ScheduleType "
                  "FROM PriceAdjustmentSchedule ORDER BY Name ASC",
         "operation": "Readonly", "externalId": "Name"},
        {"query": "SELECT CurrencyIsoCode, Id, IsActive, IsDerived, Name, "
                  "Pricebook2Id, Product2Id, ProductSellingModelId, UnitPrice, "
                  "Product2.StockKeepingUnit, ProductSellingModel.Name "
                  "FROM PricebookEntry "
                  "WHERE Product2.StockKeepingUnit LIKE 'DEMO-%' "
                  "ORDER BY Product2.StockKeepingUnit ASC, "
                  "ProductSellingModel.Name ASC, CurrencyIsoCode ASC",
         "operation": "Upsert",
         "externalId": "Product2.StockKeepingUnit;ProductSellingModel.Name;"
                       "CurrencyIsoCode"},
        {"query": "SELECT AdjustmentType, CurrencyIsoCode, EffectiveFrom, "
                  "EffectiveTo, Id, LowerBound, PriceAdjustmentScheduleId, "
                  "Product2Id, ProductSellingModelId, TierType, TierValue, "
                  "UpperBound, PriceAdjustmentSchedule.Name, "
                  "Product2.StockKeepingUnit, ProductSellingModel.Name "
                  "FROM PriceAdjustmentTier "
                  "WHERE Product2.StockKeepingUnit LIKE 'DEMO-%' "
                  "ORDER BY Product2.StockKeepingUnit ASC, LowerBound ASC",
         "operation": "Upsert",
         "externalId": "PriceAdjustmentSchedule.Name;"
                       "Product2.StockKeepingUnit;ProductSellingModel.Name;"
                       "LowerBound;CurrencyIsoCode"},
        {"query": "SELECT Id, Name FROM AttributeBasedAdjRule "
                  "WHERE Name LIKE 'ENT-%' ORDER BY Name ASC",
         "operation": "Upsert", "externalId": "Name"},
        {"query": "SELECT AttributeBasedAdjRuleId, AttributeDefinitionId, Id, "
                  "StringValue, Operator, ProductId, "
                  "AttributeBasedAdjRule.Name, AttributeDefinition.Code, "
                  "Product.StockKeepingUnit FROM AttributeAdjustmentCondition "
                  "WHERE AttributeBasedAdjRule.Name LIKE 'ENT-%' "
                  "ORDER BY AttributeBasedAdjRule.Name ASC, "
                  "AttributeDefinition.Code ASC, "
                  "Product.StockKeepingUnit ASC, Operator ASC, "
                  "StringValue ASC",
         "operation": "Upsert",
         "externalId": "AttributeBasedAdjRule.Name;AttributeDefinition.Code;"
                       "Product.StockKeepingUnit"},
        {"query": "SELECT AdjustmentType, AdjustmentValue, "
                  "AttributeBasedAdjRuleId, CurrencyIsoCode, EffectiveFrom, "
                  "EffectiveTo, Id, PriceAdjustmentScheduleId, ProductId, "
                  "ProductSellingModelId, AttributeBasedAdjRule.Name, "
                  "PriceAdjustmentSchedule.Name, Product.StockKeepingUnit, "
                  "ProductSellingModel.Name FROM AttributeBasedAdjustment "
                  "WHERE AttributeBasedAdjRule.Name LIKE 'ENT-%' "
                  "ORDER BY AttributeBasedAdjRule.Name ASC, "
                  "PriceAdjustmentSchedule.Name ASC, "
                  "Product.StockKeepingUnit ASC, ProductSellingModel.Name ASC, "
                  "CurrencyIsoCode ASC",
         "operation": "Upsert",
         "externalId": "AttributeBasedAdjRule.Name;"
                       "PriceAdjustmentSchedule.Name;"
                       "Product.StockKeepingUnit;ProductSellingModel.Name;"
                       "CurrencyIsoCode"},
        {"query": "SELECT ContributingProductId, CurrencyIsoCode, "
                  "DerivedPricingScope, EffectiveFrom, EffectiveTo, Formula, "
                  "Id, PricebookEntryId, PricebookId, PricingSource, "
                  "ProductId, ProductSellingModelId, "
                  "ContributingProduct.StockKeepingUnit, "
                  "Product.StockKeepingUnit, ProductSellingModel.Name "
                  "FROM PricebookEntryDerivedPrice "
                  "WHERE Product.StockKeepingUnit LIKE 'DEMO-%' "
                  "ORDER BY Product.StockKeepingUnit ASC, "
                  "ContributingProduct.StockKeepingUnit ASC, "
                  "ProductSellingModel.Name ASC, CurrencyIsoCode ASC",
         "operation": "Upsert",
         "externalId": "Product.StockKeepingUnit;"
                       "ContributingProduct.StockKeepingUnit;"
                       "ProductSellingModel.Name;CurrencyIsoCode"},
    ],
    "apiVersion": "68.0",
    "excludeIdsFromCSVFiles": "true",
    "orgs": [],
}


# --------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", required=True, type=Path)
    parser.add_argument("--check", action="store_true",
                        help="report what would be written and verify the "
                             "workbook's own arithmetic, writing nothing")
    args = parser.parse_args()

    if not args.workbook.exists():
        print(f"workbook not found: {args.workbook}", file=sys.stderr)
        return 2

    cat = Catalogue(Workbook(args.workbook))
    print(f"read {len(cat.products)} products, {len(cat.rules)} band rows, "
          f"{len(cat.quotes)} quotes, {len(cat.lines)} quote lines")

    expected = build_expected_quotes(cat)
    problems = verify_workbook(cat, expected)
    for p in problems:
        print(f"  WARNING {p}")

    if args.check:
        print("check only, nothing written")
        return 1 if problems else 0

    build_pcm(cat)
    build_pricing(cat)
    EXPECTED_QUOTES.write_text(json.dumps(expected, indent=2) + "\n")

    for directory in (PCM_DIR, PRICING_DIR):
        counts = {
            f.name: sum(1 for _ in f.open()) - 1
            for f in sorted(directory.glob("*.csv"))
        }
        print(f"\n{directory.relative_to(REPO)}")
        for name, n in counts.items():
            print(f"  {name:38} {n:5} rows")
    print(f"\n{EXPECTED_QUOTES.relative_to(REPO)}  "
          f"{len(expected['quotes'])} quotes")
    return 1 if problems else 0


def verify_workbook(cat: Catalogue, expected: dict) -> list[str]:
    """Re-add the workbook's own line totals and compare with its headline
    figures, so a workbook change that breaks a proof point is caught here
    rather than against a live quote."""
    problems = []
    for qid, quote in expected["quotes"].items():
        buckets = {"Monthly": Decimal(0), "Annual": Decimal(0),
                   "One-time": Decimal(0)}
        for line in quote["lines"]:
            buckets[line["billingPeriod"]] += Decimal(line["lineTotal"] or 0)
        want = quote["totals"]
        checks = [
            ("monthly", buckets["Monthly"], Decimal(want["monthly"] or 0)),
            ("annual", buckets["Annual"], Decimal(want["annual"] or 0)),
            ("oneTime", buckets["One-time"], Decimal(want["oneTime"] or 0)),
            ("first12Months",
             buckets["Monthly"] * 12 + buckets["Annual"] + buckets["One-time"],
             Decimal(want["first12Months"] or 0)),
        ]
        for label, got, target in checks:
            if abs(got - target) > Decimal("0.01"):
                problems.append(
                    f"{qid} {label}: lines add to {got}, header says {target}")
    return problems


if __name__ == "__main__":
    raise SystemExit(main())
