#!/usr/bin/env python3
"""Place one of the workbook's example quotes on the Kestrel opportunity.

Act 2 is a *click* demo: the quote the audience sees is built in the
configurator. This script exists for the other half — checking that the catalog
and the pricing procedure actually produce the numbers the workbook promises,
without a browser. It places the lines directly through Place Sales Transaction
with the configurator switched off, so what it measures is pricing alone:
volume bands, the print band, derived support and its minimum.

It is a verification tool, not part of the demo and not part of the build. The
quote it leaves behind is disposable; ``--replace`` deletes the previous one it
made before placing a new one.

    python scripts/entirely/build_test_quote.py --target-org Entirely --expect DEMO-CS-01
    python scripts/entirely/build_test_quote.py --target-org Entirely --expect DEMO-CS-02 --replace

Pair it with ``check_quote_totals.py``, which compares the placed quote against
``expected_quotes.json`` line by line.

Attribute-priced lines are the one thing it cannot reproduce on its own: the
print module's band normally comes from the CML model counting users across the
configuration, and there is no configuration here. ``--set-attribute`` writes the
band onto the line so the attribute adjustment still fires::

    --set-attribute DEMO-CS-09=ENT_NAMED_USERS:61-120

``--bundle DEMO-CS-CLOUD`` places the same lines as components of the bundle
instead of flat, which gives the configurator a root line to run the constraint
model against (``connect/cpq/configurator/actions/configure``).
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXPECTED = Path(__file__).resolve().parent / "expected_quotes.json"
API = "v68.0"

QUOTE_READY = {"CompletedWithPricing", "CompletedWithTax", "TaxCalculationSuccess",
               "CompletedWithoutPricing"}
QUOTE_FAILED = {"PriceCalculationFailed", "TaxCalculationFailed",
                "SaveFailedOrIncomplete"}

# The workbook's billing periods, as ProductSellingModel names.
SELLING_MODEL = {"Monthly": "Term Monthly", "Annual": "Term Annual",
                 "One-time": "One-Time"}

# A recurring line must bill on its selling model's own period: an annual product
# billed monthly needs a Billing Treatment the catalog does not define, and the
# place call rejects it.
BILLING_FREQUENCY = {"Monthly": "Monthly", "Annual": "Annual"}


class StepError(RuntimeError):
    pass


def _run(args, timeout=300):
    env = {**os.environ, "SF_TEMP_SHOW_SECRETS": "true"}
    p = subprocess.run(args, capture_output=True, text=True, env=env,
                       timeout=timeout)
    return p.returncode, p.stdout, p.stderr


def sf_query(org, soql):
    _rc, out, err = _run(["sf", "data", "query", "-q", soql,
                          "--target-org", org, "--json"])
    try:
        d = json.loads(out)
    except json.JSONDecodeError:
        raise StepError(f"query failed: {(err or out)[:300]}")
    if "result" not in d:
        raise StepError(f"query failed: {str(d.get('message', out))[:300]}")
    return d["result"]["records"]


def sf_rest(org, path, method="GET", body=None, attempts=3):
    """Call a Connect resource, retrying an empty response.

    `sf api request` intermittently returns a bare "Error (1):" with no body on
    this org. It is a transport hiccup, not a rejection — the same call succeeds
    on the next try — so retry rather than reporting a failure that is not one.
    """
    args = ["sf", "api", "request", "rest", path, "--target-org", org,
            "--method", method]
    if body is not None:
        args += ["--body", json.dumps(body)]
    last = ""
    for attempt in range(attempts):
        _rc, out, err = _run(args)
        text = (out.strip() or err.strip())
        # The CLI prints an update banner on stderr; drop anything before the JSON.
        start = next((i for i, ch in enumerate(text) if ch in "[{"), None)
        if start is not None:
            try:
                return json.loads(text[start:])
            except json.JSONDecodeError:
                pass
        last = text
        if attempt + 1 < attempts:
            time.sleep(5)
    raise StepError(f"{method} {path} -> unparseable response after {attempts} "
                    f"attempt(s): {last[:300]}")


def resolve_ids(org, account, opportunity):
    rows = sf_query(org, "SELECT Id, CurrencyIsoCode FROM Account "
                         f"WHERE Name = '{account}' LIMIT 1")
    if not rows:
        raise StepError(f"no account named {account!r}")
    account_id, currency = rows[0]["Id"], rows[0]["CurrencyIsoCode"]

    rows = sf_query(org, "SELECT Id, Pricebook2Id FROM Opportunity "
                         f"WHERE AccountId = '{account_id}' "
                         f"AND Name = '{opportunity}' LIMIT 1")
    if not rows:
        raise StepError(f"no opportunity named {opportunity!r} on {account!r}")
    opp_id, pricebook_id = rows[0]["Id"], rows[0]["Pricebook2Id"]
    if not pricebook_id:
        rows = sf_query(org, "SELECT Id FROM Pricebook2 WHERE IsStandard = true "
                             "LIMIT 1")
        pricebook_id = rows[0]["Id"]
    return account_id, currency, opp_id, pricebook_id


def resolve_lines(org, quote, currency):
    """Attach the price book entry and selling model to each expected line."""
    skus = sorted({line["sku"] for line in quote["lines"]})
    in_list = ", ".join(f"'{s}'" for s in skus)
    rows = sf_query(org,
                    "SELECT Id, Product2Id, Product2.StockKeepingUnit, UnitPrice, "
                    "ProductSellingModel.Name, ProductSellingModel.SellingModelType "
                    "FROM PricebookEntry "
                    f"WHERE Product2.StockKeepingUnit IN ({in_list}) "
                    f"AND CurrencyIsoCode = '{currency}' AND IsActive = true")
    by_key = {(r["Product2"]["StockKeepingUnit"],
               r["ProductSellingModel"]["Name"]): r for r in rows}

    resolved = []
    for line in quote["lines"]:
        model = SELLING_MODEL[line["billingPeriod"]]
        pbe = by_key.get((line["sku"], model))
        if pbe is None:
            raise StepError(
                f"no active {currency} price book entry for {line['sku']} on "
                f"{model}. Load entirely-pricing first."
            )
        resolved.append({
            "sku": line["sku"],
            "productId": pbe["Product2Id"],
            "pbeId": pbe["Id"],
            "unitPrice": float(pbe["UnitPrice"]),
            "quantity": float(line["quantity"]),
            "sellingModelType": pbe["ProductSellingModel"]["SellingModelType"],
            "billingFrequency": BILLING_FREQUENCY.get(line["billingPeriod"]),
        })
    return resolved


def resolve_bundle(org, bundle_sku, lines, currency):
    """Root line plus, per expected line, the component row that attaches it.

    The configurator only runs rules against a bundle root, so a flat quote
    cannot exercise the constraint model. A line whose SKU is not a component
    of the bundle stops the build rather than landing outside it.
    """
    rows = sf_query(org,
                    "SELECT Id, Product2Id, UnitPrice, ProductSellingModel.Name, "
                    "ProductSellingModel.SellingModelType FROM PricebookEntry "
                    f"WHERE Product2.StockKeepingUnit = '{bundle_sku}' "
                    f"AND CurrencyIsoCode = '{currency}' AND IsActive = true")
    if not rows:
        raise StepError(f"no active {currency} price book entry for {bundle_sku}")
    pbe = next((r for r in rows
                if r["ProductSellingModel"]["Name"] == SELLING_MODEL["Monthly"]),
               rows[0])
    root = {
        "sku": bundle_sku,
        "productId": pbe["Product2Id"],
        "pbeId": pbe["Id"],
        "unitPrice": float(pbe["UnitPrice"]),
        "quantity": 1.0,
        "sellingModelType": pbe["ProductSellingModel"]["SellingModelType"],
        "billingFrequency": "Monthly",
    }

    prcs = sf_query(org,
                    "SELECT Id, ChildProduct.StockKeepingUnit, ProductRelationshipTypeId, "
                    "DoesBundlePriceIncludeChild FROM ProductRelatedComponent "
                    f"WHERE ParentProduct.StockKeepingUnit = '{bundle_sku}'")
    by_sku = {r["ChildProduct"]["StockKeepingUnit"]: r for r in prcs}
    relationships = []
    for line in lines:
        prc = by_sku.get(line["sku"])
        if prc is None:
            raise StepError(f"{line['sku']} is not a component of {bundle_sku}")
        relationships.append({
            "ProductRelatedComponentId": prc["Id"],
            "ProductRelationshipTypeId": prc["ProductRelationshipTypeId"],
            "AssociatedQuoteLinePricing": (
                "IncludedInBundlePrice" if prc["DoesBundlePriceIncludeChild"]
                else "NotIncludedInBundlePrice"),
        })
    return root, relationships


def place(org, ids, lines, start, end, name, attributes=None, bundle=None,
          run_rules=False):
    records = [{
        "referenceId": "refQuote",
        "record": {
            "attributes": {"type": "Quote", "method": "POST"},
            "Name": name,
            "QuoteAccountId": ids["account"],
            "OpportunityId": ids["opportunity"],
            "Pricebook2Id": ids["pricebook"],
            "CurrencyIsoCode": ids["currency"],
            "Status": "Draft",
            "StartDate": start,
        },
    }]
    root, relationships = bundle or (None, [])
    if root:
        lines = [root] + lines
        relationships = [None] + relationships
    for i, line in enumerate(lines):
        record = {
            "attributes": {"type": "QuoteLineItem", "method": "POST"},
            "QuoteId": "@{refQuote.id}",
            "Product2Id": line["productId"],
            "PricebookEntryId": line["pbeId"],
            "UnitPrice": line["unitPrice"],
            "Quantity": line["quantity"],
            "StartDate": start,
        }
        # Which line fields are legal follows the selling model, not the product.
        if line["sellingModelType"] == "TermDefined":
            record["EndDate"] = end
        if line["sellingModelType"] != "OneTime":
            record["BillingFrequency"] = line["billingFrequency"]
            record["PeriodBoundary"] = "Anniversary"
        records.append({"referenceId": f"refLine{i}", "record": record})
        for j, fields in enumerate((attributes or {}).get(line["sku"], [])):
            records.append({"referenceId": f"refLine{i}Attr{j}", "record": {
                "attributes": {"type": "QuoteLineItemAttribute", "method": "POST"},
                "QuoteLineItemId": f"@{{refLine{i}.id}}",
                **fields,
            }})
        if root and relationships[i]:
            records.append({"referenceId": f"refLine{i}Rel", "record": {
                "attributes": {"type": "QuoteLineRelationship", "method": "POST"},
                "MainQuoteLineId": "@{refLine0.id}",
                "AssociatedQuoteLineId": f"@{{refLine{i}.id}}",
                **relationships[i],
            }})

    payload = {
        "pricingPref": "system",
        "configurationPref": {
            "configurationMethod": "Force" if run_rules else "skip",
            "configurationOptions": {
                "validateProductCatalog": run_rules,
                "validateAmendRenewCancel": False,
                "executeConfigurationRules": run_rules,
                "addDefaultConfiguration": False,
            },
        },
        "graph": {"graphId": "entirelyTestQuote", "records": records},
    }
    resp = sf_rest(org, f"/services/data/{API}/connect/rev/sales-transaction/"
                        "actions/place", "POST", payload)

    # This API reports per-record failures in an errorResponse array while still
    # returning HTTP 200 and still creating the parent Quote, so "did I get an
    # id" reports success on a quote with no lines. Check the flag first.
    if isinstance(resp, list) and resp and "errorCode" in resp[0]:
        raise StepError(f"place: {resp[0].get('message', resp[0])}")
    if isinstance(resp, dict):
        errors = resp.get("errorResponse") or []
        if errors or resp.get("isSuccess") is False:
            detail = "; ".join(
                f"{e.get('referenceId', '?')}: {e.get('message', e)}"
                for e in errors
            ) or json.dumps(resp)[:400]
            raise StepError(f"place failed: {detail}")

    quote_id = None
    if isinstance(resp, dict):
        for key in ("quoteId", "salesTransactionId", "id"):
            if resp.get(key):
                quote_id = resp[key]
                break
    if not quote_id:
        rows = sf_query(org, "SELECT Id FROM Quote WHERE OpportunityId = "
                             f"'{ids['opportunity']}' ORDER BY CreatedDate DESC "
                             "LIMIT 1")
        quote_id = rows[0]["Id"] if rows else None
    if not quote_id:
        raise StepError(f"place returned no quote id: {json.dumps(resp)[:400]}")
    return quote_id


def wait_for_pricing(org, quote_id, timeout=300, interval=10):
    deadline = time.time() + timeout
    status = None
    while time.time() < deadline:
        rows = sf_query(org, "SELECT CalculationStatus FROM Quote "
                             f"WHERE Id = '{quote_id}'")
        status = rows[0]["CalculationStatus"] if rows else None
        if status in QUOTE_READY:
            return status
        if status in QUOTE_FAILED:
            raise StepError(f"quote {quote_id} pricing failed: {status}")
        time.sleep(interval)
    raise StepError(f"quote {quote_id} still {status!r} after {timeout}s")


def resolve_attributes(org, spec, skus):
    """Turn ``SKU=CODE:VALUE`` entries into QuoteLineItemAttribute fields.

    The configurator normally supplies these. With it switched off, an
    attribute-priced line has no value to match an adjustment against, so the
    band never fires and the line stays at its list price.

    The values go into the place call itself, so the quote is priced once with
    them present. Writing them after placing would leave a quote priced without
    them, and there is no separate reprice action to call.

    A picklist attribute carries its AttributePicklistValue as well as the text:
    the adjustment condition compares the picklist value, and a row with only
    the text is not matched.
    """
    attributes = {}
    for entry in spec:
        sku, _, rest = entry.partition("=")
        code, _, value = rest.partition(":")
        if sku not in skus:
            raise StepError(f"--set-attribute names {sku}, which is not on the quote")
        rows = sf_query(org, "SELECT Id, PicklistId FROM AttributeDefinition "
                             f"WHERE Code = '{code}'")
        if not rows:
            raise StepError(f"no attribute definition with code {code!r}")
        fields = {"AttributeDefinitionId": rows[0]["Id"], "AttributeValue": value}
        if rows[0].get("PicklistId"):
            values = sf_query(org, "SELECT Id FROM AttributePicklistValue "
                                   f"WHERE PicklistId = '{rows[0]['PicklistId']}' "
                                   f"AND Value = '{value}'")
            if not values:
                raise StepError(f"{code!r} has no picklist value {value!r}")
            fields["AttributePicklistValueId"] = values[0]["Id"]
        attributes.setdefault(sku, []).append(fields)
        print(f"  attribute {sku}.{code} = {value}", file=sys.stderr)
    return attributes


def main():
    parser = argparse.ArgumentParser(
        description="Place a workbook example quote for verification. MUTATING.")
    parser.add_argument("--target-org", required=True,
                        help="SF CLI alias or username; not a CCI org alias.")
    parser.add_argument("--expect", required=True,
                        help="Quote key in expected_quotes.json, e.g. DEMO-CS-01.")
    parser.add_argument("--account", default="Kestrel Home & Living GmbH")
    parser.add_argument("--opportunity",
                        default="Kestrel Home & Living GmbH - Censhare Cloud")
    parser.add_argument("--start", default="2027-01-01")
    parser.add_argument("--set-attribute", action="append", default=[],
                        metavar="SKU=CODE:VALUE",
                        help="Attribute value the configurator would have set.")
    parser.add_argument("--bundle", metavar="SKU",
                        help="Place the lines as components of this bundle, so "
                             "the configurator can run against the quote.")
    parser.add_argument("--run-config-rules", action="store_true",
                        help="Run the constraint model while placing (needs "
                             "--bundle); it then sets the computed attributes.")
    parser.add_argument("--replace", action="store_true",
                        help="Delete this script's previous quote first.")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()

    quotes = json.loads(EXPECTED.read_text())["quotes"]
    if args.expect not in quotes:
        raise SystemExit(f"unknown quote {args.expect!r}; "
                         f"expected one of {', '.join(sorted(quotes))}")
    quote = quotes[args.expect]

    org = args.target_org
    account_id, currency, opp_id, pricebook_id = resolve_ids(
        org, args.account, args.opportunity)
    if currency != quote["currency"]:
        raise SystemExit(f"{args.account} is in {currency}, but {args.expect} "
                         f"is quoted in {quote['currency']}")

    name = f"Verification {args.expect}"
    if args.replace:
        for row in sf_query(org, "SELECT Id FROM Quote "
                                 f"WHERE OpportunityId = '{opp_id}' "
                                 f"AND Name = '{name}'"):
            _run(["sf", "data", "delete", "record", "-s", "Quote",
                  "-i", row["Id"], "--target-org", org])
            print(f"deleted previous {row['Id']}", file=sys.stderr)

    # The term is inclusive of both ends, so a 12-month term starting 2027-01-01
    # ends 2027-12-31. Landing on 2028-01-01 instead bills a 13th month and
    # inflates every line total by a month's worth.
    months = int(quote["termMonths"])
    start_date = date.fromisoformat(args.start)
    end_month = start_date.month + months
    end = (date(start_date.year + (end_month - 1) // 12,
                (end_month - 1) % 12 + 1, start_date.day)
           - timedelta(days=1)).isoformat()

    lines = resolve_lines(org, quote, currency)
    skus = {line["sku"] for line in lines} | ({args.bundle} if args.bundle else set())
    attributes = resolve_attributes(org, args.set_attribute, skus)
    ids = {"account": account_id, "currency": currency, "opportunity": opp_id,
           "pricebook": pricebook_id}
    bundle = (resolve_bundle(org, args.bundle, lines, currency)
              if args.bundle else None)
    if args.run_config_rules and not args.bundle:
        raise SystemExit("--run-config-rules needs --bundle: rules run on a bundle root")
    quote_id = place(org, ids, lines, args.start, end, name, attributes, bundle,
                     args.run_config_rules)
    print(f"placed quote {quote_id} ({len(lines)} line(s)"
          f"{' under ' + args.bundle if args.bundle else ''})", file=sys.stderr)

    status = wait_for_pricing(org, quote_id, timeout=args.timeout)
    print(f"pricing {status}", file=sys.stderr)
    print(quote_id)


if __name__ == "__main__":
    try:
        main()
    except StepError as exc:
        raise SystemExit(f"FAILED: {exc}")
